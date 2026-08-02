"""Canonical historical catalogues.

These classes resolve provider-native identifiers into stable Atlas
canonical ids while preserving provider lineage. They are deliberately
pure and storage-agnostic so the same identity rules can be used by a
CSV/JSONL import job, a provider API backfill job, or a future database
repository without changing the canonicalisation contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid5


CATALOGUE_NAMESPACE = UUID("3f3c0c3d-7df4-4fd4-b188-d54ad1a78501")


def _norm(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _day(value: datetime) -> str:
    return value.astimezone(timezone.utc).date().isoformat()


@dataclass(frozen=True)
class ProviderMapping:
    provider: str
    entity_type: str
    external_id: str
    canonical_id: UUID
    first_seen_at: datetime
    last_seen_at: datetime
    metadata: dict = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.provider, self.entity_type, self.external_id)


class _Catalogue:
    entity_type: str

    def __init__(self) -> None:
        self._by_provider: dict[tuple[str, str, str], UUID] = {}
        self._mappings: dict[tuple[str, str, str], ProviderMapping] = {}

    @property
    def mappings(self) -> list[ProviderMapping]:
        return list(self._mappings.values())

    def _remember(
        self,
        *,
        provider: str,
        external_id: str,
        canonical_id: UUID,
        observed_at: datetime,
        metadata: dict | None = None,
    ) -> UUID:
        key = (provider, self.entity_type, external_id)
        existing = self._by_provider.get(key)
        if existing is not None and existing != canonical_id:
            raise ValueError(
                f"provider mapping conflict for {provider}:{self.entity_type}:{external_id}"
            )
        self._by_provider[key] = canonical_id
        old = self._mappings.get(key)
        self._mappings[key] = ProviderMapping(
            provider=provider,
            entity_type=self.entity_type,
            external_id=external_id,
            canonical_id=canonical_id,
            first_seen_at=min(old.first_seen_at, observed_at) if old else observed_at,
            last_seen_at=max(old.last_seen_at, observed_at) if old else observed_at,
            metadata={**(old.metadata if old else {}), **(metadata or {})},
        )
        return canonical_id


class TeamCatalogue(_Catalogue):
    entity_type = "team"

    def resolve(
        self,
        *,
        provider: str,
        external_id: str,
        name: str,
        country_code: str | None,
        observed_at: datetime,
    ) -> UUID:
        key = (provider, self.entity_type, external_id)
        if key in self._by_provider:
            return self._by_provider[key]
        canonical_key = f"team::{_norm(country_code)}::{_norm(name)}"
        canonical_id = uuid5(CATALOGUE_NAMESPACE, canonical_key)
        return self._remember(
            provider=provider,
            external_id=external_id,
            canonical_id=canonical_id,
            observed_at=observed_at,
            metadata={"name": name, "country_code": country_code or ""},
        )


class CompetitionCatalogue(_Catalogue):
    entity_type = "competition"

    def resolve(
        self,
        *,
        provider: str,
        external_id: str,
        name: str,
        country_code: str | None,
        season: str,
        observed_at: datetime,
    ) -> UUID:
        key = (provider, self.entity_type, external_id)
        if key in self._by_provider:
            return self._by_provider[key]
        canonical_key = f"competition::{_norm(country_code)}::{_norm(name)}::{_norm(season)}"
        canonical_id = uuid5(CATALOGUE_NAMESPACE, canonical_key)
        return self._remember(
            provider=provider,
            external_id=external_id,
            canonical_id=canonical_id,
            observed_at=observed_at,
            metadata={"name": name, "country_code": country_code or "", "season": season},
        )


class MatchCatalogue(_Catalogue):
    entity_type = "match"

    def resolve(
        self,
        *,
        provider: str,
        external_id: str,
        competition_id: UUID,
        home_team_id: UUID,
        away_team_id: UUID,
        kickoff_at: datetime,
        observed_at: datetime,
    ) -> UUID:
        key = (provider, self.entity_type, external_id)
        if key in self._by_provider:
            return self._by_provider[key]
        teams = sorted([str(home_team_id), str(away_team_id)])
        canonical_key = (
            f"match::{competition_id}::{_day(kickoff_at)}::{teams[0]}::{teams[1]}"
        )
        canonical_id = uuid5(CATALOGUE_NAMESPACE, canonical_key)
        return self._remember(
            provider=provider,
            external_id=external_id,
            canonical_id=canonical_id,
            observed_at=observed_at,
            metadata={
                "competition_id": str(competition_id),
                "home_team_id": str(home_team_id),
                "away_team_id": str(away_team_id),
                "kickoff_at": kickoff_at.astimezone(timezone.utc).isoformat(),
            },
        )
