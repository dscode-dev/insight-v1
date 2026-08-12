"""Os contratos que todo o resto do domínio usa.

Reexportados aqui porque são referenciados de toda parte, e o caminho longo
(`domain.shared.identity.MatchId`) em cinquenta arquivos é ruído.
"""

from sports_intelligence.domain.shared.errors import (
    ConflictError,
    DataQualityError,
    DependencyError,
    EngineError,
    ErrorCategory,
    ErrorDetail,
    ErrorResponse,
    ForbiddenError,
    InvariantViolationError,
    NotFoundError,
    TransientError,
    UnauthorizedError,
    ValidationError,
)
from sports_intelligence.domain.shared.feature_value import (
    FeatureMask,
    FeatureValue,
    MissingFeatureError,
    Unavailability,
)
from sports_intelligence.domain.shared.identity import (
    CompetitionId,
    DatasetId,
    EntityId,
    MatchId,
    PlayerId,
    ProviderId,
    ProviderRef,
    SeasonId,
    SnapshotId,
    TeamId,
)
from sports_intelligence.domain.shared.provenance import (
    DataProvenance,
    LicenseClass,
    SourceType,
    precedence_rank,
)
from sports_intelligence.domain.shared.quality import DataQuality, QualityIssue
from sports_intelligence.domain.shared.temporal import (
    Instant,
    MatchClock,
    ObservationTimes,
    Period,
    instant,
    parse_instant,
)
from sports_intelligence.domain.shared.versioning import (
    DatasetVersion,
    EngineVersion,
    FeatureSpaceVersion,
    NormalizerVersion,
    Version,
    VersionMismatchError,
)

__all__ = [
    "CompetitionId",
    "ConflictError",
    "DataProvenance",
    "DataQuality",
    "DataQualityError",
    "DatasetId",
    "DatasetVersion",
    "DependencyError",
    "EngineError",
    "EngineVersion",
    "EntityId",
    "ErrorCategory",
    "ErrorDetail",
    "ErrorResponse",
    "FeatureMask",
    "FeatureSpaceVersion",
    "FeatureValue",
    "ForbiddenError",
    "Instant",
    "InvariantViolationError",
    "LicenseClass",
    "MatchClock",
    "MatchId",
    "MissingFeatureError",
    "NormalizerVersion",
    "NotFoundError",
    "ObservationTimes",
    "Period",
    "PlayerId",
    "ProviderId",
    "ProviderRef",
    "QualityIssue",
    "SeasonId",
    "SnapshotId",
    "SourceType",
    "TeamId",
    "TransientError",
    "UnauthorizedError",
    "Unavailability",
    "ValidationError",
    "Version",
    "VersionMismatchError",
    "instant",
    "parse_instant",
    "precedence_rank",
]
