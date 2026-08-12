# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VERSION=2.3.2 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_VIRTUALENVS_OPTIONS_NO_PIP=false

RUN apt-get update \
 && apt-get install --no-install-recommends -y build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

WORKDIR /opt/build

WORKDIR /opt/build/insight-anvil
COPY pyproject.toml poetry.lock ./
COPY anvil /opt/build/insight-anvil/anvil
RUN poetry install --only main

# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/opt/build/insight-anvil/.venv \
    PATH=/opt/build/insight-anvil/.venv/bin:$PATH

RUN groupadd --system --gid 10001 insight \
 && useradd  --system --uid 10001 --gid 10001 --no-create-home insight \
 && mkdir -p /opt/insight

COPY --from=builder /opt/build/insight-anvil     /opt/build/insight-anvil

RUN chown -R insight:insight /opt/build /opt/insight \
 && ln -s /opt/build/insight-anvil/.venv /opt/insight/venv

USER insight:insight
WORKDIR /opt/insight

EXPOSE 8081
ENV LOG_LEVEL=INFO HEALTH_HOST=0.0.0.0 HEALTH_PORT=8081

CMD ["python", "-m", "anvil.worker.anvil_worker"]
