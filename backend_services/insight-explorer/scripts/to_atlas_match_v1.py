"""Converte a linha crua do football-data.co.uk para `atlas.match.v1`.

    python -m scripts.to_atlas_match_v1 --raw-dir <lake>/raw --out partidas.jsonl

O que sai daqui é alimentado ao Atlas pelas portas novas — CLI ou tela do
console. Este script NÃO valida contra o contrato: quem aceita ou recusa é o
Atlas, e uma segunda opinião aqui seria a terceira cópia das regras.

POR QUE RODA NO EXPLORER. É aqui que vive o resolvedor de clubes e o registro
de 299. Duplicar qualquer um dos dois no Atlas criaria duas respostas
possíveis para "que clube é este", que é exatamente a classe de problema que
esta reconstrução está desfazendo.

O QUE A LINHA CRUA TEM. A camada `raw/` guarda o CSV do football-data
verbatim: `HomeTeam`, `FTHG`, `HS`/`AS` (chutes), `HC`/`AC` (escanteios),
`B365H` (abertura) e `B365CH` (fechamento). São os registros mais completos
do lake, e nunca chegaram ao Atlas — é daí que vêm as sete dimensões de
mercado que hoje são constantes zero.

NADA É INVENTADO. Um campo que a linha não tiver sai vazio e o Atlas recusa
nomeando-o. A tentação óbvia — usar a cotação de abertura no lugar da de
fechamento quando esta falta — produziria `line_movement` zero para aquela
partida: exatamente o valor neutro falso que o contrato existe para eliminar.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from explorer.clubs import resolve_club

#: Bet365. `B365H/D/A` é a cotação de abertura; o prefixo `C` marca a de
#: fechamento. As duas são exigidas porque a DIFERENÇA entre elas é o sinal.
ABERTURA = ("B365H", "B365D", "B365A")
FECHAMENTO = ("B365CH", "B365CD", "B365CA")

#: As colunas de fechamento que estavam no arquivo e ninguém lia.
#:
#: 106 colunas baixadas, 29 usadas. Estas estão em 100% dos arquivos europeus
#: — não são um dado novo a coletar, são um dado já em disco.
CONSENSO = ("AvgCH", "AvgCD", "AvgCA")
MELHOR = ("MaxCH", "MaxCD", "MaxCA")
#: Total de gols no fechamento. `AvgC` e não `B365C`: a média do mercado tem
#: menos ruído de uma casa só, e é a que está completa em 100%.
TOTAIS = ("AvgC>2.5", "AvgC<2.5")
#: Handicap asiático de fechamento. `AHCh` é a linha e vem com sinal na
#: direção do mandante.
HANDICAP = ("AHCh", "AvgCAHH", "AvgCAHA")

ESTATISTICA = {
    "shots": ("HS", "AS"),
    "shots_on_target": ("HST", "AST"),
    "corners": ("HC", "AC"),
    "fouls": ("HF", "AF"),
    "yellow_cards": ("HY", "AY"),
    "red_cards": ("HR", "AR"),
}


def _texto(bruto: dict, coluna: str) -> str:
    valor = bruto.get(coluna)
    return "" if valor is None else str(valor).strip()


def _inteiro(bruto: dict, coluna: str):
    valor = _texto(bruto, coluna)
    try:
        return int(float(valor))
    except ValueError:
        # String vazia, e não None: o Atlas recusa com "precisa ser um número
        # inteiro" apontando a coluna. Omitir o campo diria "ausente", que
        # mandaria o operador procurar no lugar errado.
        return valor


def _decimal(bruto: dict, coluna: str):
    valor = _texto(bruto, coluna)
    try:
        return float(valor)
    except ValueError:
        return valor


#: O fuso em que a FONTE publica. Não o do estádio.
#:
#: football-data.co.uk mantém todos os arquivos em hora do Reino Unido,
#: inclusive os das ligas sul-americanas, e não escreve isso em lugar nenhum.
#: Lido como UTC, 210 de 1.785 partidas brasileiras caíam no dia de calendário
#: seguinte — e o dia entra no uid, então cada uma viraria uma partida
#: fantasma em vez de se juntar à que já existe. Convertendo, as 1.899
#: partidas de Brasileirão que temos do ESPN casam 1.899/1.899 com o CSV.
FUSO_DA_FONTE = "Europe/London"


def _instante(bruto: dict, fuso: str = FUSO_DA_FONTE) -> str:
    """`11/08/2023` + `20:00` em hora do Reino Unido → o instante em UTC.

    A conversão acontece AQUI, antes de o uid ser derivado, porque o uid usa
    o dia UTC. Converter depois não adiantaria: a partida já teria sido
    arquivada sob outro dia.
    """
    data = _texto(bruto, "Date")
    hora = _texto(bruto, "Time")
    for formato in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            momento = datetime.strptime(data, formato)
            break
        except ValueError:
            momento = None
    if momento is None:
        return ""
    if not hora:
        # Sem horário não há o que converter, e converter meia-noite local
        # move a partida para o dia ANTERIOR quando o fuso está adiante de
        # UTC — inventando um deslocamento que o arquivo não afirmou. Meio-dia
        # é o instante mais distante de qualquer fronteira de dia, então a
        # falta de horário nunca muda a data.
        return momento.replace(hour=12, minute=0, tzinfo=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    try:
        h, m = (int(parte) for parte in hora.split(":")[:2])
    except ValueError:
        h, m = 12, 0
    local = momento.replace(hour=h, minute=m, tzinfo=ZoneInfo(fuso))
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _trio(bruto: dict, colunas) -> dict | None:
    valores = []
    for coluna in colunas:
        valor = _decimal(bruto, coluna)
        if not isinstance(valor, float) or valor <= 1.0:
            return None
        valores.append(valor)
    return {"home": valores[0], "draw": valores[1], "away": valores[2]}


def _espalhamento(bruto: dict) -> dict | None:
    """Média do mercado e melhor preço. As duas ou nenhuma: a dispersão é a
    DIFERENÇA entre elas, e meia dispersão não existe."""
    consenso = _trio(bruto, CONSENSO)
    melhor = _trio(bruto, MELHOR)
    if consenso is None or melhor is None:
        return None
    return {"consensus": consenso, "best": melhor}


def _totais(bruto: dict) -> dict | None:
    """O mercado de total de gols, no fechamento.

    A linha é 2.5 fixa nestas colunas — o nome delas a declara. Ler a linha
    de uma coluna que não existe seria inventá-la; declará-la aqui é o que o
    arquivo de fato diz.
    """
    over = _decimal(bruto, TOTAIS[0])
    under = _decimal(bruto, TOTAIS[1])
    if not isinstance(over, float) or not isinstance(under, float):
        return None
    if over <= 1.0 or under <= 1.0:
        return None
    return {"line": 2.5, "over": over, "under": under}


def _handicap(bruto: dict) -> dict | None:
    """Handicap asiático de fechamento, com a linha como o arquivo publica.

    `AHCh` pode ser 0, e zero é uma linha legítima (jogo equilibrado) — por
    isso a checagem é de tipo e não de valor. Tratar 0 como ausente jogaria
    fora exatamente as partidas mais parelhas.
    """
    linha = _decimal(bruto, HANDICAP[0])
    casa = _decimal(bruto, HANDICAP[1])
    fora = _decimal(bruto, HANDICAP[2])
    if not all(isinstance(v, float) for v in (linha, casa, fora)):
        return None
    if casa <= 1.0 or fora <= 1.0:
        return None
    return {"line": linha, "home": casa, "away": fora}


def _perfil(
    *,
    sem_estatistica: bool,
    espalhamento: bool,
    totais: bool,
    handicap: bool,
) -> list[str]:
    """Os blocos que ESTA linha traz. Deduzido do que foi lido, nunca fixo.

    Os arquivos europeus mais antigos não publicam handicap asiático nem
    over/under — as colunas passaram a existir em temporadas diferentes. Um
    perfil fixo declararia blocos ausentes em metade do corpus e o Atlas
    recusaria cada uma dessas linhas, com razão.
    """
    blocos = ["core", "result_halftime", "market_close", "market_open"]
    if espalhamento:
        blocos.append("market_spread")
    if totais:
        blocos.append("market_totals")
    if handicap:
        blocos.append("market_handicap")
    if not sem_estatistica:
        blocos.append("stats")
    return blocos


def converter(
    envelope: dict,
    competicao: str,
    temporada: str,
    *,
    sem_estatistica: bool = False,
) -> dict:
    bruto = envelope.get("raw") or {}
    # Os três blocos que estavam no arquivo e ninguém lia. Cada um entra no
    # perfil só se de fato veio — declarar e não trazer é recusa.
    espalhamento = _espalhamento(bruto)
    totais = _totais(bruto)
    handicap = _handicap(bruto)
    documento = {
        "schema_version": "atlas.match.v1",
        "identity": {
            "competition": competicao,
            "season": temporada,
            # `or ""` e não `or o nome`: um nome não resolvido tem de ser
            # recusado pelo Atlas, não gravado como se fosse um club_id.
            # Foi cair para o nome cru que partiu o histórico de clubes ao
            # meio antes.
            "home_club_id": resolve_club(_texto(bruto, "HomeTeam")) or "",
            "away_club_id": resolve_club(_texto(bruto, "AwayTeam")) or "",
            "kickoff_utc": _instante(bruto),
        },
        "result": {
            "status": "finished",
            "home_goals": _inteiro(bruto, "FTHG"),
            "away_goals": _inteiro(bruto, "FTAG"),
            "home_goals_halftime": _inteiro(bruto, "HTHG"),
            "away_goals_halftime": _inteiro(bruto, "HTAG"),
        },
        "market": {
            "bookmaker": "bet365",
            "opening": {
                "home": _decimal(bruto, ABERTURA[0]),
                "draw": _decimal(bruto, ABERTURA[1]),
                "away": _decimal(bruto, ABERTURA[2]),
            },
            "closing": {
                "home": _decimal(bruto, FECHAMENTO[0]),
                "draw": _decimal(bruto, FECHAMENTO[1]),
                "away": _decimal(bruto, FECHAMENTO[2]),
            },
            **({"spread": espalhamento} if espalhamento else {}),
            **({"totals": totais} if totais else {}),
            **({"handicap": handicap} if handicap else {}),
        },
        "stats": {
            lado: {
                campo: _inteiro(bruto, colunas[indice])
                for campo, colunas in ESTATISTICA.items()
            }
            for indice, lado in enumerate(("home", "away"))
        },
        "provenance": {
            "source": "football_data",
            "source_match_id": str(envelope.get("external_id") or ""),
            "collected_at": str(envelope.get("retrieved_at") or ""),
            "url": str(envelope.get("url") or ""),
            # Os quatro blocos, porque o CSV traz os quatro nas ligas
            # europeias. Nas sul-americanas as colunas de estatística não
            # existem, e `--sem-estatistica` declara só o que há — a
            # composição espera outra fonte trazer os chutes.
            "profile": _perfil(
                sem_estatistica=sem_estatistica,
                espalhamento=espalhamento is not None,
                totais=totais is not None,
                handicap=handicap is not None,
            ),
            "timezone": FUSO_DA_FONTE,
        },
    }
    if sem_estatistica:
        documento.pop("stats")
    return documento


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", required=True, help="camada raw/ do lake")
    parser.add_argument("--out", required=True, help="arquivo .jsonl de saída")
    parser.add_argument(
        "--fonte", default="football_data", help="subdiretório da fonte a converter"
    )
    parser.add_argument(
        "--sem-estatistica",
        action="store_true",
        help=(
            "a fonte não traz colunas de chutes/faltas/cartões (é o caso dos "
            "arquivos sul-americanos). Declara só os blocos que existem, em "
            "vez de emitir estatística vazia que seria recusada"
        ),
    )
    args = parser.parse_args()

    padrao = f"{args.raw_dir}/**/{args.fonte}/fixture/*.jsonl"
    caminhos = sorted(glob.glob(padrao, recursive=True))
    if not caminhos:
        print(f"nenhum arquivo em {padrao}", file=sys.stderr)
        return 1

    saida = Path(args.out)
    escritos = 0
    por_temporada: Counter[str] = Counter()
    sem_clube: Counter[str] = Counter()

    with saida.open("w", encoding="utf-8") as destino:
        for caminho in caminhos:
            partes = caminho.replace("\\", "/").split("/")
            # …/raw/{competicao}/{temporada}/{fonte}/fixture/part-*.jsonl
            competicao, temporada = partes[-5], partes[-4]
            for linha in open(caminho, encoding="utf-8"):
                linha = linha.strip()
                if not linha:
                    continue
                registro = converter(
                    json.loads(linha),
                    competicao,
                    temporada,
                    sem_estatistica=args.sem_estatistica,
                )
                identidade = registro["identity"]
                for lado, coluna in (("home_club_id", "HomeTeam"), ("away_club_id", "AwayTeam")):
                    if not identidade[lado]:
                        bruto = json.loads(linha).get("raw") or {}
                        sem_clube[str(bruto.get(coluna) or "?")] += 1
                destino.write(json.dumps(registro, ensure_ascii=False) + "\n")
                escritos += 1
                por_temporada[f"{competicao}/{temporada}"] += 1

    print(f"convertidos {escritos} registros -> {saida}")
    for chave, quantos in sorted(por_temporada.items()):
        print(f"  {chave}: {quantos}")
    if sem_clube:
        # Reportado, não escondido: são as linhas que o Atlas vai recusar, e
        # saber disso antes de enviar é o ponto de existir um relatório.
        print(f"\nCLUBES NÃO RESOLVIDOS ({sum(sem_clube.values())} ocorrências):")
        for nome, quantos in sem_clube.most_common(20):
            print(f"  {quantos:>5}  {nome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
