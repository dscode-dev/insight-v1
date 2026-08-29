"""Contar TODA leitura de armazenamento durante a agregação — e exigir zero.

O QUE O §28 PEDE NÃO É UMA PROMESSA DE DESENHO, e sim uma medição. «A agregação
é uma transformação pura» é hoje verdade por construção — o pacote de domínio
não importa adapter nenhum, e a guarda de arquitetura prova isso. Mas o caminho
de aplicação passa por objetos que TÊM acesso a armazenamento, e uma leitura
preguiçosa disparada por um atributo do resultado não apareceria em nenhuma
guarda de import.

    o que a guarda de arquitetura prova   o pacote não PODE ler
    o que este módulo prova               a execução não LEU

Os dois são necessários, e nenhum substitui o outro.

## Três fontes, três contadores

    PostgreSQL   o proxy de pool que o `instrumentation` já usa
    object store um proxy sobre as cinco operações do port
    Parquet      `pq.ParquetFile` e `pq.read_table`, trocados no módulo

O TERCEIRO CONTADOR EXISTE PORQUE O SEGUNDO NÃO BASTA. Um `ParquetFile` sobre um
arquivo local não passa pelo object store, e contar só o store daria zero por
não estar olhando. Todos os pontos de leitura em `src/` fazem `import
pyarrow.parquet as pq` DENTRO da função, então trocar o atributo do módulo é
visto por toda chamada posterior — inclusive as escritas depois deste arquivo.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, final


@final
class LojaContada:
    """Proxy do object store que conta cada operação do port.

    ELE DELEGA TUDO E NÃO MUDA COMPORTAMENTO. `open_stream` e `list_prefix` não
    são corrotinas — devolvem iteradores assíncronos —, e embrulhá-las com
    `async def` quebraria `async for` em todo chamador.
    """

    def __init__(self, real: Any) -> None:
        self._real = real
        self.operacoes: int = 0
        self.por_verbo: dict[str, int] = {}

    def _conta(self, verbo: str) -> None:
        self.operacoes += 1
        self.por_verbo[verbo] = self.por_verbo.get(verbo, 0) + 1

    def __getattr__(self, nome: str) -> Any:
        # O que o port não declara passa direto, sem contagem: são detalhes do
        # adapter (caminho em disco, cliente boto) e não leituras de dados.
        return getattr(self._real, nome)

    async def put_stream(self, *args: Any, **kwargs: Any) -> Any:
        self._conta("put_stream")
        return await self._real.put_stream(*args, **kwargs)

    def open_stream(self, key: str) -> AsyncIterator[bytes]:
        self._conta("open_stream")
        return self._real.open_stream(key)

    async def exists(self, key: str) -> bool:
        self._conta("exists")
        return bool(await self._real.exists(key))

    async def head(self, key: str) -> Any:
        self._conta("head")
        return await self._real.head(key)

    def list_prefix(self, prefix: str) -> AsyncIterator[str]:
        self._conta("list_prefix")
        return self._real.list_prefix(prefix)


@final
@dataclass(slots=True)
class ContagemDeParquet:
    total: int = 0
    por_ponto: dict[str, int] = field(default_factory=dict)

    def registrar(self, ponto: str) -> None:
        self.total += 1
        self.por_ponto[ponto] = self.por_ponto.get(ponto, 0) + 1


@contextmanager
def contando_parquet() -> Iterator[ContagemDeParquet]:
    """Conta abertura de Parquet dentro do bloco. Restaura sempre ao sair."""
    import pyarrow.parquet as pq

    contagem = ContagemDeParquet()
    arquivo_original = pq.ParquetFile
    tabela_original = pq.read_table

    def arquivo(*args: Any, **kwargs: Any) -> Any:
        contagem.registrar("ParquetFile")
        return arquivo_original(*args, **kwargs)

    def tabela(*args: Any, **kwargs: Any) -> Any:
        contagem.registrar("read_table")
        return tabela_original(*args, **kwargs)

    pq.ParquetFile = arquivo  # type: ignore[misc, assignment]
    pq.read_table = tabela  # type: ignore[assignment]
    try:
        yield contagem
    finally:
        pq.ParquetFile = arquivo_original  # type: ignore[misc]
        pq.read_table = tabela_original  # type: ignore[assignment]


@final
@dataclass(slots=True)
class LeiturasDurante:
    """Quantas leituras de cada fonte houve dentro do bloco medido."""

    postgres: int = 0
    objetos: int = 0
    parquet: int = 0
    detalhe_postgres: dict[str, int] = field(default_factory=dict)
    detalhe_objetos: dict[str, int] = field(default_factory=dict)
    detalhe_parquet: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.postgres + self.objetos + self.parquet

    def __str__(self) -> str:
        return (
            f"postgres={self.postgres} objetos={self.objetos} parquet={self.parquet}"
            f"{'' if self.total == 0 else f' · {self.detalhe_postgres} {self.detalhe_objetos}'}"
        )


@contextmanager
def sem_leituras(database: Any, loja: LojaContada) -> Iterator[LeiturasDurante]:
    """Mede as três fontes dentro do bloco. Quem afirma o zero é o teste.

    ELE NÃO ASSERTA NADA. Devolver o número em vez de falhar aqui deixa o teste
    dizer O QUE estava medindo — e um contador que falha sozinho dentro de um
    `with` produz um traceback que aponta para este arquivo, e não para a
    execução que leu.
    """
    from tests.support.instrumentation import ContagemDeConsultas, _PoolContado

    leituras = LeiturasDurante()
    contagem_sql = ContagemDeConsultas()
    objetos_antes = loja.operacoes
    original = database.pool
    database._pool = _PoolContado(original, contagem_sql)
    try:
        with contando_parquet() as contagem_parquet:
            yield leituras
    finally:
        database._pool = original
        leituras.postgres = contagem_sql.total
        leituras.detalhe_postgres = dict(contagem_sql.por_alvo)
        leituras.objetos = loja.operacoes - objetos_antes
        leituras.detalhe_objetos = dict(loja.por_verbo)
        leituras.parquet = contagem_parquet.total
        leituras.detalhe_parquet = dict(contagem_parquet.por_ponto)
