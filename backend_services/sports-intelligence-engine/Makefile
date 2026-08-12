# Comandos do dia a dia. Um lugar só, para que README, CI e pessoas usem os
# mesmos — três invocações diferentes do mesmo comando divergem na primeira
# vez que alguém ajusta uma.
.PHONY: install lint format typecheck test test-architecture test-unit \
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

# Os limites arquiteturais. Separado porque o CI o roda como gate próprio:
# uma violação de fronteira não deve se esconder no meio de 120 testes.
test-architecture:
	$(PY) -m pytest tests/architecture -m architecture

# O que o CI roda. Ordem deliberada: lint e typecheck falham em segundos e
# pegam a maior parte dos erros, então vêm antes da suíte.
check: lint typecheck test

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
