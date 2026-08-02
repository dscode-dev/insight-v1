"""PostgreSQL persistence and runtime lookup for Explorer intelligence."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.ingestion.contracts import (
    AtlasBehaviorIngest,
    AtlasIngestionBatch,
    AtlasMemoryIngest,
    AtlasSignalIngest,
    AtlasVectorIngest,
)
from atlas.vector_memory.provenance import compatibility_params


class AtlasIngestionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def persist(
        self,
        batch: AtlasIngestionBatch,
        memories: list[AtlasMemoryIngest],
        behaviors: list[AtlasBehaviorIngest],
        vectors: list[AtlasVectorIngest],
        signals: list[AtlasSignalIngest],
        rejections: list[dict[str, Any]],
    ) -> dict[str, int]:
        accepted = len(memories) + len(behaviors) + len(vectors) + len(signals)
        async with self._sf() as session:
            await session.execute(text(
                """
                INSERT INTO atlas.explorer_ingestion_batches (
                    batch_id, generation_id, schema_version, source_system,
                    content_hash, status, accepted_records, rejected_records,
                    rejection_details, created_at
                ) VALUES (
                    :batch_id, :generation_id, :schema_version, :source_system,
                    :content_hash, :status, :accepted, :rejected,
                    CAST(:details AS jsonb), :created_at
                )
                ON CONFLICT (content_hash) DO NOTHING
                """
            ), {
                "batch_id": batch.batch_id,
                "generation_id": batch.generation_id,
                "schema_version": batch.schema_version,
                "source_system": batch.source_system,
                "content_hash": batch.content_hash,
                "status": "partial" if rejections else "completed",
                "accepted": accepted,
                "rejected": len(rejections),
                "details": json.dumps(rejections),
                "created_at": batch.created_at,
            })
            for record in memories:
                await session.execute(text(
                    """
                    INSERT INTO atlas.explorer_memory_snapshots (
                        record_id, batch_id, generation_id, competition,
                        home_team, away_team, observed_at, payload, lineage,
                        content_hash
                    ) VALUES (
                        :record_id, :batch_id, :generation_id, :competition,
                        :home_team, :away_team, :observed_at,
                        CAST(:payload AS jsonb), CAST(:lineage AS jsonb),
                        :content_hash
                    ) ON CONFLICT (content_hash) DO NOTHING
                    """
                ), _base(record, batch.batch_id) | {
                    "home_team": record.home_team,
                    "away_team": record.away_team,
                })
            for record in behaviors:
                await session.execute(text(
                    """
                    INSERT INTO atlas.explorer_behavior_observations (
                        record_id, batch_id, generation_id, competition,
                        behavior, observed_at, payload, lineage, content_hash
                    ) VALUES (
                        :record_id, :batch_id, :generation_id, :competition,
                        :behavior, :observed_at, CAST(:payload AS jsonb),
                        CAST(:lineage AS jsonb), :content_hash
                    ) ON CONFLICT (content_hash) DO NOTHING
                    """
                ), _base(record, batch.batch_id) | {"behavior": record.behavior})
            for record in signals:
                await session.execute(text(
                    """
                    INSERT INTO atlas.explorer_signal_observations (
                        record_id, batch_id, generation_id, competition,
                        signal_family, observed_at, payload, lineage, content_hash
                    ) VALUES (
                        :record_id, :batch_id, :generation_id, :competition,
                        :signal_family, :observed_at, CAST(:payload AS jsonb),
                        CAST(:lineage AS jsonb), :content_hash
                    ) ON CONFLICT (content_hash) DO NOTHING
                    """
                ), _base(record, batch.batch_id) | {
                    "signal_family": record.signal_family,
                })
            for record in vectors:
                await session.execute(text(
                    """
                    INSERT INTO atlas.atlas_vector_memory (
                        vector_id, source_match_id, competition, regime,
                        home_team, away_team, behavior, trends, signals,
                        market_available, uncertainty, embedding_version,
                        embedding, created_at, source_system, generation_id,
                        ingest_batch_id, lineage,
                        feature_schema_version, signal_catalog_version,
                        behavior_catalog_version, season, market_type,
                        match_phase, similarity_metadata
                    ) VALUES (
                        :record_id, :source_match_id, :competition, :regime,
                        :home_team, :away_team, CAST(:behavior AS jsonb),
                        CAST(:trends AS jsonb), CAST(:signals AS jsonb),
                        :market_available, :uncertainty, :embedding_version,
                        CAST(:embedding AS vector), :observed_at,
                        'insight-explorer', :generation_id, :batch_id,
                        CAST(:lineage AS jsonb),
                        :feature_schema_version, :signal_catalog_version,
                        :behavior_catalog_version, :season, :market_type,
                        :match_phase, CAST(:similarity_metadata AS jsonb)
                    )
                    ON CONFLICT (source_match_id) DO UPDATE SET
                        behavior = EXCLUDED.behavior,
                        trends = EXCLUDED.trends,
                        signals = EXCLUDED.signals,
                        uncertainty = EXCLUDED.uncertainty,
                        embedding = EXCLUDED.embedding,
                        source_system = EXCLUDED.source_system,
                        generation_id = EXCLUDED.generation_id,
                        ingest_batch_id = EXCLUDED.ingest_batch_id,
                        lineage = EXCLUDED.lineage,
                        feature_schema_version = EXCLUDED.feature_schema_version,
                        signal_catalog_version = EXCLUDED.signal_catalog_version,
                        behavior_catalog_version = EXCLUDED.behavior_catalog_version,
                        season = EXCLUDED.season,
                        market_type = EXCLUDED.market_type,
                        match_phase = EXCLUDED.match_phase,
                        similarity_metadata = EXCLUDED.similarity_metadata
                    """
                ), _vector(record, batch.batch_id))
            await session.commit()
        return {
            "accepted": accepted,
            "rejected": len(rejections),
            "memories": len(memories),
            "behaviors": len(behaviors),
            "vectors": len(vectors),
            "signals": len(signals),
        }

    async def latest_context(
        self, competition: str, home_team: str, away_team: str, as_of
    ) -> dict[str, Any]:
        params = {
            "competition": competition,
            "home_team": home_team,
            "away_team": away_team,
            "as_of": as_of,
        }
        async with self._sf() as session:
            memory = (await session.execute(text(
                """
                SELECT payload, lineage, generation_id, observed_at
                FROM atlas.explorer_memory_snapshots
                WHERE competition = :competition
                  AND home_team = :home_team AND away_team = :away_team
                  AND observed_at <= :as_of
                ORDER BY observed_at DESC LIMIT 1
                """
            ), params)).mappings().first()
            behaviors = (await session.execute(text(
                """
                SELECT payload, lineage, generation_id, observed_at
                FROM atlas.explorer_behavior_observations
                WHERE competition = :competition
                  AND observed_at <= :as_of
                  AND (
                    payload->>'match_id' = (
                        SELECT payload->>'match_id'
                        FROM atlas.explorer_memory_snapshots
                        WHERE competition = :competition
                          AND home_team = :home_team AND away_team = :away_team
                          AND observed_at <= :as_of
                        ORDER BY observed_at DESC LIMIT 1
                    )
                  )
                ORDER BY observed_at DESC
                """
            ), params)).mappings().all()
            signals = (await session.execute(text(
                """
                SELECT payload, lineage, generation_id, observed_at
                FROM atlas.explorer_signal_observations
                WHERE competition = :competition
                  AND observed_at <= :as_of
                  AND payload->>'home_team' = :home_team
                  AND payload->>'away_team' = :away_team
                ORDER BY observed_at DESC LIMIT 8
                """
            ), params)).mappings().all()
        return {
            "memory": dict(memory) if memory else None,
            "behaviors": [dict(row) for row in behaviors],
            "signals": [dict(row) for row in signals],
        }

    async def status(self) -> dict[str, Any]:
        async with self._sf() as session:
            row = (await session.execute(text(
                """
                SELECT
                  (SELECT count(*) FROM atlas.explorer_ingestion_batches) batches,
                  (SELECT count(*) FROM atlas.explorer_memory_snapshots) memories,
                  (SELECT count(*) FROM atlas.explorer_behavior_observations) behaviors,
                  (SELECT count(*) FROM atlas.explorer_signal_observations) signals,
                  (SELECT count(*) FROM atlas.atlas_vector_memory
                   WHERE source_system = 'insight-explorer') vectors,
                  (SELECT max(ingested_at) FROM atlas.explorer_ingestion_batches) last_ingested_at
                """
            ))).mappings().one()
        return dict(row)


def _base(record, batch_id: UUID) -> dict[str, Any]:
    return {
        "record_id": record.record_id,
        "batch_id": batch_id,
        "generation_id": record.lineage.generation_id,
        "competition": record.competition,
        "observed_at": record.observed_at,
        "payload": json.dumps(record.payload),
        "lineage": record.lineage.model_dump_json(),
        "content_hash": record.content_hash,
    }


def _vector(record: AtlasVectorIngest, batch_id: UUID) -> dict[str, Any]:
    return {
        "record_id": record.record_id,
        "batch_id": batch_id,
        "generation_id": record.lineage.generation_id,
        "source_match_id": record.source_match_id,
        "competition": record.competition,
        "regime": record.regime.value,
        "home_team": record.home_team,
        "away_team": record.away_team,
        "behavior": json.dumps(record.behavior),
        "trends": json.dumps(record.trends),
        "signals": json.dumps(record.signals),
        "market_available": record.market_available,
        "uncertainty": record.uncertainty,
        "embedding_version": record.embedding_version,
        "embedding": "[" + ",".join(f"{v:.8f}" for v in record.embedding) + "]",
        "observed_at": record.observed_at,
        "lineage": record.lineage.model_dump_json(),
        # ATLAS-VECTOR-B compat metadata — Atlas-side canonical constants
        # (does NOT modify the Explorer ingest contract). season/market_type/
        # match_phase stay NULL: not carried by AtlasVectorIngest.
        **compatibility_params(source="insight-explorer"),
    }
