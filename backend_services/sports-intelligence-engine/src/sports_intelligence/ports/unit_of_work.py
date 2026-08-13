"""Transação — pequena, e explícita sobre o que ela NÃO cobre.

POR QUE ELA EXISTE. Duas escritas precisam acontecer juntas ou não acontecer:
a transição de `VALIDATING` para `VALIDATED` e a gravação do relatório que a
justifica. Se a primeira commita e a segunda não, o dataset fica validado sem
relatório — e a próxima leitura vai procurar o motivo e não achar.

POR QUE ELA É PEQUENA. Um `UnitOfWork` que expõe cada repositório como
propriedade vira o objeto por onde tudo passa, e o resultado conhecido é que
todo caso de uso recebe o UoW inteiro em vez de receber o que usa. Aqui ele é
só um escopo: `async with uow:` abre, sai commitando, sai levantando revertendo.
Os repositórios continuam injetados um a um.

O QUE ELA NÃO COBRE, E É A PARTE IMPORTANTE. O object store NÃO participa
desta transação. Não existe transação distribuída entre PostgreSQL e S3, e o
desenho que finge o contrário produz bytes órfãos ou registros sem bytes, em
silêncio. A saída deste projeto é o protocolo de três fases do ADR-0017:
intenção transacional, gravação física, confirmação transacional — com um
estado no meio (`PENDING`) que diz, o tempo todo, que a janela está aberta.

    dentro da transação    linhas do registro
    fora da transação      bytes no object store
    a ponte               `FileStagingState`, e a reconciliação que o lê
"""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self, runtime_checkable


@runtime_checkable
class UnitOfWorkPort(Protocol):
    """Um escopo transacional sobre o armazenamento relacional.

    A SEMÂNTICA É A DO `async with`: sair normalmente commita, sair por
    exceção reverte. Não há `commit()` público de propósito — um commit
    manual no meio de um bloco é como metade de uma operação atômica vira
    permanente enquanto a outra metade ainda pode falhar.
    """

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None: ...

    async def rollback(self) -> None:
        """Reverte antes do fim do bloco.

        Existe para o caso em que a operação decide desistir sem que isso
        seja uma exceção — validação que encontrou impeditivo e não quer
        persistir nada além do relatório, por exemplo.
        """
        ...
