"""Shared explorer.envelope.v1 builder — every per-source normalizer wraps
its payload with the same envelope shape; this is the one place that shape
is assembled, so adding a field or a source never means editing N files
identically.
"""

from __future__ import annotations

from typing import Any

from explorer.adapters.base import RawArtifact
from explorer.config import COMPETITIONS
from explorer.datalake.lake import checksum


def build_envelope(
    artifact: RawArtifact,
    *,
    confidence: float,
    payload: dict[str, Any],
    competition_external_id: str | None = None,
    entity_type: str | None = None,
) -> dict[str, Any]:
    """`entity_type` selects the payload schema (explorer.<entity_type>.v1).

    It used to be hardcoded to "fixture" here. Every contract for odds, stats,
    lineups and injuries already existed and was unreachable: a normalizer
    could build an odds payload and this function would still label it a
    fixture, so validation compared an odds body against the fixture schema
    and rejected it. Collecting anything but fixtures was impossible one
    layer below where anyone was looking.

    Defaults to the artifact's own entity_type, so an adapter that already
    declares what it is fetching needs no second declaration here.
    """
    comp_def = COMPETITIONS.get(artifact.competition_key)
    return {
        "schema_version": "explorer.envelope.v1",
        "source": artifact.source,
        "provider": artifact.provider,
        "source_type": artifact.source_type,
        "trust_level": artifact.trust_level,
        "confidence": confidence,
        "captured_at": artifact.retrieved_at,
        "entity_type": entity_type or artifact.entity_type or "fixture",
        "external_id": artifact.external_id,
        "canonical_match_id": None,
        "competition": {
            "competition_key": artifact.competition_key,
            "competition_id": None,
            "external_id": competition_external_id,
            "name": comp_def.name if comp_def else None,
        },
        "season": artifact.season,
        "payload": payload,
        "provenance": {
            "url": artifact.url,
            "retrieved_at": artifact.retrieved_at,
            "method": artifact.method,
            "parser": artifact.provider,
            "checksum": checksum(artifact.raw),
            "license_note": artifact.license_note,
        },
    }
