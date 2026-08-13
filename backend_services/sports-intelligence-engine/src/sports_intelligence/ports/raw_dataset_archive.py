"""O arquivo bruto de datasets, uma camada acima do object store.

POR QUE ESTA ABSTRAÇÃO EXISTE, se já há `ObjectStorePort`. Porque três regras
não são de armazenamento e viveriam espalhadas pelos casos de uso se ele fosse
usado diretamente:

    como a chave é montada          endereçamento por conteúdo
    o hash confere com o registro   verificação pós-gravação
    o bruto nunca é sobrescrito     imutabilidade

Um caso de uso que chama `store.put_stream(f"datasets/raw/{nome}", ...)` está
decidindo a estratégia de chave — e a decisão passa a existir em cada lugar
que grava, divergindo na primeira vez que alguém ajusta um deles. Pior: a
verificação de hash vira opcional na prática, porque é uma linha que dá para
esquecer.

Aqui ela não dá. `store` grava E confere; não existe caminho que grave sem
conferir.

O QUE ESTE PORT NÃO TEM: `delete`, `overwrite`, `move`. O bruto é a evidência
primária, e ela precisa sobreviver inclusive a um erro nosso de normalização —
que é o caso em que ela é mais necessária e o único em que alguém teria a
tentação de "limpar e reimportar".
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Protocol, final, runtime_checkable

from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.datasets.files import DatasetFile


@final
@dataclass(frozen=True, slots=True)
class ArchivedObject:
    """O que ficou gravado, conferido.

    `verified_hash` é o SHA-256 que o motor calculou; `verified_size` é o
    tamanho que o store confirmou. Os dois juntos são a prova de gravação —
    um sem o outro deixa passar o caso em que os bytes certos foram gravados
    pela metade.
    """

    key: str
    verified_hash: ContentHash
    verified_size: int
    already_present: bool

    @property
    def was_written_now(self) -> bool:
        """Se esta chamada de fato gravou, ou apenas confirmou o que já estava.

        Distingue o upload novo do retry convergindo, que é a diferença entre
        uma métrica de tráfego real e uma inflada por reenvios.
        """
        return not self.already_present


@runtime_checkable
class RawDatasetArchivePort(Protocol):
    """A camada bruta de datasets: grava, confere, lê, nunca apaga."""

    async def store(
        self,
        file: DatasetFile,
        chunks: Iterator[bytes],
    ) -> ArchivedObject:
        """Grava os bytes do arquivo e confirma que são os esperados.

        A CHAVE VEM DO `DatasetFile`, não do chamador: ela foi derivada do
        hash no momento em que a intenção foi registrada, e recalculá-la aqui
        criaria uma segunda estratégia de chave para divergir da primeira.

        IDEMPOTENTE POR CONSTRUÇÃO. A chave contém o hash, então reenviar os
        mesmos bytes escreve no mesmo lugar o mesmo conteúdo. Quando a chave
        já existe com o tamanho certo, a implementação confirma sem regravar
        e marca `already_present` — e o retry deixa de custar tráfego.

        LEVANTA se o que foi gravado não confere. Um arquivo cujo hash diverge
        do registrado é a pior coisa que este PR pode encontrar: significaria
        que a evidência guardada não é a que dissemos ter guardado.
        """
        ...

    def open(self, file: DatasetFile) -> AsyncIterator[bytes]:
        """Os bytes, em blocos. É por aqui que a validação lê."""
        ...

    async def verify(self, file: DatasetFile) -> bool:
        """Se os bytes registrados existem no store com o tamanho certo.

        NÃO RELÊ O CONTEÚDO. Verificar o hash de todos os arquivos a cada
        validação custaria uma leitura completa por execução; esta é a
        checagem barata — presença e tamanho — que pega o caso comum, que é
        o objeto que nunca chegou. A conferência de hash acontece na
        gravação, quando os bytes já estão passando de qualquer forma.
        """
        ...
