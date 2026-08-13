"""A recepção dos bytes: hash durante a leitura, memória que não cresce.

O PROBLEMA CONCRETO. Para saber onde gravar um arquivo, precisamos do hash
dele. Para ter o hash, precisamos ler todos os bytes. E um stream só se lê
uma vez. As três coisas juntas empurram para a solução errada:

    conteudo = await request.body()          # 4 GB na RAM
    sha = hashlib.sha256(conteudo)

Ela funciona no CSV de teste de 40 KB e derruba o processo no dump real. Pior:
falha por OOM, que aparece como "o contêiner reiniciou" e não como "o upload
era grande demais".

A SAÍDA É UM BUFFER QUE TRANSBORDA PARA DISCO. `SpooledTemporaryFile` mantém
o conteúdo em memória até um limiar e, passando dele, escreve num arquivo
temporário — transparentemente. Lemos o stream uma vez alimentando três coisas
ao mesmo tempo: o hash, o contador de bytes e o buffer. Depois relemos o
buffer, que é rebobinável, para entregar ao object store.

O PICO DE MEMÓRIA PASSA A SER O LIMIAR, não o tamanho do arquivo. É a regra
central deste PR, e é uma propriedade do desenho, não uma promessa.

O LIMITE DE TAMANHO É VERIFICADO DURANTE A LEITURA, e essa é a única hora em
que ele serve. Conferir `Content-Length` antes não protege — o cabeçalho é do
cliente, e um cliente que mente sobre o tamanho é exatamente o que o limite
existe para conter. Conferir depois de ler tudo é conferir depois do dano.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from types import TracebackType
from typing import IO, Final, Self, final

from sports_intelligence.domain.datasets.content import CHUNK_SIZE, ContentHash
from sports_intelligence.domain.datasets.formats import detect_compression
from sports_intelligence.domain.shared.errors import ValidationError

#: Acima disto, o buffer vai para disco. 8 MiB cobre a esmagadora maioria dos
#: CSVs de temporada sem tocar o disco e mantém o pico por upload concorrente
#: em algo previsível.
SPOOL_THRESHOLD_BYTES: Final[int] = 8 * 1024 * 1024

#: Bytes lidos para farejar o formato antes de qualquer parser. 8 é o
#: suficiente para toda assinatura conhecida; ler mais só adiaria a recusa.
SNIFF_BYTES: Final[int] = 8


@final
@dataclass(frozen=True, slots=True)
class ReceivedUpload:
    """O que a recepção apurou sobre os bytes que chegaram.

    NÃO CARREGA OS BYTES. Ela carrega o buffer que os contém, e o buffer é
    fechado quando o `StreamingReceiver` sai do bloco. Um objeto que
    devolvesse `bytes` aqui reintroduziria pela porta dos fundos exatamente o
    que este módulo existe para evitar.
    """

    content_hash: ContentHash
    size_bytes: int
    head: bytes

    @property
    def is_empty(self) -> bool:
        return self.size_bytes == 0

    @property
    def compression(self) -> str | None:
        """O compactador detectado nos primeiros bytes, se houver.

        Um `.csv.gz` renomeado para `.csv` cai aqui e é recusado com o motivo
        certo. Sem isso ele viraria um CSV de uma coluna com bytes ilegíveis,
        que atravessa a validação como "dado ruim" em vez de "arquivo errado".
        """
        return detect_compression(self.head)


@final
class StreamingReceiver:
    """Recebe um stream, calcula o hash e guarda para reler. Uma vez só.

    USO:

        async with StreamingReceiver(max_bytes=...) as receptor:
            recebido = await receptor.consume(request.stream())
            ...
            arquivo = await archive.store(registro, receptor.chunks())

    O `async with` NÃO É OPCIONAL. Ele é o que garante que o arquivo
    temporário seja removido inclusive quando a gravação falha no meio — e
    falhas no meio de upload são o caso comum, não a exceção.
    """

    def __init__(
        self,
        *,
        max_bytes: int,
        spool_threshold: int = SPOOL_THRESHOLD_BYTES,
        chunk_size: int = CHUNK_SIZE,
    ) -> None:
        if max_bytes < 1:
            raise ValueError(f"max_bytes={max_bytes} inválido")
        self._max_bytes = max_bytes
        self._chunk_size = chunk_size
        self._buffer: IO[bytes] = tempfile.SpooledTemporaryFile(
            max_size=spool_threshold, mode="w+b"
        )
        self._resultado: ReceivedUpload | None = None
        self._fechado = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if not self._fechado:
            self._buffer.close()
            self._fechado = True

    async def consume(self, stream: AsyncIterator[bytes]) -> ReceivedUpload:
        """Lê o stream inteiro uma vez, alimentando hash, contador e buffer.

        O LIMITE É COBRADO A CADA BLOCO. Assim que a soma ultrapassa, a
        leitura para e o resto do stream é abandonado — o cliente recebe o
        erro sem que o servidor tenha aceitado os 4 GB restantes só para
        depois recusá-los.
        """
        if self._resultado is not None:
            raise RuntimeError("este receptor já consumiu um stream")

        digest = hashlib.sha256()
        total = 0
        cabeca = b""
        async for bloco in stream:
            if not bloco:
                continue
            total += len(bloco)
            if total > self._max_bytes:
                raise ValidationError(
                    f"upload excede o limite de {self._max_bytes} bytes "
                    f"(já foram lidos {total})",
                    context={"max_bytes": self._max_bytes},
                )
            if len(cabeca) < SNIFF_BYTES:
                cabeca = (cabeca + bloco)[:SNIFF_BYTES]
            digest.update(bloco)
            self._buffer.write(bloco)

        self._buffer.flush()
        self._resultado = ReceivedUpload(
            content_hash=ContentHash(digest.hexdigest()),
            size_bytes=total,
            head=cabeca,
        )
        return self._resultado

    def chunks(self) -> Iterator[bytes]:
        """Relê o buffer em blocos, do começo.

        SÍNCRONO E NÃO ASSÍNCRONO, de propósito: a origem é um arquivo local
        ou memória, onde não há espera de rede para ceder o loop. Um
        `AsyncIterator` aqui daria a impressão de I/O concorrente que não
        existe e obrigaria todo adapter a lidar com um `async for` que nunca
        cede de verdade.
        """
        if self._resultado is None:
            raise RuntimeError("nada foi consumido ainda")
        if self._fechado:
            raise RuntimeError("o receptor já foi fechado")
        self._buffer.seek(0)
        while True:
            bloco = self._buffer.read(self._chunk_size)
            if not bloco:
                return
            yield bloco

    @property
    def received(self) -> ReceivedUpload:
        if self._resultado is None:
            raise RuntimeError("nada foi consumido ainda")
        return self._resultado


async def chunks_from_path(path: str, *, chunk_size: int = CHUNK_SIZE) -> AsyncIterator[bytes]:
    """Adapta um arquivo local a um stream assíncrono. Para a CLI.

    A CLI LÊ DO DISCO E MESMO ASSIM EM BLOCOS — pela mesma razão da API. Um
    `Path.read_bytes()` aqui faria o comando `upload` carregar o dump inteiro
    na máquina de quem opera, e o limite de memória de um laptop é menor que
    o do servidor, não maior.
    """
    with open(path, "rb") as arquivo:  # noqa: PTH123 — stream, não leitura de conteúdo
        while True:
            bloco = arquivo.read(chunk_size)
            if not bloco:
                return
            yield bloco
