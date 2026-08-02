"""Atlas deterministic replay & quality evaluation framework (ATLAS-BACKTEST-A).

Observes the production intelligence pipeline over historical data and produces
reproducible evaluations, reports and regression diffs. The mandatory quality
gate for every future detector/heuristic/similarity/reasoning change. No ML,
no training, no threshold changes — it never alters runtime behaviour.
"""

from atlas.backtest.adapter import (
    ExplorerDatasetAdapter,
    scenario_from_dataset,
    scenario_from_interval,
    scenario_from_match,
    scenario_from_mission,
    scenario_from_scope,
    scenario_from_season,
)
from atlas.backtest.contracts import (
    BehaviorEvaluation,
    DetectorEvaluation,
    DetectorReport,
    ExplainabilityReport,
    PromotionReport,
    QualityEvaluation,
    QualityReport,
    RegressionDiff,
    RegressionReport,
    ReplayArtifacts,
    ReplayExecution,
    ReplayQuality,
    ReplayReport,
    ReplayResult,
    ReplayScenario,
    ReplayStep,
    SimilarityEvaluation,
    StageEvaluation,
    TrendEvaluation,
)
from atlas.backtest.engine import ReplayEngine
from atlas.backtest.manifest import ReplayManifest, build_manifest, detector_versions
from atlas.backtest.quality import evaluate
from atlas.backtest.regression import diff_replays
from atlas.backtest.service import ReplayService

__all__ = [
    "BehaviorEvaluation",
    "DetectorEvaluation",
    "DetectorReport",
    "ExplainabilityReport",
    "ExplorerDatasetAdapter",
    "PromotionReport",
    "QualityEvaluation",
    "QualityReport",
    "RegressionDiff",
    "RegressionReport",
    "ReplayArtifacts",
    "ReplayManifest",
    "StageEvaluation",
    "build_manifest",
    "detector_versions",
    "evaluate",
    "ReplayEngine",
    "ReplayExecution",
    "ReplayQuality",
    "ReplayReport",
    "ReplayResult",
    "ReplayScenario",
    "ReplayService",
    "ReplayStep",
    "SimilarityEvaluation",
    "TrendEvaluation",
    "diff_replays",
    "scenario_from_dataset",
    "scenario_from_interval",
    "scenario_from_match",
    "scenario_from_mission",
    "scenario_from_scope",
    "scenario_from_season",
]
