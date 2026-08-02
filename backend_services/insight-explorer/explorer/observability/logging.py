"""Structured JSON logging (Step 10 — structured logs mandatory).

Every log line is a single JSON object on stdout with a stable set of
fields so the Console / Loki can index by job_id, source, competition.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any


class StructuredLogger:
    def __init__(self, component: str, **base: Any) -> None:
        self.component = component
        self.base = {k: v for k, v in base.items() if v is not None}

    def bind(self, **fields: Any) -> "StructuredLogger":
        merged = {**self.base, **{k: v for k, v in fields.items() if v is not None}}
        return StructuredLogger(self.component, **merged)

    def _emit(self, level: str, event: str, **fields: Any) -> None:
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level": level,
            "component": self.component,
            "event": event,
            **self.base,
            **{k: v for k, v in fields.items() if v is not None},
        }
        sys.stdout.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        sys.stdout.flush()

    def info(self, event: str, **fields: Any) -> None:
        self._emit("info", event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._emit("warning", event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self._emit("error", event, **fields)


def get_logger(component: str, **base: Any) -> StructuredLogger:
    return StructuredLogger(component, **base)
