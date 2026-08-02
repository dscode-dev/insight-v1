# syntax=docker/dockerfile:1.7
#
# Build context: modules_v1/

# ============================================================================
# Builder
# ============================================================================

FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VERSION=2.3.2 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_VIRTUALENVS_OPTIONS_NO_PIP=false

# HDBSCAN compiles from source.
# XGBoost + LightGBM use OpenMP.
RUN apt-get update \
 && apt-get install --no-install-recommends -y \
    build-essential \
    gcc \
    g++ \
    libgomp1 \
 && rm -rf /var/lib/apt/lists/*

ENV POETRY_REQUESTS_TIMEOUT=300 \
    PIP_DEFAULT_TIMEOUT=300

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

WORKDIR /opt/build

COPY insight-atlas/pyproject.toml insight-atlas/poetry.lock ./
COPY insight-atlas/atlas ./atlas
COPY insight-atlas/migrations ./migrations
COPY insight-protos/gen/py /opt/insight-protos/gen/py

RUN poetry install --only main

# ============================================================================
# Runtime
# ============================================================================

FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/opt/build/.venv \
    PATH=/opt/build/.venv/bin:$PATH

RUN apt-get update \
 && apt-get install --no-install-recommends -y \
    libgomp1 \
 && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 insight \
 && useradd --system --uid 10001 --gid 10001 --no-create-home insight

RUN mkdir -p \
    /opt/insight \
    /var/atlas/artifacts \
    /var/atlas/datasets

COPY --from=builder /opt/build /opt/build
COPY --from=builder /opt/insight-protos /opt/insight-protos

RUN chown -R insight:insight \
    /opt/build \
    /opt/insight \
    /var/atlas

COPY --chown=insight:insight insight-atlas/scripts /opt/build/scripts

RUN ln -s /opt/build/.venv /opt/insight/venv

USER insight:insight

WORKDIR /opt/build

EXPOSE 8085

ENV LOG_LEVEL=INFO \
    HEALTH_HOST=0.0.0.0 \
    HEALTH_PORT=8085

VOLUME ["/var/atlas/artifacts"]
VOLUME ["/var/atlas/datasets"]

HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=3 \
CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8085/live',timeout=2).status==200 else 1)"

CMD ["uvicorn", "atlas.main:app", "--host", "0.0.0.0", "--port", "8085"]
