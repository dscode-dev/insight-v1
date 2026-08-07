# Insight Explorer — production image (ML-B.5)
# Build context: modules_v1/
# Single container: serves the Console API + /health AND runs the continuous
# historical scheduler in a background thread. Includes the full AI stack
# (LangGraph + CrewAI + Ollama client) so CrewAI/LangGraph actually execute
# against the local Qwen runtime on Robozão.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    EXPLORER_DATA_LAKE=/home/insight/data/explorer \
    EXPLORER_CLUB_REGISTRY=/app/vendor/club_registry.json

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Deterministic core + API + AI stack. Pinned-ish for reproducibility; the
# AI libs (langgraph, crewai, ollama) are what make criteria #6/#7 real.
RUN pip install \
      "requests>=2.31,<3" \
      "jsonschema>=4.17,<5" \
      "prometheus-client>=0.20,<1" \
      "pydantic>=2.6,<3" \
      "fastapi>=0.110,<1" \
      "uvicorn>=0.29,<1" \
      "langgraph>=0.2,<1" \
      "ollama>=0.3,<1" \
      "crewai>=0.51,<1" \
      "pynvml>=11.5,<13" \
      "redis>=5.0,<7"

# redis is NOT optional despite being imported lazily. Both publishers
# (realtime signals, historical backfill) do `import redis` inside a method,
# so a missing package fails at call time rather than at boot — and the
# historical publisher was reached for the first time only after
# EXPLORER_REDIS_URL was set, which is when the gap surfaced.

# Application code + bundled contracts + vendored club registry.
COPY insight-explorer/explorer/ /app/explorer/
COPY insight-explorer/contracts/ /app/contracts/
COPY insight-explorer/vendor/ /app/vendor/
COPY insight-protos/gen/py /insight-protos/gen/py

# Non-root runtime user matching the Robozão `insight` uid/gid (999:987) so
# the bind-mounted data lake is writable without chown gymnastics.
RUN groupadd -g 987 insight && useradd -u 999 -g 987 -m -d /home/insight insight \
 && mkdir -p /home/insight/data/explorer && chown -R insight:insight /home/insight /app
USER insight

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8090/health || exit 1

# uvicorn serves the API; the app's startup hook launches the scheduler thread
# when EXPLORER_RUN_SCHEDULER=1.
CMD ["python", "-m", "uvicorn", "explorer.api.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8090"]
