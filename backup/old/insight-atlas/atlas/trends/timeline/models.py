"""Trend timeline domain models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TrendTimelineEntry(BaseModel):
    """One step in a story's narrative timeline — the evaluated trend
    as it stood at that moment."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    trend_id: UUID
    trend_type: str
    lifecycle_state: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    strength: float = Field(ge=0.0, le=1.0)
    summary: str = ""
    meaning: str = ""


class TrendTimeline(BaseModel):
    """The ordered (oldest→newest), append-only timeline of one story.

    `cluster_id` is the trend lifecycle instance id — Atlas's story
    grouping unit.
    """

    model_config = ConfigDict(frozen=True)

    cluster_id: UUID
    entries: list[TrendTimelineEntry] = Field(default_factory=list)
