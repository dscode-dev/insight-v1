"""Deterministic Evidence construction for historical intelligence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from atlas.intelligence.contracts import Evidence, EvidenceType
from atlas.intelligence.historical import stable_id
from atlas.intelligence.kernel import EvidenceID


class EvidenceEngine:
    def create(
        self,
        *,
        scope_key: str,
        evidence_type: EvidenceType,
        source: str,
        description: str,
        observed_at: datetime,
        weight: float,
        confidence: float,
        attributes: dict[str, Any] | None = None,
    ) -> Evidence:
        return Evidence(
            evidence_id=EvidenceID(
                stable_id(scope_key, evidence_type.value, source, description)
            ),
            evidence_type=evidence_type,
            source=source,
            weight=_clamp(weight),
            confidence=_clamp(confidence),
            description=description,
            observed_at=observed_at,
            attributes=attributes or {},
        )


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))

