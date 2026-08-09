"""The anti-prediction guard — Atlas's single hardest product rule.

Atlas is a DESCRIPTIVE context layer. It may report what a third-party
market implies (odds-derived implied probabilities are someone else's
number, faithfully described) but it must never emit its OWN forecast of
a match outcome, a betting recommendation, or a guaranteed return.

This module is the shared home of that rule. It used to live inline in
`atlas/inference/output.py` and therefore only protected `ContextOutput`
— which is NOT Atlas's main output. The real public surface is the
`insight:stream:trends` envelope (consumed by Nexus → Atrium → Azteca)
plus the intelligence report's free-text fields, and neither was
covered. Nothing structurally stopped a future detector from putting
`win_probability` into `Trend.evidence`.

Two scans, deliberately different in kind:
  * `assert_no_prediction_keys` — EXACT key match against structured
    dicts. Exact (not substring) so `expected_lineup` never collides
    with `expected_return`.
  * `assert_no_prediction_phrases` — case-insensitive SUBSTRING scan
    over free text, where a human can phrase a forecast any number of
    ways.

When extending: add exact terms, never regex shortcuts. This list is
meant to be auditable in code review; cleverness here is a liability.
"""

from __future__ import annotations

import re
from typing import Any

FORBIDDEN_METRIC_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"^win_probability$",
        r"^home_win_pct$",
        r"^draw_win_pct$",
        r"^away_win_pct$",
        r"^outcome_probability$",
        r"^bet_value$",
        r"^bet_recommendation$",
        r"^pick$",
        r"^picks$",
        r"^recommendation$",
        r"^recommended_odds$",
        r"^expected_return$",
        r"^expected_value$",
        r"^ev_percent$",
        r"^safe_signal$",
        r"^guaranteed.*$",
        r"^tip(_.*)?$",
        r"^tipster.*$",
    )
)

FORBIDDEN_PHRASES: tuple[str, ...] = (
    "win_probability",
    "probabilidade de vit",
    "chance de vit",
    "tip do dia",
    "aposta segura",
    "aposta certa",
    "safe bet",
    "sure thing",
    "guaranteed win",
    "we predict",
    "our prediction",
    "vai vencer",
    "vai ganhar",
)


def assert_no_prediction_keys(mapping: dict[str, Any], *, where: str) -> None:
    """Raise if any key in `mapping` reads as a prediction/recommendation.

    `where` names the offending surface so the error tells an operator
    exactly which contract to look at.
    """
    for key in mapping:
        for pattern in FORBIDDEN_METRIC_PATTERNS:
            if pattern.match(key):
                raise ValueError(
                    f"{where}: key {key!r} matches the anti-prediction "
                    f"deny-list. Atlas outputs are DESCRIPTIVE — adding a "
                    f"prediction/recommendation key requires changing the "
                    f"deny-list in atlas/contracts/no_prediction.py and "
                    f"reviewing the product/legal posture."
                )


def assert_no_prediction_phrases(text: str, *, where: str) -> None:
    """Raise if free text contains a forbidden forecast phrase."""
    lower = text.lower()
    for needle in FORBIDDEN_PHRASES:
        if needle in lower:
            raise ValueError(
                f"{where}: text contains forbidden phrase {needle!r} "
                f"(see atlas/contracts/no_prediction.py deny-list)"
            )


def scan_payload(value: Any, *, where: str) -> None:
    """Recursively enforce BOTH scans over an arbitrary nested payload.

    Used on evidence dicts, which are `dict[str, Any]` by contract and
    can nest freely. Keys are key-scanned; string values are
    phrase-scanned.
    """
    if isinstance(value, dict):
        assert_no_prediction_keys(value, where=where)
        for nested in value.values():
            scan_payload(nested, where=where)
    elif isinstance(value, (list, tuple)):
        for item in value:
            scan_payload(item, where=where)
    elif isinstance(value, str):
        assert_no_prediction_phrases(value, where=where)
