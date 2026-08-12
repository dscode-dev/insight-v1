"""OpenTelemetry tracing surface for the Anvil runtime.

This module is intentionally thin. It exposes:

  * `tracer` — a module-level Tracer instance the rest of the code uses;
  * `init_tracing()` — wires the SDK once at startup, honouring environment
    variables. The exporter is decided by the standard OTel env vars
    (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_TRACES_EXPORTER`, etc.) so the
    deployment can pick Tempo, Jaeger, an OTel Collector, or no exporter at
    all without touching code.
  * `span()` — a thin context manager wrapper that produces a no-op span
    when tracing has not been initialised. Call sites are unconditional:
    `async with span("handler.process", attributes={...})`.

Design constraints (as agreed in the Stage 0 plan):

  * Only OpenTelemetry **interfaces** are consumed. We do not import any
    Jaeger/Tempo/Grafana-specific client. The user installs the exporter
    of their choice via env-driven `pip install opentelemetry-exporter-*`.
  * If `opentelemetry-sdk` is missing or `OTEL_TRACES_EXPORTER=none`,
    `init_tracing()` is a no-op and `span()` returns a no-op span. This
    means tests and dev environments don't need to install anything new.
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import Any, Iterator, Mapping, Optional

logger = logging.getLogger(__name__)

# `opentelemetry-api` is the only hard import we want to declare. Even that
# is wrapped so a test or constrained deployment that strips OTel out at
# install time still imports cleanly.
try:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode, Tracer

    _OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover — exercised by deployments without otel
    trace = None  # type: ignore[assignment]
    Status = None  # type: ignore[assignment]
    StatusCode = None  # type: ignore[assignment]
    Tracer = Any  # type: ignore[misc,assignment]
    _OTEL_AVAILABLE = False


_INITIALISED = False
_TRACER: Optional[Tracer] = None


def init_tracing(
    *,
    service_name: str = "anvil",
    service_version: str | None = None,
) -> None:
    """Initialise the OTel SDK + exporter.

    Idempotent. If OTel is not installed (or `OTEL_TRACES_EXPORTER=none`),
    leaves tracing disabled and `span()` will produce no-op spans.

    Environment knobs respected (all standard OTel):
      OTEL_TRACES_EXPORTER          one of: none, otlp, console (default: otlp)
      OTEL_EXPORTER_OTLP_ENDPOINT   collector endpoint (e.g. http://otel:4318)
      OTEL_SERVICE_NAME             overrides the `service_name` argument
      OTEL_RESOURCE_ATTRIBUTES      k=v,k=v free-form resource attrs
    """
    global _INITIALISED, _TRACER

    if _INITIALISED:
        return

    if not _OTEL_AVAILABLE:
        logger.info(
            "tracing_disabled_otel_api_not_installed",
            extra={"hint": "pip install opentelemetry-api opentelemetry-sdk"},
        )
        _INITIALISED = True
        return

    exporter_choice = (os.getenv("OTEL_TRACES_EXPORTER") or "otlp").lower()

    if exporter_choice == "none":
        logger.info("tracing_disabled_by_env", extra={"OTEL_TRACES_EXPORTER": "none"})
        _INITIALISED = True
        return

    # The SDK is a separate package; import lazily so api-only installs work.
    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
    except ImportError:
        logger.warning(
            "tracing_sdk_missing",
            extra={
                "exporter_choice": exporter_choice,
                "hint": "pip install opentelemetry-sdk",
            },
        )
        _INITIALISED = True
        return

    resource_attrs: dict[str, str] = {
        "service.name": os.getenv("OTEL_SERVICE_NAME", service_name),
    }
    if service_version:
        resource_attrs["service.version"] = service_version
    resource = Resource.create(resource_attrs)

    provider = TracerProvider(resource=resource)

    exporter = None
    if exporter_choice == "console":
        exporter = ConsoleSpanExporter()
    elif exporter_choice == "otlp":
        # OTLP exporter is optional. If absent, fall back to no exporter
        # (tracing stays on as no-op spans).
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter()
        except ImportError:
            logger.warning(
                "tracing_otlp_exporter_not_installed",
                extra={
                    "hint": "pip install opentelemetry-exporter-otlp",
                },
            )
            exporter = None
    else:
        logger.warning(
            "tracing_unknown_exporter_choice",
            extra={"OTEL_TRACES_EXPORTER": exporter_choice},
        )

    if exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _TRACER = trace.get_tracer(service_name)
    _INITIALISED = True

    logger.info(
        "tracing_initialised",
        extra={
            "exporter": exporter_choice,
            "service_name": resource_attrs["service.name"],
        },
    )


def get_tracer() -> Optional[Tracer]:
    """Returns the active Tracer or None when tracing is disabled."""
    if _OTEL_AVAILABLE and _TRACER is None and not _INITIALISED:
        # Lazy default — caller forgot to init. Use a get_tracer fallback so
        # spans don't blow up; they just won't be exported.
        return trace.get_tracer("anvil")
    return _TRACER


@contextlib.contextmanager
def span(
    name: str,
    *,
    attributes: Optional[Mapping[str, Any]] = None,
) -> Iterator[Any]:
    """Context-manager span that is a no-op when tracing is disabled.

    Records exceptions and sets ERROR status on the span when the body
    raises. The exception still propagates.
    """
    tracer = get_tracer()
    if tracer is None:
        # Disabled: yield a None-like sentinel so `as` clauses still work.
        yield _NoopSpan()
        return

    with tracer.start_as_current_span(name) as s:
        if attributes:
            for k, v in attributes.items():
                try:
                    s.set_attribute(k, v)
                except Exception:
                    # Defensive: span attribute values must be primitives.
                    s.set_attribute(k, str(v))
        try:
            yield s
        except Exception as exc:  # noqa: BLE001 — re-raised below
            try:
                s.record_exception(exc)
                s.set_status(Status(StatusCode.ERROR, str(exc)))
            except Exception:
                pass
            raise


class _NoopSpan:
    """Minimal no-op span used when tracing is disabled.

    Implements just enough of the OTel Span surface to keep `set_attribute`
    and `record_exception` calls safe at call sites.
    """

    def set_attribute(self, *_args, **_kwargs) -> None:
        return None

    def record_exception(self, *_args, **_kwargs) -> None:
        return None

    def set_status(self, *_args, **_kwargs) -> None:
        return None
