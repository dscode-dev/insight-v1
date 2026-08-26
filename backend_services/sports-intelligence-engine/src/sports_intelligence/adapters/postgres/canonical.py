"""O PRIMEIRO WRITE REAL no registro canônico, e a linhagem que ele deixa.

A DÍVIDA DO PR-03 FECHA AQUI (§25). `PostgresCanonicalRegistry`, em
`resolution.py`, continua sendo o LEITOR — e continua sem um único `INSERT`,
de propósito: ele serve a `CanonicalRegistryPort`, que é o carregamento de
contexto da resolução, e dar a ele um método de escrita daria à resolução a
capacidade de criar entidade canônica sem passar pela qualidade. Era
exatamente a porta que o PR-03 se recusou a abrir.

Então o caminho de escrita nasce ao lado, sobre as MESMAS tabelas da migration
0003: `PostgresCanonicalRegistryWriter`. A separação é de responsabilidade e
não de dado — não há `canonical_matches_v2` (§60).

NENHUM `UPDATE` SOBRE FATO CANÔNICO. `last write wins` sobre uma partida
histórica reescreve o passado em silêncio (§62), e por isso a escrita tem três
desfechos em vez de um: insere o que falta, reaproveita o que é idêntico, e
RECUSA o que discorda — devolvendo `CONFLICT` para que a linhagem grave a
recusa e alguém decida.

DUAS CONSULTAS POR FAMÍLIA, e não duas por partida. `INSERT ... RETURNING`
diz o que entrou; um `SELECT` sobre o resto diz o que já existia e se é
equivalente. Dez mil partidas continuam custando o mesmo número de idas ao
banco que dez (§68).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Final, final

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.build.decisions import (
    BuildDecision,
    CanonicalFactType,
    FamilyDecision,
    FamilyExclusionReason,
    FamilyOutcome,
)
from sports_intelligence.domain.build.facts import MatchIdentityFacts
from sports_intelligence.domain.build.policy import CanonicalBuildPolicy
from sports_intelligence.domain.build.runs import (
    BuildCounts,
    BuildRecordStatus,
    CanonicalBuildRecord,
    CanonicalBuildRun,
    MatchWriteOutcome,
)
from sports_intelligence.domain.competitions.models import (
    CompetitionRegime,
    RegimeCode,
    Stage,
    StageType,
)
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.matches.lineup import Lineup
from sports_intelligence.domain.matches.models import Match, Venue
from sports_intelligence.domain.matches.result import MatchResult
from sports_intelligence.domain.odds.models import CanonicalOddsObservation
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.resolution.runs import RunStatus
from sports_intelligence.domain.resolution.versions import PolicyVersion
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.identity import (
    CompetitionId,
    MatchId,
    SeasonId,
    TeamId,
)
from sports_intelligence.domain.shared.provenance import LicenseClass
from sports_intelligence.domain.shared.temporal import instant

#: Quantos fatos vão ao banco por rodada. Mesmo raciocínio do PR-03.1: troca
#: idas ao banco por tamanho de array, e um `unnest` de um milhão de elementos
#: trocaria o N+1 por um pico de memória.
_FATOS_POR_RODADA: Final[int] = 500


@final
class PostgresCanonicalIdentityReader:
    """A identidade canônica JÁ RESOLVIDA de um lote de partidas.

    UMA CONSULTA PARA N PARTIDAS. Ela junta `matches` com `seasons` porque o
    regime é da temporada (PR-01) e o construtor precisa dos dois — buscá-los
    separado dobraria as idas ao banco por lote sem ganhar nada.

    AS AUSENTES NÃO VOLTAM. Uma partida sem linha em `matches` não tem
    identidade canônica, e o build a recusa em vez de inventá-la (§27).
    """

    def __init__(self, database: Database) -> None:
        self._db = database

    async def identity_facts(
        self, match_ids: Sequence[MatchId]
    ) -> Mapping[MatchId, MatchIdentityFacts]:
        if not match_ids:
            return {}
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT m.id, m.competition_id, m.season_id, m.home_team_id,
                       m.away_team_id, m.scheduled_kickoff, m.actual_kickoff,
                       m.stage_type, m.round_number, m.group_label,
                       m.regime_code, m.regime_from, m.regulation_version,
                       m.neutral_venue, m.venue_name, s.regime_to
                FROM matches m
                JOIN seasons s ON s.id = m.season_id
                WHERE m.id = ANY($1::uuid[])
                """,
                [m.value for m in match_ids],
            )
        return {MatchId(linha["id"]): _para_identidade(linha) for linha in linhas}


@final
class PostgresCanonicalRegistryWriter:
    """A escrita real no registro canônico. Equivalência antes de reuso."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def upsert_equivalent_matches(
        self, matches: Sequence[Match]
    ) -> Mapping[MatchId, MatchWriteOutcome]:
        """Insere, reaproveita ou recusa — nunca sobrescreve (§61, §62, §63).

        A EQUIVALÊNCIA É ESTRUTURAL: competição, temporada, times, horário
        marcado e fase. `lifecycle`, `venue` e `actual_kickoff` mudam
        legitimamente entre execuções e ficam de fora — exigi-los faria toda
        reingestão legítima virar conflito, e um conflito que sempre acontece
        é um conflito que ninguém lê.
        """
        if not matches:
            return {}
        desfechos: dict[MatchId, MatchWriteOutcome] = {}
        async with self._db.acquire() as conexao, conexao.transaction():
            for inicio in range(0, len(matches), _FATOS_POR_RODADA):
                bloco = matches[inicio : inicio + _FATOS_POR_RODADA]
                # QUAIS JÁ EXISTIAM, ANTES DE ESCREVER. É o que distingue
                # `INSERTED` de `REUSED_EQUIVALENT` sem depender de heurística:
                # o `executemany` não devolve `RETURNING`, e adivinhar pelo
                # estado gravado erraria justamente quando a partida
                # pré-existente tivesse o mesmo estado.
                ja_existiam = {
                    linha["id"]
                    for linha in await conexao.fetch(
                        "SELECT id FROM matches WHERE id = ANY($1::uuid[])",
                        [m.id.value for m in bloco],
                    )
                }
                await conexao.executemany(
                    """
                    INSERT INTO matches (
                        id, competition_id, season_id, home_team_id, away_team_id,
                        scheduled_kickoff, actual_kickoff, stage_type, round_number,
                        group_label, regime_code, regime_from, regulation_version,
                        lifecycle, neutral_venue, venue_name
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                            $13, $14, $15, $16)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    [
                        (
                            m.id.value,
                            m.competition_id.value,
                            m.season_id.value,
                            m.home_team_id.value,
                            m.away_team_id.value,
                            m.scheduled_kickoff,
                            m.actual_kickoff,
                            m.stage.type.value,
                            m.stage.round_number,
                            m.stage.group_label,
                            m.regime.code.value,
                            m.regime.effective_from,
                            m.regime.regulation_version,
                            m.lifecycle.value,
                            m.neutral_venue,
                            m.venue.name if m.venue else None,
                        )
                        for m in bloco
                    ],
                )
                existentes = await conexao.fetch(
                    """
                    SELECT id, competition_id, season_id, home_team_id, away_team_id,
                           scheduled_kickoff, stage_type, round_number, group_label
                    FROM matches WHERE id = ANY($1::uuid[])
                    """,
                    [m.id.value for m in bloco],
                )
                gravadas = {linha["id"]: linha for linha in existentes}
                for partida in bloco:
                    linha = gravadas.get(partida.id.value)
                    if linha is None:
                        # A LINHA NÃO EXISTE DEPOIS DO `INSERT`: só acontece se
                        # outra transação a apagou no meio. É conflito, e não
                        # sucesso silencioso.
                        desfechos[partida.id] = MatchWriteOutcome.CONFLICT
                    elif partida.id.value not in ja_existiam:
                        desfechos[partida.id] = MatchWriteOutcome.INSERTED
                    elif _partida_equivalente(partida, linha):
                        desfechos[partida.id] = MatchWriteOutcome.REUSED_EQUIVALENT
                    else:
                        # JÁ EXISTE E DISCORDA. Nada foi escrito — o `ON
                        # CONFLICT DO NOTHING` garantiu — e a linhagem grava a
                        # recusa em vez de o `UPDATE` reescrever o passado (§62).
                        desfechos[partida.id] = MatchWriteOutcome.CONFLICT
        return desfechos

    async def persist_results(
        self, results: Sequence[tuple[MatchId, MatchResult]]
    ) -> Mapping[MatchId, MatchWriteOutcome]:
        """Grava resultados. Mesma disciplina: equivalência, nunca `UPDATE`."""
        if not results:
            return {}
        desfechos: dict[MatchId, MatchWriteOutcome] = {}
        async with self._db.acquire() as conexao, conexao.transaction():
            for inicio in range(0, len(results), _FATOS_POR_RODADA):
                bloco = results[inicio : inicio + _FATOS_POR_RODADA]
                inseridos = await conexao.fetch(
                    """
                    INSERT INTO match_results (
                        match_id, regular_home, regular_away, extra_home, extra_away,
                        penalties_home, penalties_away
                    )
                    SELECT * FROM unnest(
                        $1::uuid[], $2::integer[], $3::integer[], $4::integer[],
                        $5::integer[], $6::integer[], $7::integer[]
                    )
                    ON CONFLICT (match_id) DO NOTHING
                    RETURNING match_id
                    """,
                    [m.value for m, _ in bloco],
                    [r.regular_time.home for _, r in bloco],
                    [r.regular_time.away for _, r in bloco],
                    [r.extra_time.home if r.extra_time else None for _, r in bloco],
                    [r.extra_time.away if r.extra_time else None for _, r in bloco],
                    [r.penalties.home if r.penalties else None for _, r in bloco],
                    [r.penalties.away if r.penalties else None for _, r in bloco],
                )
                novos = {linha["match_id"] for linha in inseridos}
                pendentes = [m for m, _ in bloco if m.value not in novos]
                existentes = (
                    {
                        linha["match_id"]: linha
                        for linha in await conexao.fetch(
                            "SELECT * FROM match_results WHERE match_id = ANY($1::uuid[])",
                            [m.value for m in pendentes],
                        )
                    }
                    if pendentes
                    else {}
                )
                for match_id, resultado in bloco:
                    if match_id.value in novos:
                        desfechos[match_id] = MatchWriteOutcome.INSERTED
                        continue
                    linha = existentes.get(match_id.value)
                    desfechos[match_id] = (
                        MatchWriteOutcome.REUSED_EQUIVALENT
                        if linha is not None and _resultado_equivalente(resultado, linha)
                        else MatchWriteOutcome.CONFLICT
                    )
        return desfechos

    async def persist_lineups(
        self, lineups: Sequence[Lineup]
    ) -> Mapping[MatchId, MatchWriteOutcome]:
        """Grava escalações iniciais e as entradas delas.

        O `player_id` TEM CHAVE ESTRANGEIRA PARA `players`, e é a guarda final
        do §36: um `PlayerId` inventado não tem para onde apontar, e o `INSERT`
        falha em vez de contaminar o histórico.
        """
        if not lineups:
            return {}
        desfechos: dict[MatchId, MatchWriteOutcome] = {}
        async with self._db.acquire() as conexao, conexao.transaction():
            inseridas = await conexao.fetch(
                """
                INSERT INTO lineups (match_id, team_id, formation)
                SELECT * FROM unnest($1::uuid[], $2::uuid[], $3::text[])
                ON CONFLICT (match_id, team_id) DO NOTHING
                RETURNING match_id, team_id
                """,
                [line.match_id.value for line in lineups],
                [line.team_id.value for line in lineups],
                [str(line.formation) if line.formation else None for line in lineups],
            )
            novas = {(linha["match_id"], linha["team_id"]) for linha in inseridas}
            entradas = [
                (line, entrada)
                for line in lineups
                if (line.match_id.value, line.team_id.value) in novas
                for entrada in line.entries
            ]
            if entradas:
                await conexao.execute(
                    """
                    INSERT INTO lineup_entries (
                        match_id, team_id, player_id, status, shirt_number,
                        position, captain
                    )
                    SELECT * FROM unnest(
                        $1::uuid[], $2::uuid[], $3::uuid[], $4::text[],
                        $5::integer[], $6::text[], $7::boolean[]
                    )
                    ON CONFLICT (match_id, team_id, player_id) DO NOTHING
                    """,
                    [line.match_id.value for line, _ in entradas],
                    [line.team_id.value for line, _ in entradas],
                    [e.player_id.value for _, e in entradas],
                    [e.status.value for _, e in entradas],
                    [e.shirt_number for _, e in entradas],
                    [e.position.value if e.position else None for _, e in entradas],
                    [e.captain for _, e in entradas],
                )
            for escalacao in lineups:
                chave = (escalacao.match_id.value, escalacao.team_id.value)
                desfechos[escalacao.match_id] = _pior_desfecho(
                    desfechos.get(escalacao.match_id),
                    MatchWriteOutcome.INSERTED
                    if chave in novas
                    else MatchWriteOutcome.REUSED_EQUIVALENT,
                )
        return desfechos

    async def persist_odds(
        self, observations: Sequence[CanonicalOddsObservation]
    ) -> Mapping[MatchId, MatchWriteOutcome]:
        """Grava o CONJUNTO de observações. Duas casas viram duas linhas (§42).

        A CHAVE É A IDENTIDADE DA V1 — (partida, casa, mercado, seleção,
        linha) —, exatamente a que o PR-03.2 entregou (§43). O `observed_at`
        NÃO entra nela, e por isso reler o mesmo arquivo produz a mesma
        observação em vez de uma segunda (§96).

        `observed_at` VAI COMO `NULL` quando a fonte não o declara. Nunca o
        kickoff, nunca `now()`: os dois seriam um fato inventado com aparência
        de fato (§44).
        """
        if not observations:
            return {}
        desfechos: dict[MatchId, MatchWriteOutcome] = {}
        async with self._db.acquire() as conexao, conexao.transaction():
            for inicio in range(0, len(observations), _FATOS_POR_RODADA):
                bloco = observations[inicio : inicio + _FATOS_POR_RODADA]
                await conexao.execute(
                    """
                    INSERT INTO canonical_odds_observations (
                        match_id, bookmaker, market, selection, decimal_odds,
                        line, observed_at, provider_id, record_ref, license_class
                    )
                    SELECT * FROM unnest(
                        $1::uuid[], $2::text[], $3::text[], $4::text[],
                        $5::numeric[], $6::numeric[], $7::timestamptz[],
                        $8::text[], $9::text[], $10::text[]
                    )
                    ON CONFLICT (match_id, bookmaker, market, selection,
                                 coalesce(line, -1))
                    DO NOTHING
                    """,
                    [o.match_id.value for o in bloco],
                    [str(o.bookmaker) for o in bloco],
                    [o.market.value for o in bloco],
                    [o.selection.value for o in bloco],
                    [o.decimal_odds for o in bloco],
                    [o.line for o in bloco],
                    [o.observed_at for o in bloco],
                    [
                        str(o.provenance.provider_id) if o.provenance.provider_id else ""
                        for o in bloco
                    ],
                    [o.provenance.source_record_id or "" for o in bloco],
                    [o.provenance.license_class.value for o in bloco],
                )
                gravadas = await conexao.fetch(
                    """
                    SELECT match_id, bookmaker, market, selection, line, decimal_odds
                    FROM canonical_odds_observations
                    WHERE match_id = ANY($1::uuid[])
                    """,
                    list({o.match_id.value for o in bloco}),
                )
                por_chave = {
                    (
                        linha["match_id"],
                        linha["bookmaker"],
                        linha["market"],
                        linha["selection"],
                        linha["line"],
                    ): linha["decimal_odds"]
                    for linha in gravadas
                }
                for observacao in bloco:
                    chave = (
                        observacao.match_id.value,
                        str(observacao.bookmaker),
                        observacao.market.value,
                        observacao.selection.value,
                        observacao.line,
                    )
                    existente = por_chave.get(chave)
                    desfechos[observacao.match_id] = _pior_desfecho(
                        desfechos.get(observacao.match_id),
                        _desfecho_de_odd(existente, observacao.decimal_odds),
                    )
        return desfechos


@final
class PostgresCanonicalBuildRunRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def create(self, run: CanonicalBuildRun) -> CanonicalBuildRun:
        async with self._db.acquire() as conexao, conexao.transaction():
            await conexao.execute(
                """
                INSERT INTO canonical_build_runs (
                    id, quality_run_id, build_policy_major, build_policy_minor,
                    build_policy_fingerprint, scope,
                    quality_policy_major, quality_policy_minor,
                    status, started_at, triggered_by, triggered_by_kind
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                """,
                uuid.UUID(run.id),
                uuid.UUID(run.quality_run_id),
                run.build_policy_version.major,
                run.build_policy_version.minor,
                run.build_policy_fingerprint.value if run.build_policy_fingerprint else None,
                run.scope.value,
                run.quality_policy_version.major,
                run.quality_policy_version.minor,
                run.status.value,
                run.started_at,
                run.triggered_by.id,
                run.triggered_by.kind.value,
            )
            await conexao.executemany(
                "INSERT INTO canonical_build_run_inputs (build_run_id, fusion_run_id) "
                "VALUES ($1, $2) ON CONFLICT DO NOTHING",
                [(uuid.UUID(run.id), uuid.UUID(f)) for f in run.input_fusion_run_ids],
            )
        return run

    async def save_policy_snapshot(self, run_id: str, policy: CanonicalBuildPolicy) -> None:
        """Grava a política inteira dentro da execução (§18).

        CONDICIONAL A `RUNNING`: uma execução concluída não ganha snapshot
        novo, senão a política de um build de seis meses atrás poderia ser
        reescrita — e a reprodutibilidade se apoia justamente nela.
        """
        async with self._db.acquire() as conexao:
            await conexao.execute(
                "UPDATE canonical_build_runs SET build_policy_snapshot = $2 "
                "WHERE id = $1 AND status = 'RUNNING'",
                uuid.UUID(run_id),
                json.dumps(policy.as_canonical()),
            )

    async def finish(self, run: CanonicalBuildRun) -> bool:
        async with self._db.acquire() as conexao:
            resultado = await conexao.execute(
                """
                UPDATE canonical_build_runs
                SET status = $2, completed_at = $3, failure_reason = $4,
                    records_attempted = $5, records_built = $6, records_reused = $7,
                    records_skipped = $8, records_review_required = $9,
                    records_failed = $10, families_excluded = $11,
                    output_fingerprint = $12
                WHERE id = $1 AND status = 'RUNNING'
                """,
                uuid.UUID(run.id),
                run.status.value,
                run.completed_at,
                run.failure_reason,
                run.counts.records_attempted,
                run.counts.records_built,
                run.counts.records_reused,
                run.counts.records_skipped,
                run.counts.records_review_required,
                run.counts.records_failed,
                run.counts.families_excluded,
                run.output_fingerprint.value if run.output_fingerprint else None,
            )
        return _linhas(resultado) > 0

    async def by_id(self, run_id: str) -> CanonicalBuildRun | None:
        try:
            identificador = uuid.UUID(run_id)
        except ValueError:
            return None
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                "SELECT * FROM canonical_build_runs WHERE id = $1", identificador
            )
            if linha is None:
                return None
            entradas = await conexao.fetch(
                "SELECT fusion_run_id FROM canonical_build_run_inputs "
                "WHERE build_run_id = $1 ORDER BY fusion_run_id",
                identificador,
            )
        return _para_build(linha, tuple(str(e["fusion_run_id"]) for e in entradas))

    async def for_quality_run(
        self, quality_run_id: str, *, limit: int = 20
    ) -> Sequence[CanonicalBuildRun]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT * FROM canonical_build_runs WHERE quality_run_id = $1 "
                "ORDER BY started_at DESC LIMIT $2",
                uuid.UUID(quality_run_id),
                min(limit, 100),
            )
            if not linhas:
                return []
            entradas = await conexao.fetch(
                "SELECT build_run_id, fusion_run_id FROM canonical_build_run_inputs "
                "WHERE build_run_id = ANY($1::uuid[]) ORDER BY build_run_id, fusion_run_id",
                [linha["id"] for linha in linhas],
            )
        por_execucao: dict[Any, list[str]] = {}
        for entrada in entradas:
            por_execucao.setdefault(entrada["build_run_id"], []).append(
                str(entrada["fusion_run_id"])
            )
        return [_para_build(linha, tuple(por_execucao.get(linha["id"], []))) for linha in linhas]


@final
class PostgresCanonicalBuildRecordRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def append_many(self, records: Sequence[CanonicalBuildRecord]) -> int:
        if not records:
            return 0
        gravados = 0
        async with self._db.acquire() as conexao, conexao.transaction():
            for inicio in range(0, len(records), _FATOS_POR_RODADA):
                bloco = records[inicio : inicio + _FATOS_POR_RODADA]
                # `executemany` E NÃO `unnest`, pelo mesmo motivo das
                # avaliações: duas colunas são `text[]`, e `unnest` sobre um
                # array de arrays o achata.
                await conexao.executemany(
                    """
                    INSERT INTO canonical_build_records (
                        id, build_run_id, match_id, fact_type, fact_id,
                        source_fusion_group_id, quality_assessment_id, status,
                        included_families, excluded_families, reason
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    ON CONFLICT (build_run_id, match_id, fact_type) DO NOTHING
                    """,
                    [
                        (
                            uuid.UUID(r.id),
                            uuid.UUID(r.build_run_id),
                            r.match_id.value,
                            r.fact_type.value,
                            r.fact_id,
                            uuid.UUID(r.source_fusion_group_id),
                            uuid.UUID(r.quality_assessment_id),
                            r.status.value,
                            [f.value for f in r.included_families],
                            [f.value for f in r.excluded_families],
                            r.reason,
                        )
                        for r in bloco
                    ],
                )
                gravados += len(bloco)
        return gravados

    async def by_run(
        self, run_id: str, *, limit: int = 200, offset: int = 0
    ) -> tuple[Sequence[CanonicalBuildRecord], int]:
        async with self._db.acquire() as conexao:
            total = await conexao.fetchval(
                "SELECT count(*) FROM canonical_build_records WHERE build_run_id = $1",
                uuid.UUID(run_id),
            )
            linhas = await conexao.fetch(
                "SELECT * FROM canonical_build_records WHERE build_run_id = $1 "
                "ORDER BY match_id, fact_type LIMIT $2 OFFSET $3",
                uuid.UUID(run_id),
                min(limit, 500),
                offset,
            )
        return [_para_registro_de_build(linha) for linha in linhas], int(total or 0)

    async def for_match(self, match_id: MatchId) -> Sequence[CanonicalBuildRecord]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT * FROM canonical_build_records WHERE match_id = $1 "
                "ORDER BY created_at, fact_type",
                match_id.value,
            )
        return [_para_registro_de_build(linha) for linha in linhas]

    async def record_family_decisions(self, run_id: str, decisions: Sequence[BuildDecision]) -> int:
        """Grava a decisão por família — o rastro do §20."""
        linhas = [
            (decisao.match_id, familia) for decisao in decisions for familia in decisao.families
        ]
        if not linhas:
            return 0
        async with self._db.acquire() as conexao:
            await conexao.execute(
                """
                INSERT INTO canonical_build_family_decisions (
                    build_run_id, match_id, family, outcome, reason, license_class
                )
                SELECT $1, * FROM unnest(
                    $2::uuid[], $3::text[], $4::text[], $5::text[], $6::text[]
                )
                ON CONFLICT (build_run_id, match_id, family) DO NOTHING
                """,
                uuid.UUID(run_id),
                [m.value for m, _ in linhas],
                [f.family.value for _, f in linhas],
                [f.outcome.value for _, f in linhas],
                [f.reason.value if f.reason else None for _, f in linhas],
                [f.license_class.value if f.license_class else None for _, f in linhas],
            )
        return len(linhas)

    async def family_decisions_of(self, run_id: str, match_id: MatchId) -> Sequence[FamilyDecision]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT * FROM canonical_build_family_decisions "
                "WHERE build_run_id = $1 AND match_id = $2 ORDER BY family",
                uuid.UUID(run_id),
                match_id.value,
            )
        return [
            FamilyDecision(
                family=CoverageFamily(linha["family"]),
                outcome=FamilyOutcome(linha["outcome"]),
                reason=(FamilyExclusionReason(linha["reason"]) if linha["reason"] else None),
                license_class=(
                    LicenseClass(linha["license_class"]) if linha["license_class"] else None
                ),
            )
            for linha in linhas
        ]


# ------------------------------------------------------------ equivalência --


def _partida_equivalente(match: Match, linha: Any) -> bool:
    """Se a partida existente descreve a MESMA partida (§62, §63).

    OS CAMPOS COMPARADOS SÃO OS ESTRUTURAIS. Um `venue` corrigido ou um
    `lifecycle` avançado não fazem de duas linhas duas partidas — comparar
    tudo faria toda reingestão legítima virar conflito, e um conflito que
    sempre dispara é um conflito que ninguém lê.
    """
    return bool(
        linha["competition_id"] == match.competition_id.value
        and linha["season_id"] == match.season_id.value
        and linha["home_team_id"] == match.home_team_id.value
        and linha["away_team_id"] == match.away_team_id.value
        and linha["scheduled_kickoff"] == match.scheduled_kickoff
        and linha["stage_type"] == match.stage.type.value
        and linha["round_number"] == match.stage.round_number
        and linha["group_label"] == match.stage.group_label
    )


def _resultado_equivalente(result: MatchResult, linha: Any) -> bool:
    return bool(
        linha["regular_home"] == result.regular_time.home
        and linha["regular_away"] == result.regular_time.away
        and linha["extra_home"] == (result.extra_time.home if result.extra_time else None)
        and linha["extra_away"] == (result.extra_time.away if result.extra_time else None)
        and linha["penalties_home"] == (result.penalties.home if result.penalties else None)
        and linha["penalties_away"] == (result.penalties.away if result.penalties else None)
    )


def _desfecho_de_odd(existente: Decimal | None, cotacao: Decimal) -> MatchWriteOutcome:
    if existente is None:
        return MatchWriteOutcome.CONFLICT
    return (
        MatchWriteOutcome.REUSED_EQUIVALENT
        if Decimal(existente) == cotacao
        else MatchWriteOutcome.CONFLICT
    )


#: Da mais grave para a menos. Uma partida cujas odds em parte entraram e em
#: parte conflitaram é um CONFLITO — reportar sucesso porque a maioria passou
#: é a declaração falsa do §66 em escala menor.
_ORDEM_DE_DESFECHO: Final[dict[MatchWriteOutcome, int]] = {
    MatchWriteOutcome.CONFLICT: 0,
    MatchWriteOutcome.REUSED_EQUIVALENT: 1,
    MatchWriteOutcome.INSERTED: 2,
}


def _pior_desfecho(atual: MatchWriteOutcome | None, novo: MatchWriteOutcome) -> MatchWriteOutcome:
    if atual is None:
        return novo
    return min(atual, novo, key=lambda d: _ORDEM_DE_DESFECHO[d])


# --------------------------------------------------------------- tradução --


def _para_identidade(linha: Any) -> MatchIdentityFacts:
    return MatchIdentityFacts(
        match_id=MatchId(linha["id"]),
        competition_id=CompetitionId(linha["competition_id"]),
        season_id=SeasonId(linha["season_id"]),
        regime=CompetitionRegime(
            code=RegimeCode(linha["regime_code"]),
            effective_from=instant(linha["regime_from"]),
            regulation_version=linha["regulation_version"],
            effective_to=instant(linha["regime_to"]) if linha["regime_to"] else None,
        ),
        stage=Stage(
            type=StageType(linha["stage_type"]),
            round_number=linha["round_number"],
            group_label=linha["group_label"],
        ),
        home_team_id=TeamId(linha["home_team_id"]),
        away_team_id=TeamId(linha["away_team_id"]),
        scheduled_kickoff=instant(linha["scheduled_kickoff"]),
        actual_kickoff=(instant(linha["actual_kickoff"]) if linha["actual_kickoff"] else None),
        venue=Venue(name=linha["venue_name"]) if linha["venue_name"] else None,
        neutral_venue=linha["neutral_venue"],
    )


def _para_build(linha: Any, fusion_run_ids: tuple[str, ...]) -> CanonicalBuildRun:
    return CanonicalBuildRun(
        id=str(linha["id"]),
        quality_run_id=str(linha["quality_run_id"]),
        input_fusion_run_ids=fusion_run_ids,
        build_policy_version=PolicyVersion(
            major=linha["build_policy_major"], minor=linha["build_policy_minor"]
        ),
        build_policy_fingerprint=(
            ContentHash(linha["build_policy_fingerprint"])
            if linha["build_policy_fingerprint"]
            else None
        ),
        scope=UsageScope(linha["scope"]),
        quality_policy_version=PolicyVersion(
            major=linha["quality_policy_major"], minor=linha["quality_policy_minor"]
        ),
        status=RunStatus(linha["status"]),
        started_at=instant(linha["started_at"]),
        triggered_by=Actor(id=linha["triggered_by"], kind=ActorKind(linha["triggered_by_kind"])),
        counts=BuildCounts(
            records_attempted=linha["records_attempted"],
            records_built=linha["records_built"],
            records_reused=linha["records_reused"],
            records_skipped=linha["records_skipped"],
            records_review_required=linha["records_review_required"],
            records_failed=linha["records_failed"],
            families_excluded=linha["families_excluded"],
        ),
        completed_at=instant(linha["completed_at"]) if linha["completed_at"] else None,
        failure_reason=linha["failure_reason"],
        output_fingerprint=(
            ContentHash(linha["output_fingerprint"]) if linha["output_fingerprint"] else None
        ),
    )


def _para_registro_de_build(linha: Any) -> CanonicalBuildRecord:
    return CanonicalBuildRecord(
        id=str(linha["id"]),
        build_run_id=str(linha["build_run_id"]),
        match_id=MatchId(linha["match_id"]),
        fact_type=CanonicalFactType(linha["fact_type"]),
        source_fusion_group_id=str(linha["source_fusion_group_id"]),
        quality_assessment_id=str(linha["quality_assessment_id"]),
        status=BuildRecordStatus(linha["status"]),
        fact_id=linha["fact_id"],
        included_families=tuple(CoverageFamily(f) for f in linha["included_families"]),
        excluded_families=tuple(CoverageFamily(f) for f in linha["excluded_families"]),
        reason=linha["reason"],
    )


def _linhas(resultado: str) -> int:
    try:
        return int(str(resultado).rsplit(" ", 1)[-1])
    except (ValueError, IndexError):
        return 0
