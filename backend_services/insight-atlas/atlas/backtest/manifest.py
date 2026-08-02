"""ReplayManifest — the official reproducibility contract (ATLAS-BACKTEST-B, Stage 0).

Every replay execution produces a manifest of the exact versions + inputs that
generated it, so a `replay_hash` is meaningful only alongside the manifest that
produced it. All version values are REAL module constants — never fabricated.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from atlas.intelligence.kernel import INTELLIGENCE_SCHEMA_VERSION
from atlas.trends.engine import default_detectors
from atlas.trends.models import TREND_SCHEMA_VERSION
from atlas.vector_memory.contracts import EMBEDDING_VERSION
from atlas.vector_memory.provenance import feature_schema_version

# This replay framework's own version — bumped when replay semantics change.
REPLAY_ENGINE_VERSION = "1.0.0"


def detector_versions() -> dict[str, str]:
    """Real detector inventory → their (trend-schema) version. Deterministic."""
    return {
        type(detector).__name__: TREND_SCHEMA_VERSION
        for detector in default_detectors()
    }


class ReplayManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    replay_id: str
    replay_hash: str
    dataset: str
    competition: str = ""
    season: str = ""
    time_interval: str = ""
    explorer_dataset_version: str = "unknown"
    feature_schema_version: str
    similarity_version: str = EMBEDDING_VERSION
    oracle_version: str = INTELLIGENCE_SCHEMA_VERSION
    behavior_version: str = INTELLIGENCE_SCHEMA_VERSION
    reasoning_version: str = INTELLIGENCE_SCHEMA_VERSION
    trend_engine_version: str = TREND_SCHEMA_VERSION
    replay_engine_version: str = REPLAY_ENGINE_VERSION
    detector_versions: dict[str, str] = Field(default_factory=dict)
    execution_timestamp: datetime
    execution_duration_ms: int
    artifact_locations: list[str] = Field(default_factory=list)


def build_manifest(
    *,
    replay_id: str,
    replay_hash: str,
    dataset: str,
    execution_timestamp: datetime,
    execution_duration_ms: int,
    competition: str = "",
    season: str = "",
    time_interval: str = "",
    explorer_dataset_version: str = "unknown",
    artifact_locations: list[str] | None = None,
) -> ReplayManifest:
    return ReplayManifest(
        replay_id=replay_id,
        replay_hash=replay_hash,
        dataset=dataset,
        competition=competition,
        season=season,
        time_interval=time_interval,
        explorer_dataset_version=explorer_dataset_version,
        feature_schema_version=feature_schema_version(),
        detector_versions=detector_versions(),
        execution_timestamp=execution_timestamp,
        execution_duration_ms=execution_duration_ms,
        artifact_locations=list(artifact_locations or []),
    )
