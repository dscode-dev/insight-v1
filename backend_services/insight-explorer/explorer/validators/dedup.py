"""Deterministic deduplication (Step 9).

Two-level: by raw content checksum (provenance.checksum) and by logical key
(source + external_id). The CrewAI Match Validator may *flag* suspected
semantic duplicates, but only this deterministic pass removes records.
"""

from __future__ import annotations

from typing import Any, Iterable


def logical_key(envelope: dict[str, Any]) -> tuple[str, str]:
    return (envelope.get("source", ""), envelope.get("external_id", ""))


def deduplicate(envelopes: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Return (unique, duplicates_removed). Keeps first occurrence."""
    seen_checksums: set[str] = set()
    seen_keys: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    removed = 0
    for env in envelopes:
        cs = (env.get("provenance") or {}).get("checksum")
        key = logical_key(env)
        if (cs and cs in seen_checksums) or key in seen_keys:
            removed += 1
            continue
        if cs:
            seen_checksums.add(cs)
        seen_keys.add(key)
        unique.append(env)
    return unique, removed


def duplication_ratio(total: int, removed: int) -> float:
    return removed / total if total else 0.0
