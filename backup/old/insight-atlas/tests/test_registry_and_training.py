from __future__ import annotations

import numpy as np

from atlas.registry import ModelFamily, ModelStage
from atlas.training import TrainingPipeline


async def test_training_persists_version_and_promotes(
    training_pipeline: TrainingPipeline, training_matrix: np.ndarray
) -> None:
    result = await training_pipeline.train(ModelFamily.anomaly, training_matrix)
    assert result.succeeded
    assert result.version is not None
    assert result.version.stage == ModelStage.active
    assert result.version.feature_schema_version == 1
    # Artifact path was written to disk.
    import os

    assert os.path.exists(result.version.artifact_path)


async def test_training_classifier_records_metric(
    training_pipeline: TrainingPipeline, training_matrix: np.ndarray
) -> None:
    result = await training_pipeline.train(ModelFamily.classifier, training_matrix)
    assert result.succeeded
    assert result.metrics["n_samples"] == training_matrix.shape[0]
    assert result.metrics.get("train_metric") is not None
    assert 0.0 <= result.metrics["train_metric"] <= 1.0


async def test_training_invalid_schema_returns_error(
    training_pipeline: TrainingPipeline,
) -> None:
    # Wrong column count — pipeline rejects without crashing.
    X = np.zeros((10, 2))
    result = await training_pipeline.train(ModelFamily.anomaly, X)
    assert not result.succeeded
    assert "invalid" in result.error or result.error  # any descriptive error


async def test_promote_replaces_active(
    training_pipeline: TrainingPipeline, training_matrix: np.ndarray
) -> None:
    r1 = await training_pipeline.train(ModelFamily.cluster, training_matrix)
    r2 = await training_pipeline.train(ModelFamily.cluster, training_matrix)
    assert r1.version and r2.version
    # After the second train + auto-promote, r1 must be archived and r2
    # must be active.
    versions = await training_pipeline._registry.list_versions(
        ModelFamily.cluster, limit=10
    )
    by_id = {v.id: v for v in versions}
    assert by_id[r1.version.id].stage == ModelStage.archived
    assert by_id[r2.version.id].stage == ModelStage.active


async def test_registry_get_active_returns_only_active(
    training_pipeline: TrainingPipeline, training_matrix: np.ndarray
) -> None:
    await training_pipeline.train(ModelFamily.classifier, training_matrix)
    active = await training_pipeline._registry.get_active(ModelFamily.classifier)
    assert active is not None
    assert active.stage == ModelStage.active
