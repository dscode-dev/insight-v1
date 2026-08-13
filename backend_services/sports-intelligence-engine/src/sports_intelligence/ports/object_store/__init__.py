"""Armazenamento de objetos — em stream, e sem operação de sobrescrita.

DUAS DECISÕES ESTÃO NA FORMA DESTE PROTOCOLO, e as duas são por ausência.

A PRIMEIRA: NÃO EXISTE `put(key, data: bytes)`. Uma assinatura que recebe
`bytes` obriga o chamador a ter o arquivo inteiro em memória, e a obrigação é
invisível — o código fica curto, funciona com o CSV de teste de 4 KB, e o pico
de memória passa a ser o tamanho do maior arquivo que alguém enviar. O tipo é
o que impede isso: quem só aceita um iterador de blocos não consegue ser
chamado errado.

A SEGUNDA: NÃO EXISTE `update` NEM `delete`. O arquivo bruto é imutável por
contrato (ADR-0004, ADR-0014). Ele é a única cópia do que a fonte de fato
mandou, e é dele que toda reconstrução parte — inclusive a reconstrução que
conserta um erro NOSSO de interpretação. Apagar ou sobrescrever é operação
administrativa deliberada, feita por fora, com quem responde por ela sabendo
o que está fazendo; não é algo que um caminho de código alcance por engano.

`put_stream` GRAVA UMA CHAVE NOVA. Se a chave já existe com o mesmo conteúdo —
o caso normal do retry, já que a chave contém o hash — a implementação pode
tratar como sucesso; ela nunca substitui conteúdo diferente sob a mesma chave,
e a chave endereçada por conteúdo torna essa colisão impossível na prática.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Protocol, final, runtime_checkable


@final
@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    """O que o store sabe sobre um objeto sem baixá-lo.

    `head` DEVOLVE ISTO E NÃO O OBJETO, e a diferença é a razão de o método
    existir: conferir que 4 GB estão gravados não deve custar 4 GB de tráfego.

    `checksum_sha256` é o que o store calculou, quando ele calcula. Nem todo
    backend fornece, e por isso é opcional — e por isso ele NUNCA substitui o
    nosso: o SHA-256 do motor é calculado durante a leitura dos bytes que
    chegaram, e é ele que manda (ADR-0015).
    """

    key: str
    size_bytes: int
    content_type: str | None = None
    etag: str | None = None
    checksum_sha256: str | None = None


@runtime_checkable
class ObjectStorePort(Protocol):
    """S3 ou MinIO, vistos pelo motor como cinco operações."""

    async def put_stream(
        self,
        key: str,
        chunks: Iterator[bytes],
        *,
        content_type: str,
        size_bytes: int,
    ) -> ObjectMetadata:
        """Grava os blocos sob a chave. Devolve o que ficou gravado.

        `size_bytes` É EXIGIDO e não descoberto durante a gravação: os
        backends precisam dele para escolher entre upload simples e
        multipart, e um tamanho conhecido de antemão é também a única forma
        de conferir, no fim, que o que chegou foi o que se esperava.

        A IMPLEMENTAÇÃO NÃO PODE MATERIALIZAR OS BLOCOS NUMA LISTA. É a única
        regra que o protocolo não consegue impor pelo tipo, e por isso está
        escrita: um adapter que faz `b"".join(chunks)` satisfaz a assinatura
        e destrói a propriedade inteira.
        """
        ...

    def open_stream(self, key: str) -> AsyncIterator[bytes]:
        """Lê o objeto em blocos.

        NÃO É `async def`: devolver o iterador diretamente permite
        `async for bloco in store.open_stream(k)` sem o `await` extra que
        todo mundo esquece.
        """
        ...

    async def exists(self, key: str) -> bool: ...

    async def head(self, key: str) -> ObjectMetadata | None:
        """Metadados, ou `None` se a chave não existe.

        `None` E NÃO EXCEÇÃO: perguntar por um objeto que pode não estar lá é
        o caminho normal da reconciliação, e transformar o caso esperado em
        exceção faz o caminho normal parecer falha nos logs.
        """
        ...

    def list_prefix(self, prefix: str) -> AsyncIterator[str]:
        """As chaves sob um prefixo.

        É a metade física da reconciliação do ADR-0017: confrontar o que o
        store tem com o que o registro diz ter.
        """
        ...
