# Comandos do dia a dia. Um lugar só, para que README, CI e pessoas usem os
# mesmos — três invocações diferentes do mesmo comando divergem na primeira
# vez que alguém ajusta uma.
.PHONY: infra-destroy install lint format typecheck test test-architecture test-unit \
        run-control-api run-query-api cli check clean

PY ?= python
ARGS ?=

install:
	$(PY) -m pip install -e ".[dev]"

lint:
	$(PY) -m ruff check .

format:
	$(PY) -m ruff check . --fix

typecheck:
	$(PY) -m mypy

test:
	$(PY) -m pytest

test-unit:
	$(PY) -m pytest tests/unit

# Exigem PostgreSQL e object store DE VERDADE. Separados de `test` porque um
# desenvolvedor sem Docker precisa poder rodar a suíte rápida — e porque uma
# suíte que às vezes precisa de infraestrutura e às vezes não é uma suíte que
# ninguém sabe se está passando.
test-integration:
	$(PY) -m pytest tests/integration -m integration

test-performance:
	$(PY) -m pytest tests/performance -m performance -s

# Os limites arquiteturais. Separado porque o CI o roda como gate próprio:
# uma violação de fronteira não deve se esconder no meio de 120 testes.
test-architecture:
	$(PY) -m pytest tests/architecture -m architecture

# O que o CI roda. Ordem deliberada: lint e typecheck falham em segundos e
# pegam a maior parte dos erros, então vêm antes da suíte.
check: lint typecheck test

# --- infraestrutura local ------------------------------------------------
# Só PostgreSQL e MinIO: são os dois que o código exercita hoje.

infra-up:
	docker compose -f infra/docker-compose.yml up -d
	@echo "postgres em localhost:5433 · minio em localhost:9000 (console :9001)"

infra-down:
	docker compose -f infra/docker-compose.yml down

# `down -v` apaga os volumes. Alvo separado e nomeado pelo que faz: um
# `infra-down` que apaga dados destrói um arquivo bruto local sem avisar.
infra-destroy:
	docker compose -f infra/docker-compose.yml down -v

infra-logs:
	docker compose -f infra/docker-compose.yml logs -f

migrate:
	$(PY) -m apps.cli.main migrate

migrate-status:
	$(PY) -m apps.cli.main migrate-status

run-control-api:
	$(PY) -m uvicorn apps.control_api.main:app --host 127.0.0.1 --port 8080 --reload

run-query-api:
	$(PY) -m uvicorn apps.query_api.main:app --host 127.0.0.1 --port 8081 --reload

# make cli ARGS=doctor
cli:
	$(PY) -m apps.cli.main $(ARGS)

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .ruff_cache .pytest_cache .mypy_cache
