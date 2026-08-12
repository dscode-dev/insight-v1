"""Mede cada lente POR COMPETICAO e publica o resultado.

    python -m scripts.atlas_lens_measure --database-url <url> [--gravar]

POR QUE ISTO E UM SCRIPT E NAO FOLCLORE. Os numeros de validacao viajam em
TODA resposta do Atlas: "esta lente concorda com o desfecho 9,7 pontos acima
da taxa base". Sao a unica coisa que separa uma descricao que descreve de uma
que tem a mesma forma e nao descreve. Enquanto foram escritos a mao em
`lenses.py`, o corpus cresceu 4x e eles continuaram afirmando 3.799 partidas,
com a mesma confianca e sobre uma base que nao existia mais.

POR QUE POR COMPETICAO. Medido sobre o corpus de hoje:

    lente             Europa    Brasileirao   Argentina
    resultado         +10,9%       -4,8%        +0,9%
    desempenho_time    +7,2%       -0,8%        -0,8%
    gols               +5,6%       -4,1%        -4,5%

Nao existe um numero certo por lente. "+10,9%" mente sobre o Brasileirao; a
media do corpus mente sobre a Premier League. A validade nunca foi propriedade
da lente: e propriedade da lente NAQUELE campeonato.

O QUE E MEDIDO. Para cada competicao, N partidas sorteadas depois de um
aquecimento. Para cada uma, os vizinhos saem SO DAS ANTERIORES da mesma
competicao, mesma regra da consulta real; senao a medida usaria o futuro e
daria um numero bonito e falso. Aplica os filtros duros da lente, pondera as
dimensoes pelos pesos dela, pega os 25 mais proximos e pergunta: a maioria
deles terminou como a partida-alvo terminou?

CONTRA A TAXA BASE DAQUELA COMPETICAO. Se 48% do Brasileirao termina em
vitoria do mandante, uma lente que acerta 48% ali nao aprendeu nada. E a taxa
base do corpus inteiro nao serve: a Premier League da 43,8%.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import text

from atlas.registry import build_engine, build_session_factory
from atlas.vector.lenses import LENTES
from atlas.vector.space import EspacoVetorial
from atlas.vector.validation import Medida
from atlas.vector.validation_repository import ValidationRepository

#: Partidas iniciais que nao viram alvo. As primeiras de cada clube tem
#: janelas vazias, e medir sobre elas mede o aquecimento, nao a lente.
#:
#: 500 e nao 3.000 porque a medida e POR COMPETICAO: 3.000 consumiria quase
#: todo o corpus de La Liga antes de sobrar alvo. 500 e mais de uma temporada
#: em qualquer um dos campeonatos que temos.
AQUECIMENTO = 500

#: Os mesmos 25 da consulta real. Medir com outro K mediria outra coisa.
VIZINHOS = 25


async def _carregar(database_url: str):
    engine = build_engine(database_url)
    fabrica = build_session_factory(engine)
    try:
        async with fabrica() as sessao:
            linha = (
                await sessao.execute(
                    text(
                        "SELECT dimensions, means, deviations, matches "
                        "FROM atlas.vector_space WHERE version = :v"
                    ),
                    {"v": "atlas.vector.v1"},
                )
            ).first()
            if linha is None:
                return None, []
            espaco = EspacoVetorial(
                versao="atlas.vector.v1",
                dimensoes=tuple(linha[0]),
                medias=tuple(float(x) for x in linha[1]),
                desvios=tuple(float(x) for x in linha[2]),
                partidas=int(linha[3]),
            )
            resultado = await sessao.execute(
                text(
                    "SELECT uid, competition, home_club_id, away_club_id, "
                    "       label, features "
                    "FROM atlas.match_vector ORDER BY kickoff_utc, uid"
                )
            )
            return espaco, [
                {
                    "uid": str(r[0]),
                    "competition": str(r[1]),
                    "home": str(r[2]),
                    "away": str(r[3]),
                    "label": str(r[4]),
                    "features": dict(r[5]),
                }
                for r in resultado.fetchall()
            ]
    finally:
        await engine.dispose()


def _cosseno(a: dict, b: dict, pesos: dict, espaco: EspacoVetorial) -> float:
    """A MESMA formula de `atlas.vector.query._cosseno_com_pesos`.

    Escrita aqui e nao importada de la: se a medicao usasse a funcao da
    consulta, uma mudanca na consulta mudaria em silencio o significado dos
    numeros ja gravados. Separadas, a divergencia aparece, e ha um teste
    comparando as duas sobre os mesmos vetores.
    """
    indices = {nome: i for i, nome in enumerate(espaco.dimensoes)}
    va: list[float] = []
    vb: list[float] = []
    for nome, peso in pesos.items():
        indice = indices.get(nome)
        if indice is None:
            continue
        media, desvio = espaco.medias[indice], espaco.desvios[indice]
        raiz = math.sqrt(peso)
        va.append(raiz * (a.get(nome, media) - media) / desvio)
        vb.append(raiz * (b.get(nome, media) - media) / desvio)
    na = math.sqrt(sum(v * v for v in va))
    nb = math.sqrt(sum(v * v for v in vb))
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    return sum(x * y for x, y in zip(va, vb)) / (na * nb)


def _medir(lente, partidas: list[dict], espaco, *, consultas: int, semente: int):
    disponiveis = list(range(AQUECIMENTO, len(partidas)))
    if len(disponiveis) < 50:
        return None

    rng = random.Random(semente)
    alvos = rng.sample(disponiveis, min(consultas, len(disponiveis)))

    # A taxa base DESTA competicao. A do corpus inteiro compararia a lente
    # contra o desfecho mais comum de um campeonato que nao e o consultado:
    # o Brasileirao da 48,4% de vitoria do mandante e a Premier League 43,8%.
    taxa_base = (
        Counter(p["label"] for p in partidas).most_common(1)[0][1] / len(partidas)
    )

    concordaram = 0
    avaliadas = 0
    sem_vizinhos = 0
    for indice in alvos:
        alvo = partidas[indice]
        candidatos = partidas[:indice]

        if "mesmo_par" in lente.filtros:
            par = {alvo["home"], alvo["away"]}
            candidatos = [c for c in candidatos if {c["home"], c["away"]} == par]

        if len(candidatos) < 5:
            sem_vizinhos += 1
            continue

        vizinhos = sorted(
            candidatos,
            key=lambda c: _cosseno(
                alvo["features"], c["features"], lente.pesos, espaco
            ),
            reverse=True,
        )[:VIZINHOS]

        maioria = Counter(v["label"] for v in vizinhos).most_common(1)[0][0]
        concordaram += 1 if maioria == alvo["label"] else 0
        avaliadas += 1

    if avaliadas < 30:
        return {
            "categoria": lente.categoria,
            "avaliadas": avaliadas,
            "sem_vizinhos": sem_vizinhos,
            "insuficiente": True,
        }

    concordancia = concordaram / avaliadas
    # Margem de 95% sobre a proporcao medida. Sem ela, +1,4% e +14% teriam a
    # mesma aparencia de resultado.
    margem = 1.96 * math.sqrt(concordancia * (1 - concordancia) / avaliadas)
    return {
        "categoria": lente.categoria,
        "avaliadas": avaliadas,
        "sem_vizinhos": sem_vizinhos,
        "concordancia": concordancia,
        "taxa_base": taxa_base,
        "ganho": concordancia - taxa_base,
        "margem": margem,
        "insuficiente": False,
    }


def _veredito(leitura: dict) -> str:
    if leitura["insuficiente"]:
        return "amostra insuficiente"
    if abs(leitura["ganho"]) <= leitura["margem"]:
        return "nao demonstrada"
    return "CONCLUSIVA" if leitura["ganho"] > 0 else "PIOR QUE A BASE"


async def _gravar(database_url: str, leituras: list[dict], corpus: int) -> int:
    """Publica as medidas, cada uma amarrada a competicao em que foi apurada.

    As insuficientes NAO sao gravadas. Uma linha de 12 consultas ficaria na
    tabela indistinguivel de uma de 900 para quem olha so o ganho, e a
    ausencia da linha ja diz a coisa certa: nao foi medida aqui.
    """
    engine = build_engine(database_url)
    try:
        repositorio = ValidationRepository(build_session_factory(engine))
        medidas = [
            Medida(
                lente=l["categoria"],
                competicao=l["competicao"],
                concordancia=l["concordancia"],
                taxa_base=l["taxa_base"],
                ganho=l["ganho"],
                margem=l["margem"],
                avaliadas=l["avaliadas"],
                corpus=corpus,
                medida_em=datetime.now(timezone.utc),
                versao_espaco="atlas.vector.v1",
            )
            for l in leituras
            if not l["insuficiente"]
        ]
        return await repositorio.gravar(medidas)
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--consultas", type=int, default=900)
    parser.add_argument("--semente", type=int, default=11)
    parser.add_argument(
        "--competicao",
        action="append",
        help="mede so estas. Sem isto, mede todas as que tem partidas.",
    )
    parser.add_argument(
        "--gravar",
        action="store_true",
        help=(
            "grava em atlas.lens_validation. Sem isto o comando so mede e "
            "imprime: medir e seguro, publicar o numero que toda resposta vai "
            "carregar e uma decisao"
        ),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    espaco, todas = asyncio.run(_carregar(args.database_url))
    if not todas:
        print("nenhum vetor - rode scripts.atlas_vector_build antes")
        return 1

    competicoes = sorted(
        set(args.competicao)
        if args.competicao
        else {p["competition"] for p in todas}
    )
    lentes = list(LENTES.values() if hasattr(LENTES, "values") else LENTES)

    leituras: list[dict] = []
    for competicao in competicoes:
        # UMA COMPETICAO DE CADA VEZ, alvos E vizinhos.
        #
        # Medir sobre o corpus inteiro e gravar o numero para cada competicao
        # seria a mesma afirmacao errada que esta mudanca desfaz: a vizinhanca
        # de uma partida do Brasileirao viria de La Liga, e a taxa base seria
        # a de um campeonato que nao e o dela.
        partidas = [p for p in todas if p["competition"] == competicao]
        for lente in lentes:
            leitura = _medir(
                lente,
                partidas,
                espaco,
                consultas=args.consultas,
                semente=args.semente,
            ) or {
                "categoria": lente.categoria,
                "avaliadas": 0,
                "sem_vizinhos": len(partidas),
                "insuficiente": True,
            }
            leitura["competicao"] = competicao
            leitura["partidas"] = len(partidas)
            leituras.append(leitura)

    if args.json:
        print(json.dumps({"lentes": leituras}, ensure_ascii=False, indent=2))
        return 0

    print("")
    print(f"LENTES POR COMPETICAO - {args.consultas} consultas cada")
    atual = None
    for l in leituras:
        if l["competicao"] != atual:
            atual = l["competicao"]
            print("")
            print(f"{atual}  ({l['partidas']} partidas)")
            print(
                f"  {'LENTE':<18} {'AVAL':>5} {'CONCORD':>9} {'BASE':>8} "
                f"{'GANHO':>8} {'MARGEM':>8}  VEREDITO"
            )
            print("  " + "-" * 76)
        if l["insuficiente"]:
            print(
                f"  {l['categoria']:<18} {l['avaliadas']:>5} {'-':>9} {'-':>8} "
                f"{'-':>8} {'-':>8}  {_veredito(l)}"
            )
            continue
        print(
            f"  {l['categoria']:<18} {l['avaliadas']:>5} "
            f"{l['concordancia']:>8.1%} {l['taxa_base']:>7.1%} "
            f"{l['ganho']:>+8.1%} {l['margem']:>7.1%}  {_veredito(l)}"
        )

    print("")
    if args.gravar:
        gravadas = asyncio.run(_gravar(args.database_url, leituras, len(todas)))
        print(f"  gravadas {gravadas} medidas em atlas.lens_validation")
        print("  a partir de agora elas viajam em toda resposta destas competicoes.")
    else:
        print("  nada gravado. Use --gravar para publicar em atlas.lens_validation.")
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
