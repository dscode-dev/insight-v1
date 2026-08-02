"""Prometheus rendering for Atlas's /metrics endpoint.

Atlas modules register their own counters/histograms on the default
process registry; this helper renders that registry for HTTP.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
