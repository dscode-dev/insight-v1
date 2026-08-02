"""Structured (JSON) logging for the Anvil runtime.

The previous configuration used `logging.basicConfig` with a format string of
`%(asctime)s %(levelname)s %(name)s %(message)s`. That format does not
interpolate the `extra={}` fields that the entire codebase relies on:
every call site like

    logger.info("event_acked", extra={"stream": s, "match_id": ...})

was logging the literal string `event_acked` and dropping every field.

This module installs a JSON formatter that:
  * always emits timestamp, level, logger name, message, and the basic
    process / thread context;
  * surfaces every `extra={}` field as a top-level JSON key (skipping the
    LogRecord reserved attributes);
  * preserves traceback rendering on exceptions;
  * is safe to wire on every startup (`configure_logging()` is idempotent).

The output is a single line per record, suitable for Loki / Fluent / GCP
Cloud Logging without a custom parser.

The logger does **not** depend on any third-party library; stdlib only.
That keeps the configure path failure-free at import time and avoids a
chicken-and-egg dependency for the readiness probe.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

# LogRecord attributes we never want to copy into the JSON envelope as `extra`
# fields. The list mirrors Python's logging.LogRecord __dict__ keys plus a
# few internal markers used by some handlers.
_RESERVED_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
        "taskName",  # 3.12+
    }
)


class JsonFormatter(logging.Formatter):
    """Format a LogRecord as a single-line JSON object.

    Fields:
      ts          ISO-8601 UTC timestamp with millisecond precision
      level       textual level (INFO/WARNING/...)
      logger      logger name
      message     formatted log message (post `%` interpolation)
      service     constant per-process tag (default "anvil")
      version     constant per-process tag (free-form, e.g. release sha)
      pid         OS process id
      thread      thread name
      <extras>    every key from `extra={}` not in `_RESERVED_ATTRS`
      exc_info    formatted traceback (only when an exception is logged)
    """

    def __init__(
        self,
        *,
        service: str = "anvil",
        version: str | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._version = version

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
            timespec="milliseconds"
        )
        envelope: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self._service,
            "pid": record.process,
            "thread": record.threadName,
        }
        if self._version is not None:
            envelope["version"] = self._version

        # Pull `extra={}` fields. Anything on the record's __dict__ that is
        # not a reserved LogRecord attribute is treated as caller-provided.
        for key, value in record.__dict__.items():
            if key in _RESERVED_ATTRS or key.startswith("_"):
                continue
            if key in envelope:
                # extras MUST NOT clobber envelope fields; namespace them.
                envelope[f"extra.{key}"] = _safe(value)
            else:
                envelope[key] = _safe(value)

        if record.exc_info:
            envelope["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(envelope, default=str, separators=(",", ":"))


def _safe(value: Any) -> Any:
    """Make values JSON-serialisable without per-call exception overhead.

    `json.dumps(default=str)` already handles most types, but we proactively
    coerce a few common ones (bytes -> utf8) so the result is more readable.
    """
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.hex()
    return value


def configure_logging(
    *,
    service: str = "anvil",
    version: str | None = None,
    stream=None,
) -> None:
    """Idempotent: safe to call from `main()` and from tests.

    Honours $LOG_LEVEL (default INFO). Honours $LOG_SERVICE_VERSION if not
    provided explicitly. Writes to stderr by default (matches K8s expectation).
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    if version is None:
        version = os.getenv("LOG_SERVICE_VERSION")

    handler = logging.StreamHandler(stream=stream or sys.stderr)
    handler.setFormatter(JsonFormatter(service=service, version=version))

    root = logging.getLogger()
    # Wipe any handlers attached by a previous configure call (or basicConfig
    # called by tests / poetry / something else). The structured formatter is
    # the single source of truth in this process.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)
