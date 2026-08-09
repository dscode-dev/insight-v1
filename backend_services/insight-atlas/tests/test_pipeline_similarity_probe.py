"""Regression: the online similarity probe must actually reach the
OracleSimilarityDetector.

`TrendInputs` is a frozen dataclass. The pipeline used to do
`inputs.similarity = await probe.probe(inputs)`, which raises
FrozenInstanceError — a subclass of AttributeError, therefore caught by
the broad `except Exception` right below it and logged as a probe
failure. Net effect in production: similarity was ALWAYS None,
OracleSimilarityDetector returned [] on its first line, and
historical_similarity / historical_pattern were NEVER emitted — while
the pgvector query was still executed and paid for on every tick.

No test constructed the pipeline WITH a `similarity_probe`, which is
exactly why this survived. These do.
"""

from __future__ import annotations

import os
import tempfile
from uuid import uuid4

import fakeredis.aioredis
import pytest

import atlas.registry.models  # noqa: F401
from atlas.event_aggregation import InMemoryAggregationStore
from atlas.registry import build_engine, build_session_factory
from atlas.registry.base import Base
from atlas.similarity.contracts import (
    SimilarityConfidence,
    SimilarityFilters,
    SimilarityMatch,
    SimilaritySearchResult,
)
from atlas.trends import (
    PublishScoreEngine,
    TrendCorrelationEngine,
    TrendEngine,
    TrendIntelligencePipeline,
    TrendLifecycleEngine,
    TrendLifecycleRepository,
    TrendPublisher,
    TrendRepository,
    TrendType,
)
from atlas.trends.correlation import InMemoryRecentTrendStore
from atlas.trends.correlation.repository import CorrelatedTrendRepository
from atlas.trends.models import TrendInputs

EV = "atlas-memory-embedding-v1"
FSV = "feature_schema_v2"


def _search_result() -> SimilaritySearchResult:
    matches = [
        SimilarityMatch(
            vector_id=uuid4(),
            match_id=f"m{i}",
            similarity=round(0.92 - 0.01 * i, 6),
            distance=round(1 - (0.92 - 0.01 * i), 6),
            embedding_version=EV,
            feature_schema_version=FSV,
            competition="Serie A",
            season="2024",
        )
        for i in range(5)
    ]
    sims = [m.similarity for m in matches]
    return SimilaritySearchResult(
        matches=matches,
        confidence=SimilarityConfidence(
            similarity_score=round(sum(sims) / len(sims), 6),
            confidence=0.85,
            neighbor_count=len(matches),
            minimum_neighbors=3,
            average_distance=0.1,
            distance_spread=0.02,
            neighbor_agreement=0.9,
            reasons=[],
        ),
        filters=SimilarityFilters(
            embedding_version=EV,
            feature_schema_version=FSV,
            competition="Serie A",
            season="2024",
        ),
        top_k=25,
        minimum_similarity=0.72,
    )


class _FakeProbe:
    """Stands in for OnlineSimilarityProbe (no pgvector needed)."""

    def __init__(self, result):
        self._result = result
        self.calls = 0

    async def probe(self, inputs):
        self.calls += 1
        return self._result


class _BoomProbe:
    async def probe(self, inputs):
        raise RuntimeError("pgvector unreachable")


class _DatabaseErrorProbe:
    """The realistic outage: SQLAlchemy errors derive straight from
    Exception and match none of OSError/RuntimeError/ValueError/
    TimeoutError. A narrowed except clause let these escape and kill the
    whole tick — the exact failure probe isolation exists to prevent."""

    async def probe(self, inputs):
        from sqlalchemy.exc import OperationalError

        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


@pytest.fixture
async def stack():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    for tbl in Base.metadata.tables.values():
        tbl.schema = None
    engine = build_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = build_session_factory(engine)
    redis = fakeredis.aioredis.FakeRedis()

    def _build(probe):
        return TrendIntelligencePipeline(
            engine=TrendEngine(cooldown_store=None),
            lifecycle_engine=TrendLifecycleEngine(),
            lifecycle_repository=TrendLifecycleRepository(sf),
            correlation_engine=TrendCorrelationEngine(
                InMemoryRecentTrendStore(), cooldown_store=InMemoryAggregationStore()
            ),
            correlation_repository=CorrelatedTrendRepository(sf),
            scoring_engine=PublishScoreEngine(),
            trend_repository=TrendRepository(sf),
            publisher=TrendPublisher(redis, stream="insight:stream:trends"),
            similarity_probe=probe,
        )

    try:
        yield _build
    finally:
        await redis.aclose()
        await engine.dispose()
        try:
            os.unlink(path)
        except OSError:
            pass


async def test_probe_result_reaches_oracle_detector(stack) -> None:
    """The core regression: a healthy probe must produce a
    historical_similarity trend. Before the fix this emitted nothing."""
    probe = _FakeProbe(_search_result())
    pipeline = stack(probe)

    result = await pipeline.process(TrendInputs(canonical_match_id=uuid4()))

    assert probe.calls == 1
    emitted = {t.trend_type for t in result.trends}
    assert TrendType.historical_similarity in emitted, (
        f"Oracle produced nothing from a healthy probe; got {emitted}"
    )


async def test_probe_failure_is_isolated_and_detection_continues(stack) -> None:
    """A real infrastructure failure must still be swallowed — the fix
    narrowed the except, it did not remove probe isolation."""
    pipeline = stack(_BoomProbe())

    result = await pipeline.process(TrendInputs(canonical_match_id=uuid4()))

    assert TrendType.historical_similarity not in {t.trend_type for t in result.trends}


async def test_database_outage_does_not_kill_the_tick(stack) -> None:
    """Regression guard for the isolation clause itself: a real
    SQLAlchemy error must be swallowed like any other probe failure, and
    detection must still complete."""
    pipeline = stack(_DatabaseErrorProbe())

    result = await pipeline.process(TrendInputs(canonical_match_id=uuid4()))

    assert TrendType.historical_similarity not in {t.trend_type for t in result.trends}
    assert result is not None  # the tick completed rather than raising


async def test_caller_supplied_similarity_is_not_overwritten(stack) -> None:
    """When inputs already carry similarity, the probe must not run."""
    probe = _FakeProbe(_search_result())
    pipeline = stack(probe)

    await pipeline.process(
        TrendInputs(canonical_match_id=uuid4(), similarity=_search_result())
    )

    assert probe.calls == 0
