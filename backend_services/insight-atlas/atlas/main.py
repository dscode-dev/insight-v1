"""ASGI entrypoint. `uvicorn atlas.main:app` starts the service."""

from __future__ import annotations

from atlas.api import build_app

app = build_app()
