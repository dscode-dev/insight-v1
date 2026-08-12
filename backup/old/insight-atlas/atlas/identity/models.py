"""Cross-provider match identity models + helpers (Atlas side).

Mirrors the Hub's internal/application/identity package: the same
normalisation + deterministic mint so a canonical_match_id computed on
either side agrees. Atlas owns the AUTHORITATIVE persistent registry;
the Hub stamps a best-effort hint that Atlas prefers when present.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid5

# Same namespace as internal/application/identity (Go) so uuid5 here ==
# uuid.NewSHA1 there for identical inputs.
CANONICAL_NAMESPACE = UUID("6f1c2d34-5a6b-4c7d-8e9f-0a1b2c3d4e5f")


@dataclass(frozen=True, slots=True)
class ProviderMatchIdentity:
    provider: str
    external_id: str
    competition_id: UUID | None
    home_team: str
    away_team: str
    kickoff: datetime | None


@dataclass(frozen=True, slots=True)
class CanonicalMatch:
    canonical_match_id: UUID
    competition_id: UUID | None
    home_team: str
    away_team: str
    kickoff: datetime | None


def normalize(name: str) -> str:
    """Fold a team name to a stable comparison key: lowercase, diacritics
    stripped, non-alphanumerics removed. Matches the Hub's Normalize."""
    decomposed = unicodedata.normalize("NFKD", (name or "").strip().lower())
    return "".join(c for c in decomposed if c.isalnum() and ord(c) < 128)


def mint(
    competition_id: UUID | None,
    norm_home: str,
    norm_away: str,
    kickoff: datetime | None,
) -> UUID:
    """Deterministic canonical id over (competition, teams, hour bucket).
    Identical to the Hub's Mint so cross-service ids agree."""
    bucket = ""
    if kickoff is not None:
        ko = kickoff
        if ko.tzinfo is not None:
            ko = ko.astimezone(tz=_utc())
        ko = ko.replace(minute=0, second=0, microsecond=0)
        bucket = ko.strftime("%Y-%m-%dT%H:%M:%SZ")
    comp = str(competition_id) if competition_id is not None else ""
    key = "|".join([comp, norm_home, norm_away, bucket])
    return uuid5(CANONICAL_NAMESPACE, key)


def _utc():
    from datetime import timezone

    return timezone.utc
