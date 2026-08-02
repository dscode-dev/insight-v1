"""Request contracts for the deterministic Atlas intelligence runtime."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from atlas.intelligence.contracts import RegimeType
from atlas.intelligence.kernel import ensure_aware


class RuntimeOdds(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    opening_home: float = Field(gt=1.0)
    opening_draw: float = Field(gt=1.0)
    opening_away: float = Field(gt=1.0)
    current_home: float = Field(gt=1.0)
    current_draw: float = Field(gt=1.0)
    current_away: float = Field(gt=1.0)
    bookmaker: str | None = Field(default=None, max_length=96)


class AtlasRuntimeContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    competition: str = Field(min_length=1, max_length=128)
    home_team: str = Field(min_length=1, max_length=128)
    away_team: str = Field(min_length=1, max_length=128)
    regime: RegimeType | None = None
    odds: RuntimeOdds | None = None
    as_of: datetime | None = None
    historical_data: str = Field(
        default="configured_certified_dataset",
        min_length=1,
        max_length=128,
    )

    @field_validator("as_of")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        return ensure_aware(value) if value is not None else None

    @field_validator("away_team")
    @classmethod
    def _different_team(cls, value: str, info) -> str:
        if value == info.data.get("home_team"):
            raise ValueError("home and away teams must differ")
        return value


class RuntimeExecutionTrace(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    engine_order: list[str]
    completed_engines: list[str]
    deterministic: bool = True
    request_odds_used: bool = False
    historical_data: str

