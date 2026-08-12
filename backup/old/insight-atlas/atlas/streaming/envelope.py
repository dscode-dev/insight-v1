from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from atlas.streaming.jsonx import dumps


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    match_id: UUID
    region_code: str = Field(min_length=1, max_length=32)
    event_type: str = Field(min_length=1, max_length=64)
    match_version: int = Field(default=0, ge=0)
    ts_ingest: datetime
    payload: dict

    @field_validator("ts_ingest")
    @classmethod
    def _ts_ingest_must_be_tz_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("ts_ingest must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _payload_must_not_be_empty(self) -> "EventEnvelope":
        if not self.payload:
            raise ValueError("payload must not be empty")
        return self

    def to_redis_dict(self) -> dict[bytes, bytes]:
        return {
            b"event_id": str(self.event_id).encode(),
            b"match_id": str(self.match_id).encode(),
            b"region_code": self.region_code.encode(),
            b"event_type": self.event_type.encode(),
            b"match_version": str(self.match_version).encode(),
            b"ts_ingest": self.ts_ingest.isoformat().encode(),
            b"payload": dumps(self.payload),
        }
