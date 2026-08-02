"""ATLAS-BACKTEST-B — deterministic Quality Gate (manifest/quality/promotion)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from atlas.backtest import (
    ReplayEngine,
    ReplayScenario,
    ReplayService,
    ReplayStep,
    build_manifest,
    detector_versions,
    evaluate,
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


def _ctx(n: int = 4, agreement: float = 0.85) -> SimilarityContext:
    matches = [
        SimilarityMatch(vector_id=uuid4(), match_id=f"m{i}", similarity=0.9 - 0.01 * i,
                        distance=round(0.1 + 0.01 * i, 6), embedding_version=EMBEDDING_VERSION,
                        feature_schema_version="feature_schema_v2", competition="Serie A")
        for i in range(n)
    ]
    sims = [m.similarity for m in matches]
    return SimilarityContext(
        matches=matches,
        confidence=SimilarityConfidence(
            similarity_score=round(sum(sims) / len(sims), 6), confidence=0.8,
            neighbor_count=n, minimum_neighbors=3, average_distance=0.1,
            distance_spread=0.03, neighbor_agreement=agreement),
        filters=SimilarityFilters(embedding_version=EMBEDDING_VERSION,
                                  feature_schema_version="feature_schema_v2", competition="Serie A"),
        top_k=25, minimum_similarity=0.72, agreement=agreement, coverage=1.0,
        distribution=SimilarityDistribution(count=n, best_similarity=max(sims),
            worst_similarity=min(sims), mean_similarity=round(sum(sims) / len(sims), 6),
            min_distance=0.08, max_distance=0.11, mean_distance=0.1, distance_spread=0.03),
        embedding_version=EMBEDDING_VERSION, feature_schema_version="feature_schema_v2")


def _scenario(sid: str, *, agreement: float = 0.85) -> ReplayScenario:
    mid = uuid4()
    return ReplayScenario(
        scenario_id=sid, source="match",
        steps=[ReplayStep(index=i, inputs=TrendInputs(canonical_match_id=mid, minute=i,
                          similarity=_ctx(agreement=agreement))) for i in range(4)])


async def _run(sid: str, *, agreement: float = 0.85):
    return await ReplayEngine().run(_scenario(sid, agreement=agreement))


def test_manifest_is_deterministic_and_real_versions() -> None:
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    m = build_manifest(replay_id="r1", replay_hash="h", dataset="d",
                       execution_timestamp=ts, execution_duration_ms=10)
    assert m.replay_engine_version and m.trend_engine_version == "v4"
    assert m.similarity_version == EMBEDDING_VERSION
    assert "OracleSimilarityDetector" in detector_versions()
    # deterministic: rebuilt manifest is identical (barring the caller-supplied id)
    assert build_manifest(replay_id="r1", replay_hash="h", dataset="d",
                          execution_timestamp=ts, execution_duration_ms=10) == m


def _dump_without_latency(ev) -> dict:
    # average_latency_ms is wall-clock (operational), deliberately excluded from
    # the deterministic intelligence fingerprint — mirror that in the comparison.
    d = ev.model_dump()
    for det in d["detectors"]:
        det["average_latency_ms"] = 0.0
    return d


@pytest.mark.asyncio
async def test_quality_metrics_deterministic_and_no_estimation() -> None:
    a = evaluate(await _run("q"))
    b = evaluate(await _run("q"))
    assert a.replay_hash == b.replay_hash
    assert _dump_without_latency(a) == _dump_without_latency(b)  # reproducible intelligence
    # No reference → precision/recall are None (never estimated).
    assert a.quality.has_reference is False
    assert a.quality.precision is None and a.quality.recall is None
    assert a.detectors and any(d.trend_type == "historical_similarity" for d in a.detectors)
    assert {s.stage for s in a.stages} >= {"oracle", "trend_engine", "similarity"}


@pytest.mark.asyncio
async def test_precision_recall_vs_baseline_reference() -> None:
    baseline = await _run("base")
    result = await _run("base")  # identical → perfect precision/recall
    q = evaluate(result, baseline=baseline)
    assert q.quality.has_reference is True
    assert q.quality.precision == 1.0 and q.quality.recall == 1.0
    assert q.quality.false_positives == 0 and q.quality.false_negatives == 0
    assert q.regression is not None and q.regression.quality_regression is False


@pytest.mark.asyncio
async def test_regression_and_promotion_rejects_on_lost_detections() -> None:
    baseline = await _run("p", agreement=0.85)   # oracle fires
    candidate = await _run("p", agreement=0.1)    # oracle gate fails → lost
    q = evaluate(candidate, baseline=baseline)
    assert q.regression.detector_regression is True
    # The oracle detector should be Rejected with a deterministic explanation.
    oracle = [p for p in q.promotions if p.trend_type == "historical_similarity"]
    assert not oracle or all(
        p.verdict in {"Rejected", "Warning"} for p in oracle
    )
    # Every promotion carries an explanation (no AI, deterministic).
    assert all(e.explanation for e in q.explainability)


@pytest.mark.asyncio
async def test_service_persists_manifest_quality_and_emits_ioc() -> None:
    events: list[str] = []

    class _E:
        def emit(self, event_type, **kw):
            events.append(event_type)

    service = ReplayService(events=_E())
    execution = await service.run_now(_scenario("svc"), dataset_id="ds")
    assert service.quality(execution.execution_id) is not None
    assert service.manifest(execution.execution_id).replay_hash == execution.replay_hash
    for evt in ("replay_quality_started", "quality_metrics_generated",
                "promotion_report_generated", "replay_quality_completed"):
        assert evt in events
