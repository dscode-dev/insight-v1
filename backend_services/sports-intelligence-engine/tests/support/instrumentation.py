"""Contar consultas e medir pico de memória — sem tocar em `src/`.

O PROBLEMA QUE ISTO RESOLVE (§9). «Não há N+1» é hoje uma afirmação sobre a
ASSINATURA dos ports: `teams_by_normalized_names(nomes)` recebe coleção e
devolve coleção, `find_team_by_name(nome)` não existe. Isso reduz o risco e
não o elimina — um laço `for` em volta de uma chamada em massa produz N+1 com
assinatura em massa, e nenhum teste de tipo enxerga isso.

O que enxerga é CONTAR. Se cem mil registros em cem lotes produzem umas
poucas centenas de consultas, o crescimento é por LOTE. Se produzem
centenas de milhares, é por REGISTRO — e a diferença entre os dois números é
grande demais para ser ruído.

ONDE O CONTADOR ENTRA. No pool, e não nos repositórios. `Database.acquire()`
devolve a conexão de `self.pool`; trocar o pool por um proxy faz TODA consulta
de TODO repositório passar pelo contador, inclusive as que forem escritas
depois deste arquivo. Instrumentar repositório a repositório contaria só os
que alguém lembrou de instrumentar — e o N+1 costuma nascer justamente no que
ninguém lembrou.

O PROXY NÃO MUDA COMPORTAMENTO: ele delega tudo por `__getattr__` e só conta
os cinco verbos de consulta do asyncpg no caminho. `transaction()` continua
sendo a do asyncpg, e o `UnitOfWork` continua funcionando.
"""

from __future__ import annotations

import tracemalloc
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, final

from sports_intelligence.adapters.postgres.database import Database

#: Os verbos do asyncpg que vão ao servidor. `executemany` conta como UMA ida
#: — porque é uma: ele faz um round trip com o statement preparado e N
#: conjuntos de argumentos, que é exatamente a diferença que o benchmark
#: existe para provar.
_VERBOS: frozenset[str] = frozenset({"fetch", "fetchrow", "fetchval", "execute", "executemany"})


@final
@dataclass(slots=True)
class ContagemDeConsultas:
    """Quantas foram, e quais. O detalhe é o que permite ver ONDE cresceu."""

    total: int = 0
    por_verbo: dict[str, int] = field(default_factory=dict)
    por_alvo: dict[str, int] = field(default_factory=dict)

    def registrar(self, verbo: str, sql: str) -> None:
        self.total += 1
        self.por_verbo[verbo] = self.por_verbo.get(verbo, 0) + 1
        alvo = _alvo(sql)
        self.por_alvo[alvo] = self.por_alvo.get(alvo, 0) + 1

    @property
    def mais_frequentes(self) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(self.por_alvo.items(), key=lambda p: (-p[1], p[0]))[:8])


def _alvo(sql: str) -> str:
    """O nome da tabela, para o relatório dizer ONDE as consultas foram.

    Heurística e assumidamente simples: pega a palavra após `FROM`, `INTO` ou
    `UPDATE`. Ela é usada para RELATAR, nunca para decidir — um rótulo errado
    aqui não muda contagem nenhuma.
    """
    palavras = sql.replace("\n", " ").split()
    for i, palavra in enumerate(palavras):
        if palavra.upper() in {"FROM", "INTO", "UPDATE"} and i + 1 < len(palavras):
            return palavras[i + 1].strip("(,;").lower()
    return "?"


@final
class _ConexaoContada:
    def __init__(self, real: Any, contagem: ContagemDeConsultas) -> None:
        self._real = real
        self._contagem = contagem

    def __getattr__(self, nome: str) -> Any:
        atributo = getattr(self._real, nome)
        if nome not in _VERBOS:
            return atributo

        async def contando(*args: Any, **kwargs: Any) -> Any:
            self._contagem.registrar(nome, str(args[0]) if args else "")
            return await atributo(*args, **kwargs)

        return contando


@final
class _PoolContado:
    def __init__(self, real: Any, contagem: ContagemDeConsultas) -> None:
        self._real = real
        self._contagem = contagem

    def __getattr__(self, nome: str) -> Any:
        return getattr(self._real, nome)

    async def acquire(self) -> Any:
        return _ConexaoContada(await self._real.acquire(), self._contagem)

    async def release(self, conexao: Any) -> None:
        # DESEMBRULHA ANTES DE DEVOLVER. O pool do asyncpg guarda identidade
        # das conexões que emprestou; devolver o proxy vazaria a conexão real
        # e o pool secaria depois de `max_size` aquisições.
        await self._real.release(getattr(conexao, "_real", conexao))


@asynccontextmanager
async def contando_consultas(database: Database) -> AsyncIterator[ContagemDeConsultas]:
    """Conta toda consulta feita por qualquer repositório dentro do bloco.

    Restaura o pool original ao sair, inclusive por exceção: um pool deixado
    embrulhado faria os testes seguintes contarem consultas de outra pessoa.
    """
    contagem = ContagemDeConsultas()
    original = database.pool
    database._pool = _PoolContado(original, contagem)  # o ponto de entrada da contagem
    try:
        yield contagem
    finally:
        database._pool = original


@final
@dataclass(slots=True)
class Medida:
    """O resultado de uma medição: tempo e pico de memória do bloco."""

    rotulo: str
    segundos: float = 0.0
    pico_bytes: int = 0

    @property
    def pico_mb(self) -> float:
        return self.pico_bytes / (1024 * 1024)

    def por_segundo(self, itens: int) -> float:
        return itens / self.segundos if self.segundos > 0 else float("inf")

    def __str__(self) -> str:
        return f"{self.rotulo}: {self.segundos:.2f}s · pico {self.pico_mb:.1f} MB"


@contextmanager
def medindo(rotulo: str, *, memoria: bool = True) -> Iterator[Medida]:
    """Tempo e pico de memória.

    `tracemalloc` MEDE ALOCAÇÃO PYTHON, não RSS do processo. É a métrica certa
    para a pergunta deste PR — «o lote mantém a memória limitada?» —, porque o
    que cresceria num vazamento de lote são objetos Python. RSS incluiria o
    pool do asyncpg, os buffers do PyArrow e o alocador do sistema, e o número
    diria menos sobre o nosso código.
    """
    medida = Medida(rotulo)
    if memoria:
        tracemalloc.start()
    inicio = perf_counter()
    try:
        yield medida
    finally:
        medida.segundos = perf_counter() - inicio
        if memoria:
            _, pico = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            medida.pico_bytes = pico
