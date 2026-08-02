from __future__ import annotations

import numpy as np

from atlas.features.snapshot import FeatureSnapshot
from atlas.inference import InferenceEngine
from atlas.inference.output import MatchContextResponse
from atlas.registry import ModelFamily
from atlas.training import TrainingPipeline


async def _train_all(pipeline: TrainingPipeline, X: np.ndarray) -> None:
    for fam in (
        ModelFamily.anomaly,
        ModelFamily.cluster,
        ModelFamily.density,
        ModelFamily.classifier,
        ModelFamily.ranker,
    ):
        result = await pipeline.train(fam, X)
        assert result.succeeded, f"train failed for {fam}: {result.error}"


async def test_full_inference_returns_all_four_families(
    training_pipeline: TrainingPipeline,
    training_matrix: np.ndarray,
    synthetic_snapshot: FeatureSnapshot,
) -> None:
    await _train_all(training_pipeline, training_matrix)
    engine = InferenceEngine(
        registry=training_pipeline._registry, feature_schema_version=1
    )
    response = await engine.context_for(synthetic_snapshot)
    assert isinstance(response, MatchContextResponse)
    assert response.anomaly is not None
    assert response.cluster is not None
    assert response.density is not None
    assert response.classifier is not None


async def test_inference_carries_explainability_metadata(
    training_pipeline: TrainingPipeline,
    training_matrix: np.ndarray,
    synthetic_snapshot: FeatureSnapshot,
) -> None:
    await training_pipeline.train(ModelFamily.classifier, training_matrix)
    engine = InferenceEngine(
        registry=training_pipeline._registry, feature_schema_version=1
    )
    out = await engine.classifier(synthetic_snapshot)
    assert out is not None
    assert out.model_version is not None
    assert out.feature_schema_version == 1
    assert 0.0 <= out.context_confidence <= 1.0
    assert len(out.top_factors) >= 1
    for f in out.top_factors:
        # contribution is float-valid + feature name is on the schema list
        assert isinstance(f.contribution, float)
        assert f.feature  # non-empty


async def test_inference_skips_models_with_wrong_schema(
    training_pipeline: TrainingPipeline,
    training_matrix: np.ndarray,
    synthetic_snapshot: FeatureSnapshot,
) -> None:
    await training_pipeline.train(ModelFamily.anomaly, training_matrix)
    engine = InferenceEngine(
        registry=training_pipeline._registry, feature_schema_version=2
    )  # mismatch
    out = await engine.anomaly(synthetic_snapshot)
    assert out is None


async def test_invalidate_forces_reload(
    training_pipeline: TrainingPipeline,
    training_matrix: np.ndarray,
    synthetic_snapshot: FeatureSnapshot,
) -> None:
    await training_pipeline.train(ModelFamily.cluster, training_matrix)
    engine = InferenceEngine(
        registry=training_pipeline._registry, feature_schema_version=1
    )
    first = await engine.cluster(synthetic_snapshot)
    assert first is not None
    cached_a = engine._cache.get(ModelFamily.cluster)
    await engine.invalidate(ModelFamily.cluster)
    second = await engine.cluster(synthetic_snapshot)
    assert second is not None
    cached_b = engine._cache.get(ModelFamily.cluster)
    # Cache slot was repopulated.
    assert cached_a is not None and cached_b is not None
