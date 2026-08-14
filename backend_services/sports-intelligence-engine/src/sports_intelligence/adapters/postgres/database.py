"""O pool, e como uma conexão transacional chega até um repositório.

O PROBLEMA. Um repositório precisa funcionar de dois jeitos: solto — pega uma
conexão do pool, faz a consulta, devolve — e dentro de uma transação aberta
por um caso de uso, usando A MESMA conexão que a transação abriu. Se ele pegar
outra conexão do pool, a escrita dele fica fora da transação e commita sozinha,
o que anula a atomicidade sem que nada falhe.

TRÊS SAÍDAS POSSÍVEIS, E POR QUE ESTA:

    passar a conexão em cada método       polui toda assinatura do port com um
                                          tipo de infraestrutura, e o port
                                          deixaria de ser agnóstico

    UnitOfWork expondo os repositórios    todo caso de uso passa a receber o
                                          UoW inteiro, e a lista de
                                          dependências deixa de dizer o que
                                          ele realmente usa

    ContextVar com a conexão ativa        o escopo transacional é implícito
                                          para o repositório e explícito para
                                          quem o abre — que é onde a decisão
                                          de fato está

A terceira. `async with uow:` põe a conexão na `ContextVar`; qualquer
repositório chamado dentro do bloco a encontra e a usa; fora do bloco, cada um
pega a sua do pool. `ContextVar` e não variável de módulo porque tarefas
concorrentes do mesmo processo têm contextos separados — uma variável global
faria duas requisições simultâneas compartilharem a transação uma da outra.

SEM ORM, E É DECISÃO (ADR-0003). O SQL é escrito à mão e vive em `sql.py`. Um
ORM traria mapeamento automático, lazy loading e migrações geradas — e traria
junto o acoplamento que faz o modelo de domínio ser desenhado pelo que é fácil
de persistir. Aqui a tradução entre linha e agregado é explícita, e cabe num
arquivo que dá para ler.
"""

from __future__ import annotations

import contextvars
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self, final

from sports_intelligence.config.settings import PostgresSettings
from sports_intelligence.domain.shared.errors import DependencyError

if TYPE_CHECKING:  # pragma: no cover
    pass

#: A conexão da transação em curso, se houver. `None` significa "não há
#: transação aberta neste contexto", que é o caso normal das leituras.
_CONEXAO_ATIVA: contextvars.ContextVar[Any | None] = contextvars.ContextVar(
    "sie_conexao_transacional", default=None
)


@final
class Database:
    """O pool asyncpg, criado uma vez por processo."""

    def __init__(self, settings: PostgresSettings) -> None:
        self._settings = settings
        self._pool: Any | None = None

    async def connect(self) -> None:
        """Abre o pool. Idempotente — chamar duas vezes não cria dois."""
        if self._pool is not None:
            return
        import asyncpg

        try:
            self._pool = await asyncpg.create_pool(
                dsn=self._settings.dsn(),
                min_size=self._settings.pool_min_size,
                max_size=self._settings.pool_max_size,
                # `jit=off`: consultas administrativas são curtas e o custo de
                # compilar JIT supera o de executá-las.
                server_settings={"jit": "off", "application_name": "sports-intelligence"},
            )
        except Exception as erro:
            raise DependencyError(
                f"não foi possível conectar ao PostgreSQL em "
                f"{self._settings.host}:{self._settings.port}: {erro}",
                context={"host": self._settings.host, "database": self._settings.database},
            ) from erro

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> Any:
        if self._pool is None:
            raise DependencyError(
                "o pool do PostgreSQL não foi aberto — chame `connect()` na composição "
                "do processo, não no meio de uma requisição"
            )
        return self._pool

    async def ping(self) -> bool:
        """Se o banco responde. Para o `doctor` e para o readiness."""
        try:
            async with self.pool.acquire() as conexao:
                await conexao.fetchval("SELECT 1")
        except Exception:  # noqa: BLE001 — o diagnóstico nunca derruba
            return False
        return True

    def acquire(self) -> _Aquisicao:
        """A conexão a usar AGORA.

        Dentro de uma transação, é a dela. Fora, uma do pool que volta ao
        pool no fim do bloco. Os dois casos têm a mesma forma de uso, e é o
        que permite ao repositório não saber em qual está.
        """
        return _Aquisicao(self)


@final
class _Aquisicao:
    """Gerente de contexto que devolve a conexão certa e só solta a que pegou."""

    def __init__(self, database: Database) -> None:
        self._database = database
        self._do_pool: Any | None = None

    async def __aenter__(self) -> Any:
        ativa = _CONEXAO_ATIVA.get()
        if ativa is not None:
            return ativa
        self._do_pool = await self._database.pool.acquire()
        return self._do_pool

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # SÓ DEVOLVE O QUE PEGOU. Soltar a conexão da transação aqui a
        # fecharia no meio do bloco de quem a abriu, e o commit aconteceria
        # sobre uma conexão já devolvida ao pool.
        if self._do_pool is not None:
            await self._database.pool.release(self._do_pool)
            self._do_pool = None


@final
class PostgresUnitOfWork:
    """Um escopo transacional. Sair normalmente commita; sair por exceção reverte."""

    def __init__(self, database: Database) -> None:
        self._database = database
        self._conexao: Any | None = None
        self._transacao: Any | None = None
        self._token: contextvars.Token[Any | None] | None = None
        self._revertida = False

    async def __aenter__(self) -> Self:
        if _CONEXAO_ATIVA.get() is not None:
            # TRANSAÇÃO ANINHADA É RECUSADA, e não convertida em savepoint. Um
            # savepoint implícito faz o bloco de dentro parecer atômico
            # quando o de fora ainda pode reverter tudo — e quem escreveu o
            # de dentro não tem como saber disso.
            raise DependencyError(
                "já existe uma transação aberta neste contexto: o escopo transacional "
                "é de um caso de uso, e aninhá-los esconde quem de fato commita"
            )
        self._conexao = await self._database.pool.acquire()
        self._transacao = self._conexao.transaction()
        await self._transacao.start()
        self._token = _CONEXAO_ATIVA.set(self._conexao)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if self._transacao is not None and not self._revertida:
                if exc_type is None:
                    await self._transacao.commit()
                else:
                    await self._transacao.rollback()
        finally:
            if self._token is not None:
                _CONEXAO_ATIVA.reset(self._token)
                self._token = None
            if self._conexao is not None:
                await self._database.pool.release(self._conexao)
                self._conexao = None
            self._transacao = None
            self._revertida = False

    async def rollback(self) -> None:
        if self._transacao is not None and not self._revertida:
            await self._transacao.rollback()
            self._revertida = True
