"""Live team-strength engine (ATLAS-SIM-A).

Deliberately does NOT import `lake.py`/`sync_watcher.py` at package init
time — those pull in `atlas.intelligence.historical`/`atlas.watchers`
respectively, and this package is itself imported from
`atlas.intelligence.orchestrator.engine` (for `formulas.line_movement`),
which would otherwise create an import cycle back through
`atlas.watchers -> atlas.trends -> atlas.trends.oracle_similarity ->
atlas.similarity.contracts -> atlas.intelligence.kernel ->
atlas.intelligence (package) -> report_builder -> orchestrator`. Import
`atlas.strength.lake`/`atlas.strength.sync_watcher` directly (as
`atlas/api/app.py` does) rather than via this package root.
"""

from atlas.strength.market_features import MarketFeatures, market_features_for_match
from atlas.strength.models import MatchResult, TeamStrengthFeatures
from atlas.strength.repository import StrengthRepository

__all__ = [
    "MarketFeatures",
    "MatchResult",
    "StrengthRepository",
    "TeamStrengthFeatures",
    "market_features_for_match",
]
