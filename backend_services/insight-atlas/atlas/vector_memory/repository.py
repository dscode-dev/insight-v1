"""Async PostgreSQL/pgvector storage for deterministic embeddings."""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.vector_memory.contracts import MemoryEmbedding
from atlas.vector_memory.provenance import compatibility_params


class PgVectorMemoryRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def upsert_many(self, embeddings: list[MemoryEmbedding]) -> int:
        if not embeddings:
            return 0
        statement = text(
            """
            INSERT INTO atlas.atlas_vector_memory (
                vector_id, source_match_id, competition, regime,
                home_team, away_team, behavior, trends, signals,
                market_available, uncertainty, embedding_version,
                embedding, created_at,
                feature_schema_version, signal_catalog_version,
                behavior_catalog_version, season, market_type, match_phase,
                similarity_metadata
            ) VALUES (
                :vector_id, :source_match_id, :competition, :regime,
                :home_team, :away_team, CAST(:behavior AS jsonb),
                CAST(:trends AS jsonb), CAST(:signals AS jsonb),
                :market_available, :uncertainty, :embedding_version,
                CAST(:embedding AS vector), :created_at,
                :feature_schema_version, :signal_catalog_version,
                :behavior_catalog_version, :season, :market_type, :match_phase,
                CAST(:similarity_metadata AS jsonb)
            )
            ON CONFLICT (source_match_id) DO UPDATE SET
                competition = EXCLUDED.competition,
                regime = EXCLUDED.regime,
                home_team = EXCLUDED.home_team,
                away_team = EXCLUDED.away_team,
                behavior = EXCLUDED.behavior,
                trends = EXCLUDED.trends,
                signals = EXCLUDED.signals,
                market_available = EXCLUDED.market_available,
                uncertainty = EXCLUDED.uncertainty,
                embedding_version = EXCLUDED.embedding_version,
                embedding = EXCLUDED.embedding,
                created_at = EXCLUDED.created_at,
                feature_schema_version = EXCLUDED.feature_schema_version,
                signal_catalog_version = EXCLUDED.signal_catalog_version,
                behavior_catalog_version = EXCLUDED.behavior_catalog_version,
                season = EXCLUDED.season,
                market_type = EXCLUDED.market_type,
                match_phase = EXCLUDED.match_phase,
                similarity_metadata = EXCLUDED.similarity_metadata
            """
        )
        async with self._sf() as session:
            await session.execute(
                statement,
                [_params(embedding) for embedding in embeddings],
            )
            await session.commit()
        return len(embeddings)


def _params(embedding: MemoryEmbedding) -> dict:
    return {
        "vector_id": embedding.vector_id,
        "source_match_id": embedding.source_match_id,
        "competition": embedding.competition,
        "regime": embedding.regime.value,
        "home_team": embedding.home_team,
        "away_team": embedding.away_team,
        "behavior": json.dumps(embedding.behavior),
        "trends": json.dumps(embedding.trends),
        "signals": json.dumps(embedding.signals),
        "market_available": embedding.market_available,
        "uncertainty": embedding.uncertainty,
        "embedding_version": embedding.embedding_version,
        "embedding": _vector(embedding.embedding),
        "created_at": embedding.created_at,
        # ATLAS-VECTOR-B compat metadata (canonical constants; season/
        # match_phase stay NULL — not carried by MemoryEmbedding).
        **compatibility_params(
            source="deterministic_vector_memory",
            market_type="match_odds" if embedding.market_available else None,
        ),
    }


def _vector(values: tuple[float, ...]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"

