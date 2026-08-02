"""Training pipeline — orchestrates one training job per family.

Caller hands the pipeline a feature matrix (and optionally labels).
The pipeline:
  1. Validates shape against the canonical feature schema.
  2. Trains the requested family.
  3. Computes basic train-time metrics.
  4. Persists the artifact to disk and registers the version in Postgres.

The pipeline is intentionally synchronous-in-thread; the worker layer
runs it via `asyncio.to_thread()` so the event loop stays unblocked.
This makes scaling out to a K8s Job a one-line change later.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import numpy as np

from atlas.features.definitions import FEATURE_NAMES
from atlas.models import (
    AnomalyModel,
    ContextualClassifierModel,
    ClusterModel,
    DensityClusterModel,
    ContextualRankerModel,
    SimilarityIndex,
)
from atlas.models.artifacts import save_artifact
from atlas.models.classifier import bootstrap_labels
from atlas.models.ranker import bootstrap_relevance
from atlas.historical.dataset import HistoricalDataset
from atlas.registry import ModelFamily, ModelRegistry, ModelVersion
from atlas.registry.models import LabelSource

logger = logging.getLogger(__name__)


@dataclass
class TrainingResult:
    family: ModelFamily
    version: ModelVersion | None
    succeeded: bool
    sample_count: int
    metrics: dict[str, Any]
    duration_seconds: float
    error: str = ""


class TrainingPipeline:
    def __init__(
        self,
        *,
        registry: ModelRegistry,
        artifact_dir: str,
        feature_schema_version: int,
    ) -> None:
        self._registry = registry
        self._artifact_dir = artifact_dir
        self._schema = feature_schema_version

    async def train(
        self,
        family: ModelFamily,
        X: np.ndarray,
        *,
        y: np.ndarray | None = None,
        sample_ids: list[UUID] | None = None,
        promote: bool = True,
        label_source: LabelSource | None = None,
        dataset_version: str = "",
        historical_window: dict | None = None,
        dataset_metadata: dict | None = None,
    ) -> TrainingResult:
        """Sprint 0 — `label_source` makes the label lineage visible on
        the persisted ModelVersion. When unset, the pipeline infers:
          * unsupervised families (anomaly/cluster/density) → none
          * supervised families (classifier/ranker) where `y` is None
            → bootstrap_rule (the rule-based bootstrap fires)
          * supervised families where `y` was supplied → human_curated
        Callers wiring a historical-outcome labeller should pass
        `LabelSource.historical_outcome` explicitly to override.
        """
        if X.ndim != 2 or X.shape[1] != len(FEATURE_NAMES):
            return TrainingResult(
                family=family,
                version=None,
                succeeded=False,
                sample_count=int(X.shape[0]) if X.ndim == 2 else 0,
                metrics={},
                duration_seconds=0.0,
                error="invalid_feature_schema",
            )

        # Resolve label_source from caller / inferred default.
        resolved_label_source = (
            label_source
            if label_source is not None
            else _default_label_source(family, y)
        )

        run = await self._registry.start_run(
            family=family, feature_schema_version=self._schema
        )
        t0 = time.time()
        version: ModelVersion | None = None
        succeeded = False
        metrics: dict[str, Any] = {}
        err = ""
        try:
            state, importance, train_metric = self._train_family(
                family, X, y, sample_ids=sample_ids
            )
            version_id = uuid4()
            artifact_path = save_artifact(
                self._artifact_dir,
                family=family.value,
                version_id=str(version_id),
                payload=state,
            )
            metrics = {
                "train_metric": train_metric,
                "n_samples": int(X.shape[0]),
                "label_source": resolved_label_source.value,
                "dataset_version": dataset_version,
                "historical_window": historical_window or {},
                "dataset_metadata": dataset_metadata or {},
            }
            semver = f"0.{int(time.time())}.0"
            version = await self._registry.register(
                family=family,
                semver=semver,
                artifact_path=artifact_path,
                feature_schema_version=self._schema,
                train_metric=train_metric,
                feature_importance=importance,
                label_source=resolved_label_source,
                dataset_version=dataset_version,
                historical_window=historical_window,
                dataset_metadata=dataset_metadata,
            )
            if promote and version is not None:
                promoted = await self._registry.promote(version.id)
                if promoted is not None:
                    version = promoted
            succeeded = True
        except Exception as exc:
            logger.exception("training_failed", extra={"family": family.value})
            err = f"{type(exc).__name__}: {exc}"[:2048]
        finally:
            await self._registry.finish_run(
                run.id,
                version_id=version.id if version else None,
                succeeded=succeeded,
                sample_count=int(X.shape[0]),
                metrics=metrics,
                error=err,
            )
        return TrainingResult(
            family=family,
            version=version,
            succeeded=succeeded,
            sample_count=int(X.shape[0]),
            metrics=metrics,
            duration_seconds=time.time() - t0,
            error=err,
        )

    # ------------------------------------------------------------------

    async def train_historical(
        self,
        family: ModelFamily,
        dataset: HistoricalDataset,
        *,
        promote: bool = False,
    ) -> TrainingResult:
        """Train from a real historical dataset.

        Historical versions are staged by default. Promotion remains an
        explicit operator action after validation review.
        """
        X = dataset.train.X
        y: np.ndarray | None = None
        label_source = LabelSource.none
        if family is ModelFamily.classifier:
            y = dataset.train.classifier_y
            if y is None:
                return TrainingResult(
                    family=family,
                    version=None,
                    succeeded=False,
                    sample_count=int(X.shape[0]),
                    metrics={},
                    duration_seconds=0.0,
                    error="historical_classifier_labels_missing",
                )
            label_source = LabelSource.historical_outcome
        elif family is ModelFamily.ranker:
            y = dataset.train.relevance_y
            if y is None:
                return TrainingResult(
                    family=family,
                    version=None,
                    succeeded=False,
                    sample_count=int(X.shape[0]),
                    metrics={},
                    duration_seconds=0.0,
                    error="historical_ranker_relevance_missing",
                )
            label_source = LabelSource.historical_outcome

        metadata = dict(dataset.metadata)
        metadata.update(
            {
                "validation_sample_count": len(dataset.validation.rows),
                "test_sample_count": len(dataset.test.rows),
                "provider_composition": dataset.provider_composition,
            }
        )
        return await self.train(
            family,
            X,
            y=y,
            sample_ids=dataset.train.match_ids,
            promote=promote,
            label_source=label_source,
            dataset_version=dataset.version,
            historical_window={
                "start": dataset.historical_window[0].isoformat(),
                "end": dataset.historical_window[1].isoformat(),
            },
            dataset_metadata=metadata,
        )

    def _train_family(
        self,
        family: ModelFamily,
        X: np.ndarray,
        y: np.ndarray | None,
        *,
        sample_ids: list[UUID] | None = None,
    ) -> tuple[dict, dict[str, float], float | None]:
        if family is ModelFamily.anomaly:
            m = AnomalyModel.train(X)
            return m.to_state(), self._uniform_importance(), None

        if family is ModelFamily.cluster:
            m = ClusterModel.train(X, n_clusters=4)
            return m.to_state(), self._uniform_importance(), None

        if family is ModelFamily.density:
            m = DensityClusterModel.train(X)
            return m.to_state(), self._uniform_importance(), None

        if family is ModelFamily.classifier:
            labels = y if y is not None else bootstrap_labels(X)
            m = ContextualClassifierModel.train(X, labels)
            # Accuracy on training set is a sanity check, not a validation
            # metric. Real validation belongs in a holdout job (Stage 8+).
            preds = m.booster.predict(X)
            acc = float((preds == labels).mean())
            return m.to_state(), dict(m.feature_importance), acc

        if family is ModelFamily.ranker:
            relevance = y if y is not None else bootstrap_relevance(X)
            m = ContextualRankerModel.train(X, relevance)
            # No public metric we can compute cheaply here; report
            # importance entropy as a proxy for the model having learned
            # something.
            ent = _entropy(list(m.feature_importance.values()))
            return m.to_state(), dict(m.feature_importance), ent

        if family is ModelFamily.similarity:
            if sample_ids is None or len(sample_ids) != X.shape[0]:
                raise ValueError("similarity training requires one match_id per row")
            m = SimilarityIndex.build(list(zip(sample_ids, X.tolist())))
            return m.to_state(), self._uniform_importance(), float(X.shape[0])

        raise ValueError(f"unsupported family: {family}")

    def _uniform_importance(self) -> dict[str, float]:
        n = len(FEATURE_NAMES)
        return {name: 1.0 / n for name in FEATURE_NAMES}


def _entropy(values: list[float]) -> float:
    import math

    total = sum(v for v in values if v > 0)
    if total <= 0:
        return 0.0
    out = 0.0
    for v in values:
        if v <= 0:
            continue
        p = v / total
        out -= p * math.log(p)
    return out


def _default_label_source(
    family: ModelFamily, y: np.ndarray | None
) -> LabelSource:
    """Inference rule when the caller didn't pass label_source.

    Unsupervised families don't have labels → `none`. Supervised
    families fall back to `bootstrap_rule` when `y` is None (the rule-
    based bootstrap fires inside _train_family) or `human_curated` when
    `y` is supplied — caller should override to `historical_outcome`
    when the labels came from match outcomes rather than analyst tags.
    """
    if family in (
        ModelFamily.anomaly,
        ModelFamily.cluster,
        ModelFamily.density,
        ModelFamily.similarity,
    ):
        return LabelSource.none
    if y is None:
        return LabelSource.bootstrap_rule
    return LabelSource.human_curated
