"""Outcome labels — derived STRICTLY from the final result.

Non-negotiable rule (ML-C.5b): labels come ONLY from real match outcomes, never
from any Atlas output (prediction, confidence, trend, recommendation). This
module takes raw final scores and nothing else.
"""

from __future__ import annotations


def result_label(home_score: int, away_score: int) -> str:
    """HOME_WIN / DRAW / AWAY_WIN from the full-time score."""
    if home_score > away_score:
        return "HOME_WIN"
    if away_score > home_score:
        return "AWAY_WIN"
    return "DRAW"


def goal_band(home_score: int, away_score: int) -> str:
    """Optional total-goals band label."""
    total = home_score + away_score
    if total <= 1:
        return "GOAL_BAND_LOW"
    if total <= 3:
        return "GOAL_BAND_MEDIUM"
    return "GOAL_BAND_HIGH"
