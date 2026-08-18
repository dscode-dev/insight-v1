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

import asyncio
import os
import time
from collections.abc import Iterator
from contextlib import suppress
from typing import Final

import pytest

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.config.settings import PostgresSettings
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


#: A chave do lock consultivo do benchmark. Um número fixo e nomeado: dois
#: literais diferentes em dois lugares seriam dois locks, e dois locks não
#: excluem ninguém.
_CHAVE_DO_LOCK: Final[int] = 0x5031_0342

#: Quanto uma segunda execução espera pela primeira antes de desistir. Generoso
#: de propósito — a suíte inteira leva minutos, e desistir cedo transformaria a
#: proteção no incômodo que faz alguém desligá-la.
_ESPERA_MAXIMA_S: Final[float] = float(
    os.environ.get("SIE_PERF_LOCK_TIMEOUT_SECONDS", "2400")
)


@pytest.fixture(scope="session", autouse=True)
def exclusividade_do_benchmark(_settings_de_postgres: PostgresSettings) -> Iterator[None]:  # noqa: F811
    """UMA suíte de performance por banco, por vez.

    O QUE ACONTECEU SEM ISTO, e é o motivo de a fixture existir. Duas suítes
    rodaram ao mesmo tempo contra o mesmo PostgreSQL. A segunda chamou
    `limpar_execucoes`, que dá `TRUNCATE ... CASCADE` em `resolution_runs`, e a
    primeira — no meio de um lote — recebeu:

        ForeignKeyViolationError: resolution_decisions.run_id não existe

    O motor estava certo. O HARNESS é que tinha estado mutável compartilhado, e
    a falha se apresentou como se fosse regressão de performance do produto.
    Um arnês que mente sobre o produto é pior que um arnês ausente.

    POR QUE LOCK CONSULTIVO E NÃO NAMESPACE POR EXECUÇÃO. Um schema por
    execução resolveria o conflito e mudaria o que se mede: as migrations
    rodariam por suíte, os índices nasceriam frios, e o número deixaria de ser
    comparável com o baseline anterior. O lock preserva o cenário e serializa.

    POR QUE `session` E NÃO POR TESTE. Com lock por teste, a segunda execução
    se intercalaria entre os testes da primeira — que é exatamente a
    interferência, só que mais difícil de enxergar.

    ELE FALHA EM VEZ DE PULAR. Um `skip` faria a suíte «passar» sem ter
    medido nada, e o relatório diria verde. A mensagem diz que o conflito é do
    arnês, para que ninguém procure a regressão no lugar errado.
    """
    import asyncpg

    laco = asyncio.new_event_loop()
    try:
        conexao = laco.run_until_complete(
            asyncpg.connect(dsn=_settings_de_postgres.dsn())
        )
    except Exception as erro:  # noqa: BLE001 — sem banco, o pulo é dos testes
        laco.close()
        pytest.skip(f"sem PostgreSQL para o lock do benchmark: {erro}")

    try:
        limite = time.monotonic() + _ESPERA_MAXIMA_S
        while not laco.run_until_complete(
            conexao.fetchval("SELECT pg_try_advisory_lock($1)", _CHAVE_DO_LOCK)
        ):
            if time.monotonic() > limite:
                pytest.fail(
                    "outra suíte de performance está usando este PostgreSQL há mais "
                    f"de {_ESPERA_MAXIMA_S:.0f}s. Isto é CONFLITO DE ARNÊS, e não "
                    "regressão do motor: as duas suítes compartilham o mesmo banco "
                    "mutável e uma trunca as tabelas da outra. Rode uma de cada vez "
                    "ou aponte `SIE_TEST_POSTGRES_DSN` para bancos diferentes.",
                    pytrace=False,
                )
            time.sleep(2.0)
        yield
    finally:
        with suppress(Exception):
            laco.run_until_complete(
                conexao.execute("SELECT pg_advisory_unlock_all()")
            )
        with suppress(Exception):
            laco.run_until_complete(conexao.close())
        laco.close()


@pytest.fixture
async def banco_semeado(database: Database, corpus: Corpus) -> Database:  # noqa: F811
    """Banco com o registro canônico dentro e as execuções zeradas.

    A ORDEM IMPORTA: limpar DEPOIS de semear apagaria o registro; limpar
    ANTES deixa as execuções do teste anterior fora do caminho e preserva as
    entidades canônicas, que são idempotentes e caras de reescrever (§49).

    A EXCLUSIVIDADE VEM DE `exclusividade_do_benchmark`, que é `autouse` e de
    sessão: quando este `TRUNCATE` roda, nenhuma outra suíte de performance
    está no meio de um lote.
    """
    await limpar_execucoes(database)
    await seed_corpus(database, corpus)
    return database
