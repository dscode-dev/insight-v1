"""Executa uma consulta: filtra, aplica a lente, descreve.

A ORDEM IMPORTA. Os filtros da lente vêm ANTES da similaridade, não depois.
`confronto` precisa das partidas daquele par específico; encontrá-las por
proximidade encontraria jogos parecidos de outros times — que é a pergunta
`resultado` com outro nome. Filtrar depois de ordenar daria os mesmos 25
vizinhos genéricos e então descartaria quase todos.

O CORTE TEMPORAL É DURO. Só entram partidas anteriores ao `as_of`. Não é
detalhe de implementação: as features são walk-forward, e deixar o futuro
entrar faria a descrição usar o que ainda não havia acontecido — do jeito
que ninguém notaria, porque a resposta continuaria bem formada.
"""

from __future__ import annotations

import statistics
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.vector.builder import carregar_espaco
from atlas.vector.lenses import lente
from atlas.vector.query import Consulta, Vizinho, _cosseno_com_pesos, descrever
from atlas.vector.validation_repository import ValidationRepository

#: Quantas partidas são lidas do banco antes de a lente ordenar. A lente usa
#: um subconjunto de dimensões, então o índice HNSW — construído sobre o vetor
#: inteiro — não é a ordem certa. Ler um recorte razoável e ordenar em memória
#: é honesto com 3.799 partidas; com 100 mil a resposta é um índice por lente,
#: não um limite maior.
CANDIDATOS = 4_000


class QueryService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory
        self._validacoes = ValidationRepository(session_factory)

    @property
    def validacoes(self) -> ValidationRepository:
        """Exposto para a rota de cobertura. Um repositório próprio ali
        abriria um segundo cache que envelheceria em desacordo com este."""
        return self._validacoes

    async def responder(self, consulta: Consulta) -> dict[str, Any]:
        """A resposta em JSON — o que a tela e o fluxo de produção leem."""
        vizinhos, espaco, escala = await self.vizinhos(consulta)
        if espaco is None:
            return _sem_memoria(consulta)
        # A medida desta lente NESTA competição. `None` quando nunca foi
        # medida ali, e a resposta diz isso — nunca cai para a medida de
        # outra competição, que é a afirmação errada que motivou a tabela.
        medida = await self._validacoes.para(consulta.categoria, consulta.competition)
        return descrever(consulta, vizinhos, espaco, escala, medida)

    async def vizinhos(self, consulta: Consulta):
        """Os vizinhos crus, ordenados, mais o espaço e a régua da lente.

        Existe separado de `responder` porque a ponte ao vivo precisa dos 25
        vizinhos para pontuar a vizinhança, e a resposta em JSON só carrega os
        8 primeiros como evidência. Servir a ponte a partir do JSON faria o
        detector pontuar um subconjunto e reportar o número do conjunto —
        exatamente o defeito que o próprio detector documenta ter tido.
        """
        lente_ = lente(consulta.categoria)
        espaco = await carregar_espaco(self._sf)
        if espaco is None:
            # Sem espaço não há como padronizar, e padronizar com média zero
            # sobre um corpus cuja média não é zero produz vetores plausíveis
            # num espaço errado. Dizer que não há memória é a única resposta.
            return [], None, 0.0

        condicoes = ["kickoff_utc < :as_of"]
        parametros: dict[str, Any] = {"as_of": consulta.as_of, "limite": CANDIDATOS}
        if "mesma_competicao" in lente_.filtros:
            condicoes.append("competition = :competition")
            parametros["competition"] = consulta.competition
        if "mesmo_par" in lente_.filtros:
            # Nos dois sentidos: o mando muda, o confronto não.
            condicoes.append(
                "((home_club_id = :casa AND away_club_id = :fora) "
                " OR (home_club_id = :fora AND away_club_id = :casa))"
            )
            parametros["casa"] = consulta.home_club_id
            parametros["fora"] = consulta.away_club_id

        async with self._sf() as session:
            resultado = await session.execute(
                text(
                    "SELECT uid, competition, season, kickoff_utc, home_club_id, "
                    "       away_club_id, label, features "
                    "FROM atlas.match_vector "
                    f"WHERE {' AND '.join(condicoes)} "
                    "ORDER BY kickoff_utc DESC LIMIT :limite"
                ),
                parametros,
            )
            linhas = resultado.fetchall()

        vizinhos = [
            Vizinho(
                uid=str(linha[0]),
                competition=str(linha[1]),
                season=str(linha[2]),
                kickoff=linha[3],
                home=str(linha[4]),
                away=str(linha[5]),
                label=str(linha[6]),
                features=dict(linha[7]),
                similaridade=_cosseno_com_pesos(
                    consulta.features, dict(linha[7]), lente_, espaco
                ),
            )
            for linha in linhas
        ]
        vizinhos.sort(key=lambda v: v.similaridade, reverse=True)
        return vizinhos, espaco, _mediana_aleatoria(vizinhos, lente_, espaco)


def _sem_memoria(consulta: Consulta) -> dict[str, Any]:
    lente_ = lente(consulta.categoria)
    return {
        "schema_version": "atlas.query.v1",
        "categoria": lente_.categoria,
        "descricao": None,
        "incerteza": {
            "score": 1.0,
            "motivo": "memória vetorial não construída",
            "dimensoes_ausentes": list(lente_.pesos),
        },
    }


def _mediana_aleatoria(vizinhos, lente_, espaco) -> float:
    """A régua desta lente: quanto se parecem duas partidas quaisquer.

    Calculada sobre os próprios candidatos e nesta lente — a mediana do
    espaço inteiro não serve, porque cada lente usa um subconjunto de
    dimensões e portanto tem a sua própria escala.
    """
    import random

    if len(vizinhos) < 20:
        return 0.0
    rng = random.Random(7)
    amostra = rng.sample(vizinhos, min(200, len(vizinhos)))
    pares = []
    for _ in range(2000):
        a, b = rng.randrange(len(amostra)), rng.randrange(len(amostra))
        if a == b:
            continue
        pares.append(
            _cosseno_com_pesos(amostra[a].features, amostra[b].features, lente_, espaco)
        )
    return statistics.median(pares) if pares else 0.0
