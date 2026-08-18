"""Os repositórios do corpus histórico em SQL escrito à mão.

O QUE É PARTICULAR DESTE ARQUIVO, e não aparece nos anteriores:

A COMPOSIÇÃO É UMA CONSULTA DE INTERSEÇÃO. «Os fatos que estes builds
autorizaram» não é «tudo que está no registro canônico»: o registro é global e
contém também o que um build de pesquisa escreveu. O cruzamento com
`canonical_build_records` é o que separa os dois, e ele acontece no BANCO —
trazer as duas listas para Python e intersectá-las seria carregar o registro
inteiro para descartar a maior parte.

A MESMA PARTIDA EM DOIS BUILDS VOLTA DUAS VEZES, E É DELIBERADO (PR-04.3.1
§22). Este arquivo já usou `DISTINCT ON (match_id) … ORDER BY created_at DESC`
para não duplicar a partida, e ao deduplicar respondia uma pergunta que ninguém
fez: «qual build vence?». Com o perdedor sumiam as famílias que ele incluiu e a
linhagem que ele registrou.

A leitura devolve uma linha por (partida, build), adjacentes e em ordem
determinística; quem as junta é `domain/corpus/composition.py` — união de
famílias quando os fatos concordam, recusa quando divergem, linhagem inteira
nos dois casos. Nenhuma cláusula SQL sabe tomar essa decisão.

NENHUM `UPDATE` SOBRE VERSÃO PUBLICADA. A única escrita que uma versão aceita é
a transição de estado, e ela é condicional ao estado anterior — o
`UPDATE ... WHERE status = $n` que serializa duas publicações simultâneas sem
lock distribuído (§84).

A PERTINÊNCIA É `ON CONFLICT DO NOTHING` (§83). Um retry depois de um timeout
parcial reescreve o lote inteiro e não duplica nada.
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
    BuildOutcome,
    FamilyDecision,
    FamilyExclusionReason,
    FamilyOutcome,
)
from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.competitions.models import (
    CompetitionRegime,
    RegimeCode,
    Stage,
    StageType,
)
from sports_intelligence.domain.corpus.facts import MatchCorpusFacts
from sports_intelligence.domain.corpus.manifest import (
    CorpusObjectRef,
    FamilyCoverageSummary,
    HistoricalCanonicalManifest,
    IssueSummary,
    LicenseSummary,
    QualitySummary,
)
from sports_intelligence.domain.corpus.membership import (
    BuildContribution,
    CorpusMember,
    MembershipCounts,
)
from sports_intelligence.domain.corpus.scope import CorpusScope, ScopeEntry
from sports_intelligence.domain.corpus.versions import (
    DatasetVersionStatus,
    HistoricalCanonicalDataset,
    HistoricalCanonicalDatasetVersion,
    VersionInputs,
)
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.matches.lifecycle import MatchLifecycle
from sports_intelligence.domain.matches.lineup import (
    Lineup,
    LineupEntry,
    LineupStatus,
)
from sports_intelligence.domain.matches.models import Match, Venue
from sports_intelligence.domain.matches.result import MatchResult, Score
from sports_intelligence.domain.odds.models import (
    BookmakerRef,
    CanonicalOddsObservation,
    OddsMarket,
    OddsSelection,
)
from sports_intelligence.domain.players.positions import Position
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.resolution.versions import PolicyVersion
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.errors import ConflictError
from sports_intelligence.domain.shared.identity import (
    CompetitionId,
    MatchId,
    PlayerId,
    ProviderId,
    SeasonId,
    TeamId,
)
from sports_intelligence.domain.shared.provenance import (
    DataProvenance,
    LicenseClass,
    SourceType,
)
from sports_intelligence.domain.shared.temporal import ObservationTimes, instant
from sports_intelligence.domain.shared.versioning import DatasetVersion

#: Quantos ids vão por rodada de `ANY(...)`. Mesma calibração dos demais
#: repositórios: troca idas ao banco por tamanho de array, sem pico visível.
_POR_RODADA: Final[int] = 500

#: Os estados de linhagem que significam «este fato está no registro». Um
#: `SKIPPED` não tem fato para publicar, e um `FAILED` menos ainda.
_MATERIALIZADOS: Final[tuple[str, ...]] = ("BUILT", "REUSED")


@final
class PostgresHistoricalCorpusRepository:
    """Datasets, versões e a ligação com os builds que os compuseram."""

    def __init__(self, database: Database) -> None:
        self._db = database

    # ------------------------------------------------------------ dataset --

    async def create_dataset(
        self, dataset: HistoricalCanonicalDataset
    ) -> HistoricalCanonicalDataset:
        async with self._db.acquire() as conexao:
            try:
                await conexao.execute(
                    """
                    INSERT INTO historical_canonical_datasets (
                        id, name, description, created_at, created_by,
                        created_by_kind
                    )
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    uuid.UUID(dataset.id),
                    dataset.name,
                    dataset.description,
                    dataset.created_at,
                    dataset.created_by.id,
                    dataset.created_by.kind.value,
                )
            except Exception as erro:  # asyncpg.UniqueViolationError
                if "historical_canonical_datasets_nome_unico" not in str(erro):
                    raise
                raise ConflictError(
                    f"já existe um dataset histórico chamado {dataset.name!r}",
                    context={"name": dataset.name},
                ) from erro
        return dataset

    async def dataset_by_name(self, name: str) -> HistoricalCanonicalDataset | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"SELECT {_COLUNAS_DATASET} FROM historical_canonical_datasets WHERE name = $1",
                name,
            )
        return None if linha is None else _para_dataset(linha)

    async def dataset_by_id(self, dataset_id: str) -> HistoricalCanonicalDataset | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"SELECT {_COLUNAS_DATASET} FROM historical_canonical_datasets WHERE id = $1",
                uuid.UUID(dataset_id),
            )
        return None if linha is None else _para_dataset(linha)

    async def list_datasets(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[Sequence[HistoricalCanonicalDataset], int]:
        async with self._db.acquire() as conexao:
            total = await conexao.fetchval("SELECT count(*) FROM historical_canonical_datasets")
            linhas = await conexao.fetch(
                f"SELECT {_COLUNAS_DATASET} FROM historical_canonical_datasets "
                "ORDER BY created_at DESC LIMIT $1 OFFSET $2",
                limit,
                offset,
            )
        return [_para_dataset(linha) for linha in linhas], int(total or 0)

    # ------------------------------------------------------------- versão --

    async def create_version(
        self, version: HistoricalCanonicalDatasetVersion
    ) -> HistoricalCanonicalDatasetVersion:
        async with self._db.acquire() as conexao:
            try:
                await conexao.execute(
                    """
                    INSERT INTO historical_canonical_dataset_versions (
                        id, dataset_id, version_major, version_minor,
                        usage_scope, status, match_count, created_at,
                        created_by, created_by_kind, inputs, scope
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                            $11::jsonb, $12::jsonb)
                    """,
                    uuid.UUID(version.id),
                    uuid.UUID(version.dataset_id),
                    version.version.major,
                    version.version.minor,
                    version.scope.usage.value,
                    version.status.value,
                    version.match_count,
                    version.created_at,
                    version.created_by.id,
                    version.created_by.kind.value,
                    json.dumps(version.inputs.as_canonical()),
                    json.dumps(version.scope.as_canonical()),
                )
            except Exception as erro:
                if "hcdv_versao_unica" not in str(erro):
                    raise
                raise ConflictError(
                    f"a versão {version.version} já existe neste dataset. «1.0» "
                    "precisa significar um conteúdo só, para sempre (ADR-0026)",
                    context={"version": str(version.version)},
                ) from erro
        return version

    async def version_by_id(self, version_id: str) -> HistoricalCanonicalDatasetVersion | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"SELECT {_COLUNAS_VERSAO} FROM historical_canonical_dataset_versions "
                "WHERE id = $1",
                uuid.UUID(version_id),
            )
        return None if linha is None else _para_versao(linha)

    async def version_of(
        self, dataset_id: str, version: DatasetVersion
    ) -> HistoricalCanonicalDatasetVersion | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"SELECT {_COLUNAS_VERSAO} FROM historical_canonical_dataset_versions "
                "WHERE dataset_id = $1 AND version_major = $2 AND version_minor = $3",
                uuid.UUID(dataset_id),
                version.major,
                version.minor,
            )
        return None if linha is None else _para_versao(linha)

    async def transition(
        self,
        version: HistoricalCanonicalDatasetVersion,
        *,
        expected: DatasetVersionStatus,
    ) -> bool:
        """`UPDATE ... WHERE status = $expected`. Devolve se pegou a linha.

        É A ÚNICA ESCRITA QUE UMA VERSÃO ACEITA, e a cláusula `WHERE` é o que
        serializa duas publicações simultâneas sem Redis: a segunda vê zero
        linhas afetadas e decide, em vez de sobrescrever (§84).
        """
        async with self._db.acquire() as conexao:
            resultado = await conexao.execute(
                """
                UPDATE historical_canonical_dataset_versions
                SET status = $2,
                    corpus_fingerprint = $3,
                    manifest_id = $4,
                    match_count = $5,
                    completed_at = $6,
                    failure_reason = $7,
                    superseded_by = $8
                WHERE id = $1 AND status = $9
                """,
                uuid.UUID(version.id),
                version.status.value,
                None if version.corpus_fingerprint is None else version.corpus_fingerprint.value,
                None if version.manifest_id is None else uuid.UUID(version.manifest_id),
                version.match_count,
                version.completed_at,
                version.failure_reason,
                None if version.superseded_by is None else uuid.UUID(version.superseded_by),
                expected.value,
            )
        return _linhas_afetadas(resultado) == 1

    async def list_versions(
        self,
        dataset_id: str,
        *,
        status: DatasetVersionStatus | None = None,
        usage: UsageScope | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[HistoricalCanonicalDatasetVersion], int]:
        async with self._db.acquire() as conexao:
            total = await conexao.fetchval(
                """
                SELECT count(*) FROM historical_canonical_dataset_versions
                WHERE dataset_id = $1
                  AND ($2::text IS NULL OR status = $2)
                  AND ($3::text IS NULL OR usage_scope = $3)
                """,
                uuid.UUID(dataset_id),
                None if status is None else status.value,
                None if usage is None else usage.value,
            )
            linhas = await conexao.fetch(
                f"""
                SELECT {_COLUNAS_VERSAO}
                FROM historical_canonical_dataset_versions
                WHERE dataset_id = $1
                  AND ($2::text IS NULL OR status = $2)
                  AND ($3::text IS NULL OR usage_scope = $3)
                ORDER BY version_major DESC, version_minor DESC
                LIMIT $4 OFFSET $5
                """,
                uuid.UUID(dataset_id),
                None if status is None else status.value,
                None if usage is None else usage.value,
                limit,
                offset,
            )
        return [_para_versao(linha) for linha in linhas], int(total or 0)

    async def latest_ready(
        self, dataset_id: str, *, usage: UsageScope
    ) -> HistoricalCanonicalDatasetVersion | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"""
                SELECT {_COLUNAS_VERSAO}
                FROM historical_canonical_dataset_versions
                WHERE dataset_id = $1 AND usage_scope = $2 AND status = 'READY'
                ORDER BY completed_at DESC
                LIMIT 1
                """,
                uuid.UUID(dataset_id),
                usage.value,
            )
        return None if linha is None else _para_versao(linha)

    # -------------------------------------------------------- composição --

    async def register_builds(self, version_id: str, build_run_ids: Sequence[str]) -> int:
        if not build_run_ids:
            return 0
        async with self._db.acquire() as conexao:
            await conexao.execute(
                """
                INSERT INTO historical_canonical_version_builds
                    (version_id, build_run_id)
                SELECT $1, unnest($2::uuid[])
                ON CONFLICT DO NOTHING
                """,
                uuid.UUID(version_id),
                [uuid.UUID(b) for b in build_run_ids],
            )
        return len(build_run_ids)

    async def build_run_ids_of(self, version_id: str) -> Sequence[str]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT build_run_id FROM historical_canonical_version_builds "
                "WHERE version_id = $1 ORDER BY build_run_id",
                uuid.UUID(version_id),
            )
        return [str(linha["build_run_id"]) for linha in linhas]

    async def versions_using_build(
        self, build_run_id: str, *, limit: int = 20
    ) -> Sequence[HistoricalCanonicalDatasetVersion]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                f"""
                SELECT {_COLUNAS_VERSAO}
                FROM historical_canonical_dataset_versions v
                JOIN historical_canonical_version_builds b ON b.version_id = v.id
                WHERE b.build_run_id = $1
                ORDER BY v.created_at DESC
                LIMIT $2
                """,
                uuid.UUID(build_run_id),
                limit,
            )
        return [_para_versao(linha) for linha in linhas]


@final
class PostgresCorpusMembershipRepository:
    """A pertinência. Gravada em lote, lida por chave, nunca derivada."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def append_members(self, version_id: str, members: Sequence[CorpusMember]) -> int:
        if not members:
            return 0
        gravados = 0
        async with self._db.acquire() as conexao, conexao.transaction():
            for inicio in range(0, len(members), _POR_RODADA):
                bloco = members[inicio : inicio + _POR_RODADA]
                # `executemany` E NÃO `unnest` COM `text[][]`: `unnest`
                # ACHATA um array bidimensional, e as famílias de todas as
                # partidas viriam misturadas numa lista só — o defeito que o
                # PR-04.2 encontrou nesta mesma forma de escrita.
                await conexao.executemany(
                    """
                    INSERT INTO historical_canonical_members (
                        version_id, match_id, competition_id, season_id,
                        competition_code, season_label, included_families,
                        content_fingerprint
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (version_id, match_id) DO NOTHING
                    """,
                    [
                        (
                            uuid.UUID(version_id),
                            m.match_id.value,
                            m.competition_id.value,
                            m.season_id.value,
                            m.competition.value,
                            m.season_label,
                            [f.value for f in m.included_families],
                            m.content_fingerprint.value,
                        )
                        for m in bloco
                    ],
                )
                # AS CONTRIBUIÇÕES VÊM DEPOIS, E NA MESMA TRANSAÇÃO. Um membro
                # sem linhagem é um membro sem resposta para «por que esta
                # partida está no corpus»; separá-las em duas transações
                # deixaria essa janela aberta a cada lote.
                await conexao.executemany(
                    """
                    INSERT INTO historical_canonical_member_builds (
                        version_id, match_id, build_run_id,
                        quality_assessment_id, included_families
                    )
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT DO NOTHING
                    """,
                    [
                        (
                            uuid.UUID(version_id),
                            m.match_id.value,
                            uuid.UUID(c.build_run_id),
                            uuid.UUID(c.quality_assessment_id),
                            [f.value for f in c.included_families],
                        )
                        for m in bloco
                        for c in m.contributions
                    ],
                )
                gravados += len(bloco)
        return gravados

    async def page_members(
        self,
        version_id: str,
        *,
        limit: int = 500,
        after_match_id: str | None = None,
    ) -> Sequence[CorpusMember]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT m.match_id, m.competition_id, m.season_id,
                       m.competition_code, m.season_label, m.included_families,
                       m.content_fingerprint,
                       coalesce(b.contributions, '[]'::jsonb) AS contributions
                FROM historical_canonical_members m
                LEFT JOIN LATERAL (
                    SELECT jsonb_agg(
                               jsonb_build_object(
                                   'build_run_id', c.build_run_id,
                                   'quality_assessment_id', c.quality_assessment_id,
                                   'included_families', c.included_families
                               )
                               ORDER BY c.build_run_id
                           ) AS contributions
                    FROM historical_canonical_member_builds c
                    WHERE c.version_id = m.version_id AND c.match_id = m.match_id
                ) b ON true
                WHERE m.version_id = $1
                  AND ($2::uuid IS NULL OR m.match_id > $2::uuid)
                ORDER BY m.match_id
                LIMIT $3
                """,
                uuid.UUID(version_id),
                None if after_match_id is None else uuid.UUID(after_match_id),
                limit,
            )
        return [_para_membro(linha) for linha in linhas]

    async def members_by_match(
        self, version_id: str, match_ids: Sequence[MatchId]
    ) -> Sequence[CorpusMember]:
        if not match_ids:
            return []
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT m.match_id, m.competition_id, m.season_id,
                       m.competition_code, m.season_label, m.included_families,
                       m.content_fingerprint,
                       coalesce(b.contributions, '[]'::jsonb) AS contributions
                FROM historical_canonical_members m
                LEFT JOIN LATERAL (
                    SELECT jsonb_agg(
                               jsonb_build_object(
                                   'build_run_id', c.build_run_id,
                                   'quality_assessment_id', c.quality_assessment_id,
                                   'included_families', c.included_families
                               )
                               ORDER BY c.build_run_id
                           ) AS contributions
                    FROM historical_canonical_member_builds c
                    WHERE c.version_id = m.version_id AND c.match_id = m.match_id
                ) b ON true
                WHERE m.version_id = $1 AND m.match_id = ANY($2::uuid[])
                ORDER BY m.match_id
                """,
                uuid.UUID(version_id),
                [m.value for m in match_ids],
            )
        return [_para_membro(linha) for linha in linhas]

    async def count_members(self, version_id: str) -> int:
        async with self._db.acquire() as conexao:
            total = await conexao.fetchval(
                "SELECT count(*) FROM historical_canonical_members WHERE version_id = $1",
                uuid.UUID(version_id),
            )
        return int(total or 0)

    async def versions_containing(self, match_id: MatchId, *, limit: int = 20) -> Sequence[str]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT version_id FROM historical_canonical_members WHERE match_id = $1 LIMIT $2",
                match_id.value,
                limit,
            )
        return [str(linha["version_id"]) for linha in linhas]


@final
class PostgresCanonicalManifestRepository:
    """Manifestos publicados. Um por versão, e sem `UPDATE` nenhum."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def save(
        self,
        manifest: HistoricalCanonicalManifest,
        *,
        object_key: str | None = None,
    ) -> HistoricalCanonicalManifest:
        async with self._db.acquire() as conexao:
            try:
                await conexao.execute(
                    """
                    INSERT INTO historical_canonical_manifests (
                        id, version_id, schema_version, document,
                        corpus_fingerprint, manifest_sha256, object_key,
                        created_at, fingerprint_algorithm,
                        fingerprint_schema_version
                    )
                    VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9, $10)
                    """,
                    uuid.UUID(manifest.id),
                    uuid.UUID(manifest.dataset_version_id),
                    manifest.schema_version,
                    manifest.to_json().decode("utf-8"),
                    manifest.corpus_fingerprint.value,
                    manifest.manifest_sha256.value,
                    object_key,
                    manifest.created_at,
                    manifest.fingerprint_algorithm,
                    manifest.fingerprint_schema_version,
                )
            except Exception as erro:
                if "hcmf_um_por_versao" not in str(erro):
                    raise
                raise ConflictError(
                    "esta versão já tem manifesto. Um segundo descreveria o mesmo "
                    "corpus de outra forma, e a segunda seria a que ninguém leu",
                    context={"version_id": manifest.dataset_version_id},
                ) from erro
        return manifest

    async def by_version(self, version_id: str) -> HistoricalCanonicalManifest | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                "SELECT document FROM historical_canonical_manifests WHERE version_id = $1",
                uuid.UUID(version_id),
            )
        return None if linha is None else _para_manifesto(linha["document"])

    async def record_objects(self, version_id: str, objects: Sequence[CorpusObjectRef]) -> int:
        """Grava os objetos materializados. Idempotente pela chave."""
        if not objects:
            return 0
        async with self._db.acquire() as conexao, conexao.transaction():
            await conexao.executemany(
                """
                INSERT INTO historical_canonical_objects (
                    id, version_id, object_key, family, competition_code,
                    season_label, sha256, size_bytes, row_count, content_type,
                    created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, now())
                ON CONFLICT (version_id, object_key) DO NOTHING
                """,
                [
                    (
                        uuid.uuid4(),
                        uuid.UUID(version_id),
                        objeto.object_key,
                        objeto.family,
                        objeto.competition,
                        objeto.season,
                        objeto.sha256.value,
                        objeto.size_bytes,
                        objeto.row_count,
                        objeto.content_type,
                    )
                    for objeto in objects
                ],
            )
        return len(objects)

    async def objects_of(self, version_id: str) -> Sequence[CorpusObjectRef]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT object_key, family, competition_code, season_label,
                       sha256, size_bytes, row_count, content_type
                FROM historical_canonical_objects
                WHERE version_id = $1
                ORDER BY object_key
                """,
                uuid.UUID(version_id),
            )
        return [
            CorpusObjectRef(
                object_key=linha["object_key"],
                family=linha["family"],
                competition=linha["competition_code"],
                season=linha["season_label"],
                sha256=ContentHash(linha["sha256"]),
                size_bytes=linha["size_bytes"],
                row_count=linha["row_count"],
                content_type=linha["content_type"],
            )
            for linha in linhas
        ]

    async def by_fingerprint(
        self, corpus_fingerprint: str, *, limit: int = 10
    ) -> Sequence[HistoricalCanonicalManifest]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT document FROM historical_canonical_manifests "
                "WHERE corpus_fingerprint = $1 ORDER BY created_at DESC LIMIT $2",
                corpus_fingerprint,
                limit,
            )
        return [_para_manifesto(linha["document"]) for linha in linhas]


@final
class PostgresCorpusCompositionReader:
    """De onde saem os fatos que uma versão publica.

    QUATRO CONSULTAS POR LOTE, e não quatro por partida: a página de partidas,
    os resultados, as escalações com entradas e as observações de odds. É a
    mesma disciplina do §68 do PR-04.2, aplicada ao caminho de leitura.
    """

    def __init__(self, database: Database) -> None:
        self._db = database

    async def page_facts(
        self,
        build_run_ids: Sequence[str],
        *,
        limit: int = 500,
        after_match_id: str | None = None,
    ) -> Sequence[MatchCorpusFacts]:
        if not build_run_ids:
            return []
        execucoes = [uuid.UUID(b) for b in build_run_ids]
        async with self._db.acquire() as conexao:
            cabecalhos = await conexao.fetch(
                """
                WITH contribuicoes AS (
                    -- UMA LINHA POR (PARTIDA, BUILD), e NENHUM `DISTINCT ON`
                    -- (PR-04.3.1 §22, §29). Deduplicar aqui responderia «qual
                    -- build vence?» — uma pergunta que ninguém fez —, e com o
                    -- perdedor sumiriam as famílias e a linhagem dele.
                    --
                    -- Quem junta as contribuições é `compose`, no domínio: ele
                    -- une famílias quando os fatos concordam e RECUSA quando
                    -- divergem. Nenhuma cláusula SQL sabe fazer as duas coisas.
                    SELECT r.match_id, r.build_run_id, r.quality_assessment_id,
                           r.included_families
                    FROM canonical_build_records r
                    WHERE r.build_run_id = ANY($1::uuid[])
                      AND r.fact_type = 'MATCH'
                      AND r.status = ANY($2::text[])
                      AND ($3::uuid IS NULL OR r.match_id > $3::uuid)
                )
                SELECT e.match_id, e.build_run_id, e.quality_assessment_id,
                       e.included_families,
                       m.competition_id, m.season_id, m.home_team_id,
                       m.away_team_id, m.scheduled_kickoff, m.actual_kickoff,
                       m.stage_type, m.round_number, m.group_label,
                       m.regime_code, m.regime_from, m.regulation_version,
                       m.lifecycle, m.neutral_venue, m.venue_name,
                       c.code AS competition_code, s.label AS season_label,
                       s.regime_to,
                       res.regular_home, res.regular_away, res.extra_home,
                       res.extra_away, res.penalties_home, res.penalties_away
                FROM contribuicoes e
                JOIN matches m ON m.id = e.match_id
                JOIN competitions c ON c.id = m.competition_id
                JOIN seasons s ON s.id = m.season_id
                LEFT JOIN match_results res ON res.match_id = m.id
                -- A ORDEM SECUNDÁRIA POR BUILD é o que torna a página
                -- reproduzível: as linhas de uma mesma partida ficam
                -- adjacentes E na mesma ordem em toda execução.
                ORDER BY e.match_id, e.build_run_id
                LIMIT $4
                """,
                execucoes,
                list(_MATERIALIZADOS),
                None if after_match_id is None else uuid.UUID(after_match_id),
                limit,
            )
            if not cabecalhos:
                return []
            ids = list({linha["match_id"] for linha in cabecalhos})
            escalacoes = await self._escalacoes(conexao, ids)
            cotacoes = await self._cotacoes(conexao, ids)

        return [
            _para_fatos(
                linha,
                lineups=escalacoes.get(linha["match_id"], ()),
                odds=cotacoes.get(linha["match_id"], ()),
            )
            for linha in cabecalhos
        ]

    async def usage_scopes_of(self, build_run_ids: Sequence[str]) -> Mapping[str, UsageScope]:
        if not build_run_ids:
            return {}
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT id, scope FROM canonical_build_runs WHERE id = ANY($1::uuid[])",
                [uuid.UUID(b) for b in build_run_ids],
            )
        # AS AUSENTES NÃO VOLTAM, e quem chama trata a ausência: um build que
        # não existe é um erro diferente de um build com escopo divergente.
        return {str(linha["id"]): UsageScope(linha["scope"]) for linha in linhas}

    async def decisions_of(
        self, build_run_ids: Sequence[str], match_ids: Sequence[MatchId]
    ) -> Sequence[BuildDecision]:
        if not build_run_ids or not match_ids:
            return []
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT d.build_run_id, d.match_id, d.family, d.outcome,
                       d.reason, d.license_class, r.scope,
                       r.build_policy_major, r.build_policy_minor
                FROM canonical_build_family_decisions d
                JOIN canonical_build_runs r ON r.id = d.build_run_id
                WHERE d.build_run_id = ANY($1::uuid[])
                  AND d.match_id = ANY($2::uuid[])
                ORDER BY d.match_id, d.build_run_id, d.family
                """,
                [uuid.UUID(b) for b in build_run_ids],
                [m.value for m in match_ids],
            )
        # O AGRUPAMENTO É POR (BUILD, PARTIDA) E NÃO POR PARTIDA (PR-04.3.1
        # §22). Uma `BuildDecision` descreve o que UM build decidiu sobre UMA
        # partida; agrupar dois builds numa decisão só produziria a mesma
        # família duas vezes — e o domínio recusa, porque «a família decidida
        # duas vezes» é exatamente o sintoma de duas decisões misturadas.
        por_build_e_partida: dict[tuple[Any, Any], list[FamilyDecision]] = {}
        # O ESCOPO E A VERSÃO DA POLÍTICA VÊM DA EXECUÇÃO e não são inventados
        # aqui: uma `BuildDecision` sem eles não diz sob qual regra decidiu, e
        # é justamente essa a pergunta da auditoria (ADR-0025).
        contexto: dict[tuple[Any, Any], tuple[str, int, int]] = {}
        for linha in linhas:
            chave = (linha["match_id"], linha["build_run_id"])
            contexto[chave] = (
                linha["scope"],
                linha["build_policy_major"],
                linha["build_policy_minor"],
            )
            por_build_e_partida.setdefault(chave, []).append(
                FamilyDecision(
                    family=CoverageFamily(linha["family"]),
                    outcome=FamilyOutcome(linha["outcome"]),
                    reason=(
                        None if linha["reason"] is None else FamilyExclusionReason(linha["reason"])
                    ),
                    license_class=(
                        None
                        if linha["license_class"] is None
                        else LicenseClass(linha["license_class"])
                    ),
                )
            )
        return [
            BuildDecision(
                match_id=MatchId(chave[0]),
                outcome=(
                    BuildOutcome.BUILD
                    if any(f.outcome is FamilyOutcome.INCLUDED for f in familias)
                    else BuildOutcome.SKIP
                ),
                scope=UsageScope(contexto[chave][0]),
                build_policy_version=PolicyVersion(
                    major=contexto[chave][1], minor=contexto[chave][2]
                ),
                families=tuple(familias),
            )
            for chave, familias in sorted(
                por_build_e_partida.items(), key=lambda p: (str(p[0][0]), str(p[0][1]))
            )
        ]

    # ---------------------------------------------------------- internos --

    @staticmethod
    async def _escalacoes(conexao: Any, match_ids: Sequence[Any]) -> dict[Any, tuple[Lineup, ...]]:
        """As escalações e as entradas delas — UMA consulta, com junção."""
        linhas = await conexao.fetch(
            """
            SELECT l.match_id, l.team_id, l.formation, e.player_id, e.status,
                   e.shirt_number, e.position, e.captain
            FROM lineups l
            JOIN lineup_entries e
              ON e.match_id = l.match_id AND e.team_id = l.team_id
            WHERE l.match_id = ANY($1::uuid[])
            ORDER BY l.match_id, l.team_id, e.player_id
            """,
            list(match_ids),
        )
        agrupado: dict[tuple[Any, Any], list[Any]] = {}
        formacoes: dict[tuple[Any, Any], str | None] = {}
        for linha in linhas:
            chave = (linha["match_id"], linha["team_id"])
            agrupado.setdefault(chave, []).append(linha)
            formacoes[chave] = linha["formation"]

        por_partida: dict[Any, list[Lineup]] = {}
        for (partida, time), entradas in agrupado.items():
            por_partida.setdefault(partida, []).append(
                Lineup(
                    match_id=MatchId(partida),
                    team_id=TeamId(time),
                    entries=tuple(_para_entrada(linha) for linha in entradas),
                    formation=_para_formacao(formacoes[(partida, time)]),
                )
            )
        return {partida: tuple(v) for partida, v in por_partida.items()}

    @staticmethod
    async def _cotacoes(
        conexao: Any, match_ids: Sequence[Any]
    ) -> dict[Any, tuple[CanonicalOddsObservation, ...]]:
        linhas = await conexao.fetch(
            """
            SELECT match_id, bookmaker, market, selection, decimal_odds, line,
                   observed_at, provider_id, record_ref, license_class,
                   recorded_at
            FROM canonical_odds_observations
            WHERE match_id = ANY($1::uuid[])
            ORDER BY match_id, bookmaker, market, selection
            """,
            list(match_ids),
        )
        por_partida: dict[Any, list[CanonicalOddsObservation]] = {}
        for linha in linhas:
            por_partida.setdefault(linha["match_id"], []).append(_para_odd(linha))
        return {partida: tuple(v) for partida, v in por_partida.items()}


# ============================================================== mapeamento ==

_COLUNAS_DATASET: Final[str] = "id, name, description, created_at, created_by, created_by_kind"

_COLUNAS_VERSAO: Final[str] = (
    "id, dataset_id, version_major, version_minor, usage_scope, status, "
    "corpus_fingerprint, manifest_id, match_count, created_at, created_by, "
    "created_by_kind, completed_at, failure_reason, superseded_by, inputs, scope"
)


def _linhas_afetadas(resultado: str) -> int:
    """`UPDATE 1` → 1. asyncpg devolve a etiqueta de comando, não a contagem."""
    partes = str(resultado).split()
    return int(partes[-1]) if partes and partes[-1].isdigit() else 0


def _para_dataset(linha: Any) -> HistoricalCanonicalDataset:
    return HistoricalCanonicalDataset(
        id=str(linha["id"]),
        name=linha["name"],
        created_at=instant(linha["created_at"]),
        created_by=Actor(id=linha["created_by"], kind=ActorKind(linha["created_by_kind"])),
        description=linha["description"],
    )


def _para_versao(linha: Any) -> HistoricalCanonicalDatasetVersion:
    return HistoricalCanonicalDatasetVersion(
        id=str(linha["id"]),
        dataset_id=str(linha["dataset_id"]),
        version=DatasetVersion(major=linha["version_major"], minor=linha["version_minor"]),
        scope=_para_escopo(linha["scope"], linha["usage_scope"]),
        inputs=_para_entradas(linha["inputs"]),
        status=DatasetVersionStatus(linha["status"]),
        created_at=instant(linha["created_at"]),
        created_by=Actor(id=linha["created_by"], kind=ActorKind(linha["created_by_kind"])),
        corpus_fingerprint=(
            None
            if linha["corpus_fingerprint"] is None
            else ContentHash(linha["corpus_fingerprint"])
        ),
        manifest_id=None if linha["manifest_id"] is None else str(linha["manifest_id"]),
        match_count=linha["match_count"],
        completed_at=(None if linha["completed_at"] is None else instant(linha["completed_at"])),
        failure_reason=linha["failure_reason"],
        superseded_by=(None if linha["superseded_by"] is None else str(linha["superseded_by"])),
    )


def _para_escopo(bruto: Any, usage: str) -> CorpusScope:
    documento = _json(bruto)
    entradas = tuple(
        ScopeEntry(
            competition=CompetitionCode(e["competition"]),
            season_label=e["season"],
            competition_id=CompetitionId(uuid.UUID(e["competition_id"])),
            season_id=SeasonId(uuid.UUID(e["season_id"])),
        )
        for e in documento.get("entries", [])
    )
    return CorpusScope(entries=entradas, usage=UsageScope(usage))


def _para_entradas(bruto: Any) -> VersionInputs:
    documento = _json(bruto)
    return VersionInputs(
        build_run_ids=tuple(documento.get("build_run_ids", ())),
        quality_run_ids=tuple(documento.get("quality_run_ids", ())),
        build_output_fingerprints=tuple(
            ContentHash(f) for f in documento.get("build_output_fingerprints", ())
        ),
        quality_policy_versions=tuple(
            _para_versao_de_politica(v) for v in documento.get("quality_policy_versions", ())
        ),
        quality_policy_fingerprints=tuple(
            ContentHash(f) for f in documento.get("quality_policy_fingerprints", ())
        ),
        build_policy_versions=tuple(
            _para_versao_de_politica(v) for v in documento.get("build_policy_versions", ())
        ),
        build_policy_fingerprints=tuple(
            ContentHash(f) for f in documento.get("build_policy_fingerprints", ())
        ),
        fusion_run_ids=tuple(documento.get("fusion_run_ids", ())),
        resolution_run_ids=tuple(documento.get("resolution_run_ids", ())),
    )


def _para_versao_de_politica(texto: str) -> PolicyVersion:
    maior, _, menor = texto.removeprefix("v").partition(".")
    return PolicyVersion(major=int(maior), minor=int(menor or 0))


def _para_membro(linha: Any) -> CorpusMember:
    return CorpusMember(
        match_id=MatchId(linha["match_id"]),
        competition=CompetitionCode(linha["competition_code"]),
        competition_id=CompetitionId(linha["competition_id"]),
        season_label=linha["season_label"],
        season_id=SeasonId(linha["season_id"]),
        included_families=tuple(CoverageFamily(f) for f in linha["included_families"]),
        contributions=tuple(
            BuildContribution(
                build_run_id=str(c["build_run_id"]),
                quality_assessment_id=str(c["quality_assessment_id"]),
                included_families=tuple(CoverageFamily(f) for f in c["included_families"]),
            )
            for c in _contribuicoes(linha["contributions"])
        ),
        content_fingerprint=ContentHash(linha["content_fingerprint"]),
    )


def _contribuicoes(bruto: Any) -> list[dict[str, Any]]:
    if isinstance(bruto, str):
        carregado: Any = json.loads(bruto)
        return list(carregado)
    return list(bruto or [])


def _para_fatos(
    linha: Any,
    *,
    lineups: tuple[Lineup, ...],
    odds: tuple[CanonicalOddsObservation, ...],
) -> MatchCorpusFacts:
    familias = tuple(CoverageFamily(f) for f in linha["included_families"])
    partida = Match(
        id=MatchId(linha["match_id"]),
        competition_id=CompetitionId(linha["competition_id"]),
        season_id=SeasonId(linha["season_id"]),
        regime=CompetitionRegime(
            code=RegimeCode(linha["regime_code"]),
            effective_from=instant(linha["regime_from"]),
            effective_to=(None if linha["regime_to"] is None else instant(linha["regime_to"])),
            regulation_version=linha["regulation_version"],
        ),
        stage=Stage(
            type=StageType(linha["stage_type"]),
            round_number=linha["round_number"],
            group_label=linha["group_label"],
        ),
        home_team_id=TeamId(linha["home_team_id"]),
        away_team_id=TeamId(linha["away_team_id"]),
        scheduled_kickoff=instant(linha["scheduled_kickoff"]),
        lifecycle=MatchLifecycle(linha["lifecycle"]),
        actual_kickoff=(
            None if linha["actual_kickoff"] is None else instant(linha["actual_kickoff"])
        ),
        venue=None if linha["venue_name"] is None else Venue(name=linha["venue_name"]),
        neutral_venue=linha["neutral_venue"],
    )
    return MatchCorpusFacts(
        match=partida,
        competition=CompetitionCode(linha["competition_code"]),
        season_label=linha["season_label"],
        included_families=familias,
        build_run_id=str(linha["build_run_id"]),
        quality_assessment_id=str(linha["quality_assessment_id"]),
        result=_para_resultado(linha),
        lineups=lineups if CoverageFamily.LINEUP in familias else (),
        odds=odds if CoverageFamily.ODDS in familias else (),
    )


def _para_resultado(linha: Any) -> MatchResult | None:
    if linha["regular_home"] is None:
        return None
    return MatchResult(
        regular_time=Score(home=linha["regular_home"], away=linha["regular_away"]),
        extra_time=(
            None
            if linha["extra_home"] is None
            else Score(home=linha["extra_home"], away=linha["extra_away"])
        ),
        penalties=(
            None
            if linha["penalties_home"] is None
            else Score(home=linha["penalties_home"], away=linha["penalties_away"])
        ),
    )


def _para_entrada(linha: Any) -> LineupEntry:
    return LineupEntry(
        player_id=PlayerId(linha["player_id"]),
        status=LineupStatus(linha["status"]),
        shirt_number=linha["shirt_number"],
        position=None if linha["position"] is None else Position(linha["position"]),
        captain=linha["captain"],
    )


def _para_formacao(bruto: str | None) -> Any:
    if not bruto:
        return None
    from sports_intelligence.domain.matches.lineup import FormationLabel

    return FormationLabel(bruto)


def _para_odd(linha: Any) -> CanonicalOddsObservation:
    return CanonicalOddsObservation(
        match_id=MatchId(linha["match_id"]),
        bookmaker=BookmakerRef(code=linha["bookmaker"]),
        market=OddsMarket(linha["market"]),
        selection=OddsSelection(linha["selection"]),
        decimal_odds=Decimal(str(linha["decimal_odds"])),
        provenance=DataProvenance(
            source_type=SourceType.OPEN_DATA,
            provider_id=(ProviderId(linha["provider_id"]) if linha["provider_id"] else None),
            source_record_id=linha["record_ref"] or None,
            # OS CARIMBOS DE PIPELINE SÃO O `recorded_at` DA LINHA — quando
            # NÓS gravamos —, e não uma tentativa de reconstruir quando a
            # fonte observou. O que a fonte declarou (ou não) sobre isso vive
            # em `observed_at`, logo abaixo, e continua `None` quando ela
            # calou. Misturar os dois faria a nossa leitura passar por
            # observação da casa (§44).
            times=ObservationTimes.at_once(instant(linha["recorded_at"])),
            license_class=LicenseClass(linha["license_class"]),
        ),
        line=None if linha["line"] is None else Decimal(str(linha["line"])),
        observed_at=(None if linha["observed_at"] is None else instant(linha["observed_at"])),
    )


def _para_manifesto(bruto: Any) -> HistoricalCanonicalManifest:
    """Reconstrói o manifesto a partir do documento gravado.

    O DOCUMENTO É A FONTE E NÃO AS COLUNAS. As colunas existem para consultar
    — impressão, schema, chave —; reconstruir a partir delas exigiria manter
    duas representações em dia, e a segunda divergiria no primeiro campo novo.
    """
    documento = _json(bruto)
    return HistoricalCanonicalManifest(
        id=documento["id"],
        schema_version=documento["schema_version"],
        dataset_id=documento["dataset_id"],
        dataset_name=documento["dataset_name"],
        dataset_version=_para_versao_de_dataset(documento["dataset_version"]),
        dataset_version_id=documento["dataset_version_id"],
        scope=_para_escopo(
            documento["scope"], documento["scope"].get("usage", UsageScope.RESEARCH.value)
        ),
        inputs=_para_entradas(documento["inputs"]),
        counts=MembershipCounts(
            matches=documento["counts"]["matches"],
            by_family=dict(documento["counts"].get("by_family", {})),
            by_partition=dict(documento["counts"].get("by_partition", {})),
        ),
        coverage=tuple(
            FamilyCoverageSummary(
                family=c["family"],
                state=c["state"],
                matches_with_data=c.get("matches_with_data", 0),
                matches_total=c.get("matches_total", 0),
                available_total=c.get("available_total", 0),
                expected_total=c.get("expected_total"),
            )
            for c in documento.get("coverage", ())
        ),
        quality=QualitySummary(**documento.get("quality", {})),
        license=LicenseSummary(
            usage_scope=documento["license"]["usage_scope"],
            licenses_present=tuple(documento["license"].get("licenses_present", ())),
            independent_support=tuple(documento["license"].get("independent_support", ())),
            families_included=tuple(documento["license"].get("families_included", ())),
            families_excluded=tuple(documento["license"].get("families_excluded", ())),
            exclusion_reasons=dict(documento["license"].get("exclusion_reasons", {})),
            exclusion_licenses=dict(documento["license"].get("exclusion_licenses", {})),
            requires_attribution=documento["license"].get("requires_attribution", False),
        ),
        issues=IssueSummary(
            by_code=dict(documento.get("issues", {}).get("by_code", {})),
            by_severity=dict(documento.get("issues", {}).get("by_severity", {})),
            records_skipped=documento.get("issues", {}).get("records_skipped", 0),
            records_review_required=documento.get("issues", {}).get("records_review_required", 0),
            families_excluded=documento.get("issues", {}).get("families_excluded", 0),
            examples=tuple(documento.get("issues", {}).get("examples", ())),
        ),
        corpus_fingerprint=ContentHash(documento["corpus_fingerprint"]),
        created_at=instant(_parse(documento["created_at"])),
        fingerprint_algorithm=documento["fingerprint_algorithm"],
        fingerprint_schema_version=documento["fingerprint_schema_version"],
    )


def _para_versao_de_dataset(texto: str) -> DatasetVersion:
    """`v1.0` → `DatasetVersion(1, 0)`.

    O PREFIXO `v` VEM DO `__str__` DE `Version` e precisa ser removido aqui —
    ele é a forma de EXIBIÇÃO, e reaproveitá-la para serialização sem inverter
    o mesmo prefixo é o defeito clássico do ida-e-volta.
    """
    maior, _, menor = texto.removeprefix("v").partition(".")
    return DatasetVersion(major=int(maior), minor=int(menor or 0))


def _parse(texto: str) -> Any:
    from datetime import datetime

    return datetime.fromisoformat(texto)


def _json(bruto: Any) -> dict[str, Any]:
    if isinstance(bruto, str):
        carregado: Any = json.loads(bruto)
        return dict(carregado)
    return dict(bruto or {})
