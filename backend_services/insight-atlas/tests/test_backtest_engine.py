"""ATLAS-BACKTEST-A — deterministic replay over the REAL TrendEngine (no infra)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from atlas.backtest import (
    ReplayEngine,
    ReplayScenario,
    ReplayService,
    ReplayStep,
    diff_replays,
)
from atlas.similarity.contracts import (
    SimilarityConfidence,
    SimilarityContext,
    SimilarityDistribution,
    SimilarityFilters,
    SimilarityMatch,
)
from atlas.trends.models import TrendInputs
from atlas.vector_memory.contracts import EMBEDDING_VERSION


def _match(mid: str, sim: float) -> SimilarityMatch:
    return SimilarityMatch(
        vector_id=uuid4(), match_id=mid, similarity=sim, distance=round(1 - sim, 6),
        embedding_version=EMBEDDING_VERSION, feature_schema_version="feature_schema_v2",
        competition="Serie A",
    )


def _context(n: int = 4, agreement: float = 0.85) -> SimilarityContext:
    # The neighbourhood must MATCH the requested agreement: the Oracle
    # detector re-scores the set it accepted (and SimilarityService
    # always derives confidence from these same matches), so a tight
    # cluster paired with a low `agreement` field is a state production
    # cannot produce. Low agreement = genuinely wide distance spread.
    matches = (
        [_match(f"m{i}", 0.92 - 0.01 * i) for i in range(n)]
        if agreement >= 0.4
        else [_match(f"m{i}", 0.95 if i < n // 2 else 0.50) for i in range(n)]
    )
    sims = [m.similarity for m in matches]
    return SimilarityContext(
        matches=matches,
        confidence=SimilarityConfidence(
            similarity_score=round(sum(sims) / len(sims), 6), confidence=0.8,
            neighbor_count=n, minimum_neighbors=3, average_distance=0.1,
            distance_spread=0.03, neighbor_agreement=agreement,
        ),
        filters=SimilarityFilters(
            embedding_version=EMBEDDING_VERSION,
            feature_schema_version="feature_schema_v2", competition="Serie A",
        ),
        top_k=25, minimum_similarity=0.72, agreement=agreement, coverage=1.0,
        distribution=SimilarityDistribution(
            count=n, best_similarity=max(sims), worst_similarity=min(sims),
            mean_similarity=round(sum(sims) / len(sims), 6), min_distance=0.08,
            max_distance=0.11, mean_distance=0.1, distance_spread=0.03,
        ),
        embedding_version=EMBEDDING_VERSION, feature_schema_version="feature_schema_v2",
    )


def _scenario(scenario_id: str = "s1", *, agreement: float = 0.85) -> ReplayScenario:
    mid = uuid4()
    steps = [
        ReplayStep(index=i, label=f"tick{i}",
                   inputs=TrendInputs(canonical_match_id=mid, minute=i,
                                      similarity=_context(agreement=agreement)))
        for i in range(3)
    ]
    return ReplayScenario(scenario_id=scenario_id, source="match", steps=steps)


@pytest.mark.asyncio
async def test_replay_runs_real_pipeline_and_emits_oracle_similarity() -> None:
    result = await ReplayEngine().run(_scenario())
    assert result.steps_executed == 3
    types = {t.trend_type for t in result.trends}
    assert "historical_similarity" in types  # real OracleSimilarityDetector fired
    # generic detector metrics exist for the oracle agent
    oracle = [d for d in result.detectors if d.trend_type == "historical_similarity"]
    assert oracle and oracle[0].positive_detections == 3
    assert oracle[0].historical_coverage == 1.0
    assert result.similarity and result.similarity[0].neighbor_count == 4


@pytest.mark.asyncio
async def test_replay_is_deterministic() -> None:
    a = await ReplayEngine().run(_scenario("det"))
    b = await ReplayEngine().run(_scenario("det"))
    assert a.deterministic_hash == b.deterministic_hash
    assert [t.model_dump() for t in a.trends] == [t.model_dump() for t in b.trends]


@pytest.mark.asyncio
async def test_regression_detects_no_change_when_identical() -> None:
    a = await ReplayEngine().run(_scenario("r"))
    b = await ReplayEngine().run(_scenario("r"))
    diff = diff_replays(a, b)
    assert diff.identical and not diff.new_detections and not diff.lost_detections


@pytest.mark.asyncio
async def test_regression_detects_lost_detection() -> None:
    baseline = await ReplayEngine().run(_scenario("b", agreement=0.85))  # oracle fires
    # Low agreement fails the Oracle gate → detections lost.
    candidate = await ReplayEngine().run(_scenario("b", agreement=0.1))
    diff = diff_replays(baseline, candidate)
    assert not diff.identical
    assert diff.lost_detections
    assert any(d["kind"] == "lost" for d in diff.trend_changes)


@pytest.mark.asyncio
async def test_replay_service_is_async_and_records_history() -> None:
    service = ReplayService()
    execution = await service.run_now(_scenario("svc"))
    assert execution.status == "completed" and execution.result is not None
    assert service.status(execution.execution_id).status == "completed"
    assert service.history()[0].scenario_id == "svc"


@pytest.mark.asyncio
async def test_quality_metrics_present_and_bounded() -> None:
    result = await ReplayEngine().run(_scenario("q"))
    q = result.quality
    for value in (q.replay_completion, q.pipeline_completion, q.detector_stability,
                  q.similarity_consistency, q.trend_consistency):
        assert 0.0 <= value <= 1.0
    assert q.replay_completion == 1.0
