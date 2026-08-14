"""PostgreSQL e object store reais também para os benchmarks (§11).

AS FIXTURES SÃO AS MESMAS DA INTEGRAÇÃO, importadas em vez de copiadas. Uma
segunda definição divergiria — e o dia em que a de integração ganhasse
Testcontainers e a de performance não, o benchmark passaria a rodar contra
outro banco sem que ninguém percebesse.

O QUE ESTE ARQUIVO NÃO FAZ é cair para duplo em memória quando o banco falta.
Um benchmark que mede repositório falso mede a si mesmo. Sem PostgreSQL, os
testes que precisam dele PULAM, com o motivo dito — a mesma decisão do PR-02.
"""

from __future__ import annotations

import pytest

from sports_intelligence.adapters.postgres.database import Database
from tests.integration.conftest import (  # noqa: F401 — fixtures, não símbolos
    _settings_de_postgres,
    database,
    object_store,
    postgres_dsn,
    prefixo_unico,
)
from tests.support.corpus import Corpus, build_corpus
from tests.support.registry_seed import limpar_execucoes, seed_corpus


@pytest.fixture(scope="session")
def corpus() -> Corpus:
    """O registro canônico do benchmark. Construído UMA vez por sessão.

    Construir por teste custaria segundos por teste e não isolaria nada: o
    corpus é derivado por `uuid5`, então ele é o mesmo objeto lógico em toda
    construção.
    """
    return build_corpus()


@pytest.fixture
async def banco_semeado(database: Database, corpus: Corpus) -> Database:  # noqa: F811
    """Banco com o registro canônico dentro e as execuções zeradas.

    A ORDEM IMPORTA: limpar DEPOIS de semear apagaria o registro; limpar
    ANTES deixa as execuções do teste anterior fora do caminho e preserva as
    entidades canônicas, que são idempotentes e caras de reescrever (§49).
    """
    await limpar_execucoes(database)
    await seed_corpus(database, corpus)
    return database
