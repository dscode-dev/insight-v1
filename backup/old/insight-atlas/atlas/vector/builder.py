"""Reconstrói a memória vetorial a partir de `atlas.match_record`.

    partidas em ordem  →  features walk-forward  →  ajusta o espaço
                       →  padroniza  →  grava vetor + espaço

RECONSTRÓI TUDO, SEMPRE, E ISSO NÃO É PREGUIÇA. As features são walk-forward:
o Elo, a forma e o confronto direto de uma partida dependem de todas as
anteriores. Uma partida inserida no meio da linha do tempo muda tudo que vem
depois dela, então a reconstrução parcial correta é a reconstrução inteira.
Com 3.799 partidas isso leva segundos; se deixar de levar, a resposta é
particionar por competição, não atualizar no lugar.

O ESPAÇO É REAJUSTADO JUNTO. Média e desvio saem do corpus, então mudar o
corpus muda o espaço — e vetores gravados sob médias diferentes não são
comparáveis entre si. Gravar os dois na mesma passagem é o que impede a
combinação impossível de vetor novo com espaço velho.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.vector.features import Linha, construir
from atlas.vector.space import VERSAO, EspacoVetorial, ajustar


@dataclass
class ResultadoConstrucao:
    partidas: int = 0
    dimensoes: int = 0
    versao: str = VERSAO
    #: Dimensões que não variam no corpus. Reportadas, não escondidas: cada
    #: uma é uma coluna paga e vazia, e a régua do passo 0 as encontraria de
    #: qualquer forma — melhor que o próprio construtor as denuncie.
    constantes: list[str] = field(default_factory=list)
    por_bloco: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "versao": self.versao,
            "partidas": self.partidas,
            "dimensoes": self.dimensoes,
            "constantes": self.constantes,
            "por_bloco": self.por_bloco,
        }


class VectorBuilder:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def _documentos(self) -> list[dict]:
        async with self._sf() as session:
            resultado = await session.execute(
                text(
                    "SELECT uid, document FROM atlas.match_record "
                    "ORDER BY kickoff_utc, uid"
                )
            )
            documentos = []
            for uid, documento in resultado.fetchall():
                # O uid vem da COLUNA, não do documento: é a chave que o
                # contrato derivou na ingestão, e recalculá-la aqui abriria
                # a possibilidade de as duas discordarem.
                documentos.append({**documento, "__uid__": str(uid)})
            return documentos

    async def construir(self) -> ResultadoConstrucao:
        documentos = await self._documentos()
        if not documentos:
            return ResultadoConstrucao(partidas=0)

        linhas: list[Linha] = list(construir(documentos))
        espaco = ajustar([linha.features for linha in linhas])

        await self._gravar(linhas, espaco)

        from atlas.vector.features import FEATURES

        constantes = [
            nome
            for indice, nome in enumerate(espaco.dimensoes)
            if espaco.desvios[indice] == 1.0
            and all(linha.features.get(nome) == linhas[0].features.get(nome) for linha in linhas[:50])
        ]
        por_bloco: dict[str, int] = {}
        for feature in FEATURES:
            por_bloco[feature.bloco] = por_bloco.get(feature.bloco, 0) + 1

        return ResultadoConstrucao(
            partidas=len(linhas),
            dimensoes=espaco.tamanho,
            constantes=constantes,
            por_bloco=por_bloco,
        )

    async def _gravar(self, linhas: Sequence[Linha], espaco: EspacoVetorial) -> None:
        async with self._sf() as session:
            # TRUNCATE e não upsert: o corpus foi recalculado inteiro, e uma
            # linha que sobrasse de uma construção anterior traria um vetor
            # feito com outra média e outro desvio. Foi o upsert-só-adiciona
            # que deixou 134 órfãos na tabela antiga.
            await session.execute(text("TRUNCATE atlas.match_vector"))

            for linha in linhas:
                await session.execute(
                    text(
                        "INSERT INTO atlas.match_vector "
                        "(uid, version, competition, season, kickoff_utc, "
                        " home_club_id, away_club_id, label, embedding, features) "
                        "VALUES (:uid, :version, :competition, :season, :kickoff, "
                        " :home, :away, :label, :embedding, CAST(:features AS JSONB))"
                    ),
                    {
                        "uid": linha.uid,
                        "version": espaco.versao,
                        "competition": linha.competition,
                        "season": linha.season,
                        "kickoff": linha.kickoff,
                        "home": linha.home,
                        "away": linha.away,
                        "label": linha.label,
                        "embedding": _pgvector(espaco.transformar(linha.features)),
                        "features": json.dumps(
                            {k: round(v, 6) for k, v in linha.features.items()}
                        ),
                    },
                )

            await session.execute(
                text(
                    "INSERT INTO atlas.vector_space "
                    "(version, dimensions, means, deviations, matches, built_at) "
                    "VALUES (:version, CAST(:dims AS JSONB), CAST(:means AS JSONB), "
                    "        CAST(:devs AS JSONB), :matches, now()) "
                    "ON CONFLICT (version) DO UPDATE SET "
                    "  dimensions = EXCLUDED.dimensions, means = EXCLUDED.means, "
                    "  deviations = EXCLUDED.deviations, matches = EXCLUDED.matches, "
                    "  built_at = now()"
                ),
                {
                    "version": espaco.versao,
                    "dims": json.dumps(list(espaco.dimensoes)),
                    "means": json.dumps([round(v, 8) for v in espaco.medias]),
                    "devs": json.dumps([round(v, 8) for v in espaco.desvios]),
                    "matches": espaco.partidas,
                },
            )
            await session.commit()


async def carregar_espaco(
    session_factory: async_sessionmaker[AsyncSession], versao: str = VERSAO
) -> EspacoVetorial | None:
    """O espaço gravado, para padronizar uma consulta ao vivo do mesmo jeito.

    Devolve None quando não há espaço construído — e quem chama precisa
    tratar isso como "não há memória vetorial", nunca como "use a identidade".
    Padronizar com média zero e desvio um sobre um corpus cuja média não é
    zero produz vetores plausíveis num espaço errado.
    """
    async with session_factory() as session:
        resultado = await session.execute(
            text(
                "SELECT version, dimensions, means, deviations, matches "
                "FROM atlas.vector_space WHERE version = :v"
            ),
            {"v": versao},
        )
        linha = resultado.first()
        if linha is None:
            return None
        return EspacoVetorial(
            versao=str(linha[0]),
            dimensoes=tuple(linha[1]),
            medias=tuple(float(v) for v in linha[2]),
            desvios=tuple(float(v) for v in linha[3]),
            partidas=int(linha[4]),
        )


def _pgvector(valores: Sequence[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in valores) + "]"
