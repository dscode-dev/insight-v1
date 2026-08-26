"""UMA suíte destrutiva por banco, por vez — de performance OU de integração.

O QUE ACONTECEU SEM ISTO, duas vezes, e é o motivo de este módulo existir.

A PRIMEIRA (PR-04): duas suítes de PERFORMANCE rodaram ao mesmo tempo contra o
mesmo PostgreSQL. A segunda chamou `limpar_execucoes`, que dá
`TRUNCATE ... CASCADE`, e a primeira — no meio de um lote — recebeu:

    ForeignKeyViolationError: resolution_decisions.run_id não existe

A SEGUNDA (PR-05.5.1): a suíte de INTEGRAÇÃO rodou durante o benchmark. O
`database` da integração dá `TRUNCATE datasets ... CASCADE` a cada teste, e o
benchmark — no meio da composição de dez mil partidas — recebeu:

    ForeignKeyViolationError: dataset_validation_runs.dataset_id não existe

O motor estava certo nas duas vezes. O ARNÊS é que tinha estado mutável
compartilhado, e a falha se apresentou como se fosse defeito do produto. Um
arnês que mente sobre o produto é pior que um arnês ausente.

A PROTEÇÃO ANTERIOR COBRIA `perf ↔ perf` E NÃO `perf ↔ integração`, porque o
lock morava no `conftest` da performance. Ele mora aqui agora, com UMA chave, e
as duas suítes o tomam: quem chegar depois espera.

POR QUE LOCK CONSULTIVO E NÃO NAMESPACE POR EXECUÇÃO. Um schema por execução
resolveria o conflito e mudaria o que se mede: as migrations rodariam por
suíte, os índices nasceriam frios, e o número deixaria de ser comparável com o
baseline anterior. O lock preserva o cenário e serializa.

POR QUE `session` E NÃO POR TESTE. Com lock por teste, a segunda suíte se
intercalaria entre os testes da primeira — que é exatamente a interferência, só
que mais difícil de enxergar.

ELE FALHA EM VEZ DE PULAR. Um `skip` faria a suíte «passar» sem ter medido nem
provado nada, e o relatório diria verde.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from typing import Any, Final

import pytest

#: A chave do lock consultivo. UM número fixo e nomeado, compartilhado por
#: TODAS as suítes destrutivas: dois literais diferentes em dois lugares seriam
#: dois locks, e dois locks não excluem ninguém.
CHAVE_DO_LOCK: Final[int] = 0x5031_0342

#: Quanto uma segunda suíte espera pela primeira antes de desistir. Generoso de
#: propósito — o benchmark leva dezenas de minutos, e desistir cedo
#: transformaria a proteção no incômodo que faz alguém desligá-la.
ESPERA_MAXIMA_S: Final[float] = float(os.environ.get("SIE_PERF_LOCK_TIMEOUT_SECONDS", "2400"))


@contextmanager
def exclusividade_do_banco(dsn: str, *, rotulo: str) -> Iterator[None]:
    """Toma o lock do banco para esta suíte, e o devolve no fim.

    `rotulo` VAI PARA A MENSAGEM DE ERRO. Quando o conflito acontece, saber
    QUAL suíte está segurando é a diferença entre «rode uma de cada vez» e meia
    hora procurando a regressão no lugar errado.
    """
    import asyncpg

    laco = asyncio.new_event_loop()
    try:
        conexao: Any = laco.run_until_complete(asyncpg.connect(dsn=dsn))
    except Exception as erro:  # noqa: BLE001 — sem banco, o pulo é dos testes
        laco.close()
        pytest.skip(f"sem PostgreSQL para o lock de exclusividade: {erro}")

    try:
        limite = time.monotonic() + ESPERA_MAXIMA_S
        while not laco.run_until_complete(
            conexao.fetchval("SELECT pg_try_advisory_lock($1)", CHAVE_DO_LOCK)
        ):
            if time.monotonic() > limite:
                pytest.fail(
                    f"outra suíte destrutiva está usando este PostgreSQL há mais de "
                    f"{ESPERA_MAXIMA_S:.0f}s (esta é a suíte {rotulo!r}). Isto é "
                    "CONFLITO DE ARNÊS, e não regressão do motor: as suítes de "
                    "integração e de performance compartilham o mesmo banco mutável, "
                    "e uma trunca as tabelas da outra. Rode uma de cada vez ou aponte "
                    "`SIE_TEST_POSTGRES_DSN` para bancos diferentes.",
                    pytrace=False,
                )
            time.sleep(2.0)
        yield
    finally:
        with suppress(Exception):
            laco.run_until_complete(conexao.execute("SELECT pg_advisory_unlock_all()"))
        with suppress(Exception):
            laco.run_until_complete(conexao.close())
        laco.close()
