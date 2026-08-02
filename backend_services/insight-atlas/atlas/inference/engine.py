"""Inference engine — loads the active model per family and produces
ContextOutput for a feature snapshot.

The engine is built around three rules from the brief:

  * Inference must NEVER block on the training path.
  * Every output carries explainability metadata.
  * No betting predictions — outputs are descriptive.

Latency budget (p95 < 50ms):
  - Redis hot snapshot fetch ............ ~ 0.5 ms
  - load model (cached after first hit) . ~ 0  ms
  - 4 inferences (parallel) ............. ~ 5–20 ms
  - serialisation ....................... ~ 1 ms

Headlines are pt-BR and intentionally generic. Each model's output goes
through a small renderer that maps `top_factors` to a sentence the
frontend can show without further string work.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from atlas.features.definitions import FEATURE_NAMES
from atlas.features.snapshot import FeatureSnapshot
from atlas.inference.confidence_policy import DEFAULT_POLICY, ConfidencePolicy
from atlas.inference.output import ContextOutput, Factor, MatchContextResponse
from atlas.models import (
    AnomalyModel,
    ContextualClassifierModel,
    ClusterModel,
    DensityClusterModel,
    ContextualRankerModel,
    SimilarityIndex,
)
from atlas.models.artifacts import load_artifact
from atlas.registry import ModelFamily, ModelRegistry, ModelVersion

logger = logging.getLogger(__name__)


# Map a classifier label to a pt-BR headline. The actual sentence stays
# generic and descriptive — never prescriptive.
CLASSIFIER_HEADLINE = {
    "balanced": "Comportamento equilibrado — sem dominância clara",
    "late_pressure": "Padrão de pressão tardia detectado",
    "high_volatility": "Volatilidade de mercado acima do habitual",
    "high_engagement": "Engajamento coletivo elevado",
}


class InferenceEngine:
    """Caches loaded model artifacts in-process. The registry is queried
    once per family and the binary is loaded lazily on first request.

    Reloads happen through `invalidate()` which the API can call after
    a promotion to make the new version live without a process restart.
    """

    def __init__(
        self,
        *,
        registry: ModelRegistry,
        feature_schema_version: int,
        confidence_policy: ConfidencePolicy = DEFAULT_POLICY,
    ) -> None:
        self._registry = registry
        self._schema = feature_schema_version
        self._policy = confidence_policy
        self._cache: dict[ModelFamily, tuple[ModelVersion, Any]] = {}
        self._lock = asyncio.Lock()

    # ---- confidence combination -----------------------------------------

    def _final_confidence(
        self, snapshot: FeatureSnapshot, feature_quality: float
    ) -> float:
        """Wraps the policy call so each family's per-output computation
        is a single line. Catches any policy bug + returns the raw
        model signal as a safe fallback rather than crashing the whole
        inference call."""
        try:
            return self._policy.combine(
                feature_quality=feature_quality,
                source_confidence=snapshot.source_confidence,
                data_confidence=snapshot.data_confidence,
            )
        except Exception:
            logger.exception(
                "confidence_policy_failed",
                extra={"match_id": str(snapshot.match_id)},
            )
            return feature_quality

    # ---- cache control --------------------------------------------------

    async def invalidate(self, family: ModelFamily | None = None) -> None:
        async with self._lock:
            if family is None:
                self._cache.clear()
            else:
                self._cache.pop(family, None)

    async def _get(self, family: ModelFamily) -> tuple[ModelVersion, Any] | None:
        cached = self._cache.get(family)
        if cached is not None:
            return cached
        async with self._lock:
            cached = self._cache.get(family)
            if cached is not None:
                return cached
            version = await self._registry.get_active(family)
            if version is None:
                return None
            if version.feature_schema_version != self._schema:
                logger.warning(
                    "inference_skip_schema_mismatch",
                    extra={
                        "family": family.value,
                        "model_schema": version.feature_schema_version,
                        "current_schema": self._schema,
                    },
                )
                return None
            if not Path(version.artifact_path).exists():
                logger.error(
                    "inference_artifact_missing",
                    extra={"family": family.value, "path": version.artifact_path},
                )
                return None
            state = load_artifact(version.artifact_path)
            wrapper = self._load_wrapper(family, state)
            self._cache[family] = (version, wrapper)
            return (version, wrapper)

    def _load_wrapper(self, family: ModelFamily, state: dict[str, Any]) -> Any:
        if family is ModelFamily.anomaly:
            return AnomalyModel.from_state(state)
        if family is ModelFamily.cluster:
            return ClusterModel.from_state(state)
        if family is ModelFamily.density:
            return DensityClusterModel.from_state(state)
        if family is ModelFamily.classifier:
            return ContextualClassifierModel.from_state(state)
        if family is ModelFamily.ranker:
            return ContextualRankerModel.from_state(state)
        if family is ModelFamily.similarity:
            return SimilarityIndex.from_state(state)
        raise ValueError(f"unsupported family {family}")

    # ---- public inference -----------------------------------------------

    async def context_for(self, snapshot: FeatureSnapshot) -> MatchContextResponse:
        """Composite inference. Each family is independent so we run
        them concurrently."""
        # Snapshot data_confidence is recomputed inside with_defaults()
        # — capture the post-fill value so it's the one that flows into
        # every per-family ContextOutput.
        snapshot = snapshot.with_defaults()
        if snapshot.schema_version != self._schema:
            return MatchContextResponse(
                match_id=snapshot.match_id,
                feature_schema_version=self._schema,
                sport=snapshot.sport,
                competition_id=snapshot.competition_id,
                data_confidence=snapshot.data_confidence,
                sources=list(snapshot.sources),
                feature_window_origin=snapshot.feature_window_origin,
            )

        anomaly, cluster, density, classifier = await asyncio.gather(
            self.anomaly(snapshot, _silence=True),
            self.cluster(snapshot, _silence=True),
            self.density(snapshot, _silence=True),
            self.classifier(snapshot, _silence=True),
        )
        return MatchContextResponse(
            match_id=snapshot.match_id,
            feature_schema_version=self._schema,
            sport=snapshot.sport,
            competition_id=snapshot.competition_id,
            data_confidence=snapshot.data_confidence,
            sources=list(snapshot.sources),
            feature_window_origin=snapshot.feature_window_origin,
            anomaly=anomaly,
            cluster=cluster,
            density=density,
            classifier=classifier,
        )

    async def anomaly(
        self, snapshot: FeatureSnapshot, *, _silence: bool = False
    ) -> ContextOutput | None:
        loaded = await self._get(ModelFamily.anomaly)
        if loaded is None:
            return None
        version, model = loaded
        assert isinstance(model, AnomalyModel)
        # Tree-model scoring releases the GIL — offload so the four
        # families really run in parallel under asyncio.gather().
        result = await asyncio.to_thread(model.score_vector, snapshot.to_vector())
        if result.is_anomaly:
            headline = "Movimento incomum detectado"
            tags = ["unusual_movement"]
        else:
            headline = "Sem anomalias relevantes na janela"
            tags = ["nominal"]
        return ContextOutput(
            match_id=snapshot.match_id,
            sport=snapshot.sport,
            competition_id=snapshot.competition_id,
            model_name="anomaly_isolation_forest",
            family=ModelFamily.anomaly.value,
            context_confidence=float(result.score),
            headline=headline,
            tags=tags,
            top_factors=[
                Factor(feature=f, contribution=c) for f, c in result.top_factors
            ],
            model_version=version.semver,
            feature_schema_version=self._schema,
            data_confidence=snapshot.data_confidence,
            sources=list(snapshot.sources),
            feature_window_origin=snapshot.feature_window_origin,
            final_confidence=self._final_confidence(snapshot, float(result.score)),
            metrics={"is_anomaly": result.is_anomaly},
        )

    async def cluster(
        self, snapshot: FeatureSnapshot, *, _silence: bool = False
    ) -> ContextOutput | None:
        loaded = await self._get(ModelFamily.cluster)
        if loaded is None:
            return None
        version, model = loaded
        assert isinstance(model, ClusterModel)
        result = await asyncio.to_thread(model.assign, snapshot.to_vector())
        confidence = max(0.0, min(1.0, 1.0 - (result.distance / max(1.0, _vector_norm()))))
        return ContextOutput(
            match_id=snapshot.match_id,
            sport=snapshot.sport,
            competition_id=snapshot.competition_id,
            model_name="cluster_kmeans",
            family=ModelFamily.cluster.value,
            context_confidence=confidence,
            headline=f"Cluster {result.cluster_id} — padrão histórico de comportamento",
            tags=[f"cluster_{result.cluster_id}"],
            top_factors=[
                Factor(feature=f, contribution=c) for f, c in result.top_factors
            ],
            model_version=version.semver,
            feature_schema_version=self._schema,
            data_confidence=snapshot.data_confidence,
            sources=list(snapshot.sources),
            feature_window_origin=snapshot.feature_window_origin,
            final_confidence=self._final_confidence(snapshot, confidence),
            metrics={"cluster_id": result.cluster_id, "distance": result.distance},
        )

    async def density(
        self, snapshot: FeatureSnapshot, *, _silence: bool = False
    ) -> ContextOutput | None:
        loaded = await self._get(ModelFamily.density)
        if loaded is None:
            return None
        version, model = loaded
        assert isinstance(model, DensityClusterModel)
        result = await asyncio.to_thread(model.assign, snapshot.to_vector())
        if result.is_noise:
            headline = "Padrão sem precedente próximo no histórico"
            tags = ["novel_pattern"]
            # Sprint 0 fix: noise = no nearby precedent → LOW context
            # confidence (we have no historical analogue to be confident
            # ABOUT). Pre-fix this branch returned 1.0, which inverted
            # the signal. Use a small constant (0.2) rather than 0 so
            # the UI still surfaces "novel pattern" without being
            # filtered out entirely.
            confidence = 0.2
        else:
            headline = f"Padrão de comportamento agrupado (#{result.cluster_id})"
            tags = [f"density_{result.cluster_id}"]
            confidence = float(result.probability)
        return ContextOutput(
            match_id=snapshot.match_id,
            sport=snapshot.sport,
            competition_id=snapshot.competition_id,
            model_name="density_hdbscan",
            family=ModelFamily.density.value,
            context_confidence=confidence,
            headline=headline,
            tags=tags,
            top_factors=[
                Factor(feature=f, contribution=c) for f, c in result.top_factors
            ],
            model_version=version.semver,
            feature_schema_version=self._schema,
            data_confidence=snapshot.data_confidence,
            sources=list(snapshot.sources),
            feature_window_origin=snapshot.feature_window_origin,
            final_confidence=self._final_confidence(snapshot, confidence),
            metrics={"is_noise": result.is_noise, "cluster_id": result.cluster_id},
        )

    async def classifier(
        self, snapshot: FeatureSnapshot, *, _silence: bool = False
    ) -> ContextOutput | None:
        loaded = await self._get(ModelFamily.classifier)
        if loaded is None:
            return None
        version, model = loaded
        assert isinstance(model, ContextualClassifierModel)
        pred = await asyncio.to_thread(model.predict, snapshot.to_vector())
        headline = CLASSIFIER_HEADLINE.get(
            pred.label, "Comportamento detectado pelo classificador"
        )
        return ContextOutput(
            match_id=snapshot.match_id,
            sport=snapshot.sport,
            competition_id=snapshot.competition_id,
            model_name="classifier_xgboost",
            family=ModelFamily.classifier.value,
            context_confidence=float(pred.confidence),
            headline=headline,
            tags=[pred.label],
            top_factors=[
                Factor(feature=f, contribution=c) for f, c in pred.top_factors
            ],
            model_version=version.semver,
            feature_schema_version=self._schema,
            data_confidence=snapshot.data_confidence,
            sources=list(snapshot.sources),
            feature_window_origin=snapshot.feature_window_origin,
            final_confidence=self._final_confidence(snapshot, float(pred.confidence)),
            metrics={"label": pred.label},
        )

    async def similar(
        self,
        snapshot: FeatureSnapshot,
        *,
        index: SimilarityIndex,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        results = index.topk(snapshot.to_vector(), k=k)
        return [
            {
                "match_id": str(m.match_id),
                "similarity": m.similarity,
                "shared_factors": [
                    {"feature": f, "contribution": c} for f, c in m.shared_factors
                ],
            }
            for m in results
        ]


def _vector_norm() -> float:
    return float(len(FEATURE_NAMES)) ** 0.5
