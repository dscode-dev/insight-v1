"""Lê e grava `atlas.lens_validation`.

Em cache na memória porque toda consulta precisa da medida e ela muda uma vez
por reconstrução do vetor — mas com a versão do espaço junto, para que uma
reconstrução invalide o cache em vez de servir números de um espaço que não
existe mais.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.vector.validation import Medida

_GRAVAR = text(
    """
    INSERT INTO atlas.lens_validation (
        lens, competition, agreement, base_rate, lift, margin,
        evaluated, corpus, space_version, measured_at
    ) VALUES (
        :lens, :competition, :agreement, :base_rate, :lift, :margin,
        :evaluated, :corpus, :space_version, now()
    )
    ON CONFLICT (lens, competition) DO UPDATE SET
        agreement     = EXCLUDED.agreement,
        base_rate     = EXCLUDED.base_rate,
        lift          = EXCLUDED.lift,
        margin        = EXCLUDED.margin,
        evaluated     = EXCLUDED.evaluated,
        corpus        = EXCLUDED.corpus,
        space_version = EXCLUDED.space_version,
        measured_at   = now()
    """
)


class ValidationRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory
        self._cache: dict[tuple[str, str], Medida] | None = None

    async def carregar(self) -> dict[tuple[str, str], Medida]:
        if self._cache is not None:
            return self._cache
        async with self._sf() as sessao:
            linhas = await sessao.execute(
                text(
                    "SELECT lens, competition, agreement, base_rate, lift, "
                    "       margin, evaluated, corpus, measured_at, space_version "
                    "FROM atlas.lens_validation"
                )
            )
            self._cache = {
                (str(l[0]), str(l[1])): Medida(
                    lente=str(l[0]),
                    competicao=str(l[1]),
                    concordancia=float(l[2]),
                    taxa_base=float(l[3]),
                    ganho=float(l[4]),
                    margem=float(l[5]),
                    avaliadas=int(l[6]),
                    corpus=int(l[7]),
                    medida_em=l[8],
                    versao_espaco=str(l[9]),
                )
                for l in linhas.fetchall()
            }
        return self._cache

    async def para(self, lente: str, competicao: str) -> Medida | None:
        """A medida desta lente NESTA competição, ou None.

        Sem fallback para outra competição, deliberadamente: a medida de La
        Liga não diz nada sobre o Brasileirão, e servi-la ali seria a mesma
        afirmação errada que motivou a tabela.
        """
        return (await self.carregar()).get((lente, competicao))

    async def gravar(self, medidas: Iterable[Medida]) -> int:
        gravadas = 0
        async with self._sf() as sessao:
            for m in medidas:
                await sessao.execute(
                    _GRAVAR,
                    {
                        "lens": m.lente,
                        "competition": m.competicao,
                        "agreement": m.concordancia,
                        "base_rate": m.taxa_base,
                        "lift": m.ganho,
                        "margin": m.margem,
                        "evaluated": m.avaliadas,
                        "corpus": m.corpus,
                        "space_version": m.versao_espaco,
                    },
                )
                gravadas += 1
            await sessao.commit()
        self._cache = None
        return gravadas

    async def cobertura(self) -> list[dict]:
        """Que lentes estão medidas em que competições — e quais faltam.

        A pergunta que o console faz para mostrar onde o Atlas pode afirmar
        alguma coisa e onde ele só tem vizinhos.
        """
        async with self._sf() as sessao:
            linhas = await sessao.execute(
                text(
                    """
                    -- AGREGA CADA LADO ANTES DE JUNTAR.
                    --
                    -- Juntar `match_record` com `lens_validation` e contar
                    -- multiplica as partidas pelo número de lentes medidas:
                    -- o Brasileirão apareceu com 27.670 partidas, que é
                    -- 5.534 × 5. O número ficou plausível o bastante para
                    -- passar, e é o tipo de erro que só a conferência pega.
                    WITH partidas AS (
                        SELECT competition, count(*) AS total
                        FROM atlas.match_record
                        GROUP BY competition
                    ),
                    medidas AS (
                        SELECT competition,
                               count(*) AS lentes,
                               count(*) FILTER (
                                   WHERE lift > margin
                               ) AS conclusivas_a_favor,
                               count(*) FILTER (
                                   WHERE -lift > margin
                               ) AS piores_que_a_base
                        FROM atlas.lens_validation
                        GROUP BY competition
                    )
                    SELECT p.competition,
                           p.total,
                           coalesce(m.lentes, 0),
                           coalesce(m.conclusivas_a_favor, 0),
                           coalesce(m.piores_que_a_base, 0)
                    FROM partidas p
                    LEFT JOIN medidas m ON m.competition = p.competition
                    ORDER BY p.total DESC
                    """
                )
            )
            return [
                {
                    "competition": str(l[0]),
                    "matches": int(l[1]),
                    "lenses_measured": int(l[2]),
                    "lenses_conclusive": int(l[3]),
                    "lenses_worse_than_base": int(l[4]),
                    # As não medidas são explícitas: cinco lentes existem
                    # sempre, e "medidas 4" sem dizer que falta uma seria lido
                    # como se as cinco estivessem cobertas.
                    "lenses_unmeasured": 5 - int(l[2]),
                }
                for l in linhas.fetchall()
            ]
