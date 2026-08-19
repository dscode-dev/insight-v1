"""A leitura do corpus publicado para reconstruir estado — SQL escrito à mão.

O QUE É PARTICULAR DESTE ARQUIVO:

A LEITURA PARTE DA PERTINÊNCIA, e não do registro canônico. `matches`,
`canonical_match_events` e `canonical_odds_observations` são GLOBAIS: eles
contêm tudo que qualquer build já escreveu. O que a versão publica está em
`historical_canonical_members` e `historical_canonical_event_members` — e é o
cruzamento com elas que separa «o corpus 1.0» de «o banco inteiro».

CINCO CONSULTAS POR LOTE, E NUNCA POR PARTIDA (§79, §81):

    membros + partidas + contexto     uma
    escalações                        uma
    eventos                           uma
    cotações                          uma
    resultados                        uma

Com N+1 seriam cinco por partida — vinte e cinco mil consultas para cinco mil
partidas, e o benchmark do §158 existe justamente para que isso não passe.

A FAMÍLIA PUBLICADA VEM DO MEMBRO. `included_families` diz o que aquela
partida contribui NAQUELA versão, e é isso que distingue «zero cartões» de
«sem eventos publicados» (§40) — a tabela de eventos poderia ter linhas que a
versão não publica.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Final, final

from sports_intelligence.adapters.postgres.corpus import (
    lineups_of,
    match_from_row,
    odds_of,
)
from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.features.state.builder import CanonicalMatchStateInput
from sports_intelligence.domain.matches.result import MatchResult, Score
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.identity import MatchId

#: Os desfechos de linhagem de evento que significam «este evento existe».
#: `SKIPPED` e companhia não produziram evento — procurá-los faria a leitura
#: pedir linhas que não existem.
_EVENTOS_PUBLICADOS: Final[tuple[str, ...]] = ("BUILT", "REUSED")


@final
class PostgresHistoricalMatchStateSource:
    """Os insumos de estado de um lote de partidas, de UMA versão publicada."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def match_ids(
        self, version_id: str, *, limit: int = 500, after: str | None = None
    ) -> Sequence[MatchId]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT match_id
                FROM historical_canonical_members
                WHERE version_id = $1
                  AND ($2::uuid IS NULL OR match_id > $2::uuid)
                ORDER BY match_id
                LIMIT $3
                """,
                uuid.UUID(version_id),
                None if after is None else uuid.UUID(after),
                limit,
            )
        return [MatchId(linha["match_id"]) for linha in linhas]

    async def load(
        self, version_id: str, match_ids: Sequence[MatchId]
    ) -> Mapping[MatchId, CanonicalMatchStateInput]:
        if not match_ids:
            return {}
        versao = uuid.UUID(version_id)
        ids = [m.value for m in match_ids]

        async with self._db.acquire() as conexao:
            membros = await conexao.fetch(
                """
                SELECT m.match_id, m.included_families, m.competition_code,
                       m.season_label,
                       p.competition_id, p.season_id, p.home_team_id, p.away_team_id,
                       p.scheduled_kickoff, p.actual_kickoff, p.lifecycle,
                       p.neutral_venue, p.venue_name, p.stage_type, p.round_number,
                       p.group_label, p.regime_code, p.regime_from,
                       p.regulation_version, s.regime_to
                FROM historical_canonical_members m
                JOIN matches p ON p.id = m.match_id
                JOIN seasons s ON s.id = p.season_id
                WHERE m.version_id = $1 AND m.match_id = ANY($2::uuid[])
                ORDER BY m.match_id
                """,
                versao,
                ids,
            )
            if not membros:
                return {}
            presentes = [linha["match_id"] for linha in membros]
            escalacoes = await lineups_of(conexao, presentes)
            eventos = await self._eventos(conexao, versao, presentes)
            cotacoes = await odds_of(conexao, presentes)
            resultados = await self._resultados(conexao, presentes)

        insumos: dict[MatchId, CanonicalMatchStateInput] = {}
        for linha in membros:
            partida = MatchId(linha["match_id"])
            insumos[partida] = CanonicalMatchStateInput(
                # A PARTIDA VEM DO MESMO MAPEADOR do corpus: dois construtores
                # da mesma linha divergiriam no primeiro campo novo.
                match=match_from_row(linha),
                competition_code=linha["competition_code"],
                season_label=linha["season_label"],
                published_families=frozenset(
                    CoverageFamily(f) for f in linha["included_families"]
                ),
                candidate_events=eventos.get(linha["match_id"], ()),
                lineups=escalacoes.get(linha["match_id"], ()),
                odds=cotacoes.get(linha["match_id"], ()),
                result=resultados.get(linha["match_id"]),
            )
        return insumos

    # ------------------------------------------------------- consultas --

    @staticmethod
    async def _eventos(
        conexao: Any, version_id: uuid.UUID, match_ids: Sequence[Any]
    ) -> dict[Any, tuple[Any, ...]]:
        """Os eventos que AQUELA VERSÃO publica — não os do registro global.

        A JUNÇÃO COM A PERTINÊNCIA É O PONTO. `canonical_match_events` tem os
        eventos de todos os builds; a versão publica um recorte, e ler o
        registro direto traria eventos que aquele corpus nunca publicou.
        """
        from sports_intelligence.adapters.postgres.events import _para_evento

        linhas = await conexao.fetch(
            f"""
            SELECT {_COLUNAS_DE_EVENTO}
            FROM historical_canonical_event_members m
            JOIN canonical_match_events e ON e.id = m.event_id
            WHERE m.version_id = $1 AND m.match_id = ANY($2::uuid[])
            ORDER BY e.match_id, e.period, e.minute, e.stoppage, e.sequence, e.id
            """,
            version_id,
            list(match_ids),
        )
        por_partida: dict[Any, list[Any]] = {}
        for linha in linhas:
            por_partida.setdefault(linha["match_id"], []).append(_para_evento(linha))
        return {partida: tuple(v) for partida, v in por_partida.items()}

    @staticmethod
    async def _resultados(
        conexao: Any, match_ids: Sequence[Any]
    ) -> dict[Any, MatchResult]:
        """Os resultados finais — para a CONFERÊNCIA pós-jogo, e só (§100).

        ELES SÃO LIDOS SEMPRE E USADOS QUASE NUNCA. O construtor só os consulta
        num corte pós-jogo; lê-los de qualquer forma custa uma consulta por
        lote e evita uma segunda ida ao banco quando o corte é o do apito
        final.
        """
        linhas = await conexao.fetch(
            """
            SELECT match_id, regular_home, regular_away, extra_home, extra_away,
                   penalties_home, penalties_away
            FROM match_results
            WHERE match_id = ANY($1::uuid[])
            """,
            list(match_ids),
        )
        resultados: dict[Any, MatchResult] = {}
        for linha in linhas:
            normal = _para_placar(linha["regular_home"], linha["regular_away"])
            if normal is None:
                # SEM TEMPO NORMAL NÃO HÁ RESULTADO. O contrato canônico exige
                # o placar do tempo regulamentar; uma linha sem ele descreve
                # uma partida cujo resultado não foi publicado.
                continue
            resultados[linha["match_id"]] = MatchResult(
                regular_time=normal,
                extra_time=_para_placar(linha["extra_home"], linha["extra_away"]),
                penalties=_para_placar(
                    linha["penalties_home"], linha["penalties_away"]
                ),
            )
        return resultados


_COLUNAS_DE_EVENTO: Final[str] = (
    "e.id, e.match_id, e.event_type, e.period, e.minute, e.stoppage, "
    "e.sequence, e.team_id, e.player_id, e.start_x, e.start_y, e.end_x, "
    "e.end_y, e.coordinate_frame, e.detail, e.revision, e.supersedes_event_id, "
    "e.status, e.provider_id, e.source_event_key, e.record_ref, "
    "e.license_class, e.raw_event_type"
)


def _para_placar(home: int | None, away: int | None) -> Score | None:
    if home is None or away is None:
        return None
    return Score(home=home, away=away)
