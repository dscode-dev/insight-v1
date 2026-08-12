"""BRA.csv / ARG.csv do football-data.co.uk → atlas.match.v1.

POR QUE UM CONVERSOR SEPARADO, E NÃO UM FLAG NO OUTRO. Os arquivos
sul-americanos do football-data são um formato DIFERENTE dos europeus, não
uma versão reduzida deles:

    europeu           sul-americano
    HomeTeam/AwayTeam Home/Away
    FTHG/FTAG         HG/AG
    HTHG/HTAG         (não existe)
    HS/HST/HC/HF/HY/HR (não existem)
    B365H + B365CH    só as de fechamento
    um arquivo por temporada  um arquivo com a coluna Season

Um único conversor com condicionais para os dois viraria uma função onde
metade das linhas nunca roda para metade das entradas — e a linha errada
rodando é como o placar do intervalo apareceria como 0-0 em vez de ausente.

O QUE ESTE ARQUIVO TRAZ, DECLARADO: `core` e `market_close`. Nada mais. É
literalmente o que o CSV tem, e é a exigência declarada em
`EXIGENCIA_POR_COMPETICAO` para estas competições — porque nenhuma fonte
pública publica chute, escanteio ou cartão histórico do futebol
sul-americano, e uma barra que exigisse isso não deixaria estas partidas mais
completas, deixaria o Atlas sem elas.

O FUSO É A ARMADILHA. O football-data mantém TODOS os arquivos em hora do
Reino Unido, inclusive os sul-americanos, e não escreve isso em lugar nenhum.
Lidas como UTC, 210 de 1.785 partidas brasileiras caíam no dia seguinte — e o
dia entra no uid, então cada uma viraria uma partida fantasma. Convertido, o
que temos do ESPN casa 1.899/1.899.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from explorer.clubs import resolve_club

#: O fuso em que a FONTE publica. Não o do estádio. Ver o docstring.
FUSO_DA_FONTE = "Europe/London"

#: `Country` + `League` do arquivo → a competição como o Atlas a nomeia.
#:
#: Mapa explícito, e não uma normalização do texto: `Liga Profesional ` vem
#: com espaço no fim em parte das linhas, e derivar a chave de um texto que
#: varia produziria duas competições com o mesmo nome — que é exatamente como
#: um histórico de clube se parte ao meio.
COMPETICAO = {
    ("Brazil", "Serie A"): "brasileirao",
    ("Argentina", "Liga Profesional"): "argentina_liga_profesional",
    ("Argentina", "Copa De La Liga Profesional"): "argentina_copa_liga_profesional",
}

#: As três cotações de fechamento, em ordem de preferência.
#:
#: Pinnacle primeiro porque é a casa com menor margem do arquivo e a que
#: menos arredonda; `Avg` é a média do mercado e serve quando a Pinnacle não
#: cotou; `B365` fecha. Preferir a de menor margem NÃO é otimização: é a que
#: menos distorce a probabilidade implícita, que é o que vira dimensão.
CASAS = (
    ("pinnacle", ("PSCH", "PSCD", "PSCA")),
    ("mercado_medio", ("AvgCH", "AvgCD", "AvgCA")),
    ("bet365", ("B365CH", "B365CD", "B365CA")),
)


def _texto(linha: dict, coluna: str) -> str:
    valor = linha.get(coluna)
    return "" if valor is None else str(valor).strip()


def _instante(linha: dict) -> str | None:
    """`19/05/2012` + `22:30` em hora do Reino Unido → o instante em UTC."""
    data = _texto(linha, "Date")
    hora = _texto(linha, "Time")
    momento = None
    for formato in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            momento = datetime.strptime(data, formato)
            break
        except ValueError:
            continue
    if momento is None:
        return None
    if not hora:
        # Meio-dia, e não meia-noite: converter meia-noite local move a
        # partida para o dia anterior quando o fuso está adiante de UTC,
        # inventando um deslocamento que o arquivo não afirmou.
        return momento.replace(hour=12, tzinfo=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    try:
        h, m = (int(p) for p in hora.split(":")[:2])
    except ValueError:
        h, m = 12, 0
    local = momento.replace(hour=h, minute=m, tzinfo=ZoneInfo(FUSO_DA_FONTE))
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _temporada(bruto: str) -> str | None:
    """`2012` e `2012/2013` são os dois formatos reais do arquivo.

    Sul-americanas cabem num ano civil; a argentina atravessa dois. O contrato
    aceita as duas formas, com hífen.
    """
    bruto = bruto.strip()
    if bruto.isdigit() and len(bruto) == 4:
        return bruto
    if "/" in bruto:
        inicio, fim = bruto.split("/", 1)
        if inicio.strip().isdigit() and fim.strip().isdigit():
            return f"{inicio.strip()}-{fim.strip()}"
    return None


def _fechamento(linha: dict) -> tuple[str, dict] | None:
    """A primeira casa que cotou as três, na ordem de preferência.

    Devolve `None` quando nenhuma cotou — o que acontece nas temporadas mais
    antigas do arquivo. Sem mercado a partida não atende `market_close`, e
    fica de fora em vez de entrar com uma cotação inventada.
    """
    for nome, colunas in CASAS:
        valores = []
        for coluna in colunas:
            try:
                valores.append(float(_texto(linha, coluna)))
            except ValueError:
                break
        if len(valores) == 3 and all(v > 1.0 for v in valores):
            return nome, {
                "home": valores[0],
                "draw": valores[1],
                "away": valores[2],
            }
    return None


def _trio(linha: dict, colunas: tuple[str, str, str]) -> dict | None:
    valores = []
    for coluna in colunas:
        try:
            valores.append(float(_texto(linha, coluna)))
        except ValueError:
            return None
    if not all(v > 1.0 for v in valores):
        return None
    return {"home": valores[0], "draw": valores[1], "away": valores[2]}


def _espalhamento(linha: dict) -> dict | None:
    """Média do mercado e melhor preço, se as duas estiverem completas.

    As duas ou nenhuma: a dispersão é a DIFERENÇA entre elas, e meia
    dispersão não existe.
    """
    consenso = _trio(linha, ("AvgCH", "AvgCD", "AvgCA"))
    melhor = _trio(linha, ("MaxCH", "MaxCD", "MaxCA"))
    if consenso is None or melhor is None:
        return None
    return {"consensus": consenso, "best": melhor}


def converter(linha: dict, indice: int) -> tuple[dict | None, str]:
    """Uma linha do CSV → um registro, ou `None` e o motivo da recusa."""
    chave = (_texto(linha, "Country"), _texto(linha, "League").strip())
    competicao = COMPETICAO.get(chave)
    if competicao is None:
        return None, f"competição não mapeada: {chave[0]}/{chave[1]}"

    temporada = _temporada(_texto(linha, "Season"))
    if temporada is None:
        return None, f"temporada ilegível: {_texto(linha, 'Season')!r}"

    kickoff = _instante(linha)
    if kickoff is None:
        return None, f"data ilegível: {_texto(linha, 'Date')!r}"

    casa = resolve_club(_texto(linha, "Home"))
    fora = resolve_club(_texto(linha, "Away"))
    if not casa:
        return None, f"clube não resolvido: {_texto(linha, 'Home')!r}"
    if not fora:
        return None, f"clube não resolvido: {_texto(linha, 'Away')!r}"

    try:
        gols_casa = int(float(_texto(linha, "HG")))
        gols_fora = int(float(_texto(linha, "AG")))
    except ValueError:
        return None, "placar ausente ou ilegível"

    mercado = _fechamento(linha)
    if mercado is None:
        return None, "nenhuma casa cotou as três saídas"
    bookmaker, precos = mercado

    # DISPERSÃO: a média do mercado contra o melhor preço.
    #
    # As colunas Max* e Avg* estão em 100% dos dois arquivos sul-americanos e
    # não eram lidas. É o único sinal de mercado novo que existe aqui:
    # over/under e handicap asiático não são publicados para estes
    # campeonatos.
    espalhamento = _espalhamento(linha)
    perfil = ["core", "market_close"]
    if espalhamento is not None:
        perfil.append("market_spread")

    return {
        "schema_version": "atlas.match.v1",
        "identity": {
            "competition": competicao,
            "season": temporada,
            "home_club_id": casa,
            "away_club_id": fora,
            "kickoff_utc": kickoff,
        },
        "result": {
            "status": "finished",
            "home_goals": gols_casa,
            "away_goals": gols_fora,
        },
        "market": (
            {"bookmaker": bookmaker, "closing": precos, "spread": espalhamento}
            if espalhamento is not None
            else {"bookmaker": bookmaker, "closing": precos}
        ),
        "provenance": {
            "source": "football_data",
            # Estável e reconstruível: arquivo + linha. O CSV não traz id
            # próprio, e inventar um sequencial que mude quando o arquivo for
            # rebaixado faria a reingestão parecer uma fonte nova.
            "source_match_id": f"fd-{competicao}-{temporada}-{indice:05d}",
            "collected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "url": "https://www.football-data.co.uk/data.php",
            "profile": perfil,
            "timezone": FUSO_DA_FONTE,
        },
    }, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, action="append", help="BRA.csv/ARG.csv")
    parser.add_argument("--out", required=True, help="arquivo .jsonl de saída")
    args = parser.parse_args()

    saida = Path(args.out)
    escritos = 0
    por_competicao: Counter[str] = Counter()
    recusas: Counter[str] = Counter()
    clubes_nao_resolvidos: Counter[str] = Counter()

    with saida.open("w", encoding="utf-8") as destino:
        for caminho in args.csv:
            # `utf-8-sig`: o arquivo vem com BOM, e sem isto a primeira coluna
            # se chama '﻿Country' e nenhuma linha casa.
            with open(caminho, encoding="utf-8-sig", newline="") as fonte:
                for indice, linha in enumerate(csv.DictReader(fonte)):
                    registro, motivo = converter(linha, indice)
                    if registro is None:
                        recusas[motivo.split(":")[0]] += 1
                        if motivo.startswith("clube não resolvido"):
                            clubes_nao_resolvidos[motivo.split(": ", 1)[1]] += 1
                        continue
                    destino.write(json.dumps(registro, ensure_ascii=False) + "\n")
                    escritos += 1
                    por_competicao[
                        f"{registro['identity']['competition']}/"
                        f"{registro['identity']['season']}"
                    ] += 1

    print(f"convertidos {escritos} registros -> {saida}")
    for chave in sorted(por_competicao):
        print(f"  {chave}: {por_competicao[chave]}")
    if recusas:
        print("\nnão convertidos:", file=sys.stderr)
        for motivo, quantas in recusas.most_common():
            print(f"  {quantas:5d}  {motivo}", file=sys.stderr)
    if clubes_nao_resolvidos:
        print("\nclubes sem id no registro:", file=sys.stderr)
        for nome, quantas in clubes_nao_resolvidos.most_common(40):
            print(f"  {quantas:5d}  {nome}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
