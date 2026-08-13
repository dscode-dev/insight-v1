"""A implementação do arquivo bruto: grava, confere, e nunca sobrescreve.

ELA NÃO É UM ADAPTER, e a distinção importa para quem for procurá-la. Um
adapter fala com uma tecnologia — S3, MinIO, disco. Esta classe fala com um
PORT (`ObjectStorePort`) e acrescenta as três regras que são do motor, não do
armazenamento: como a chave é montada, que o hash é conferido, e que o bruto
é imutável. Trocar S3 por MinIO troca o adapter e não toca este arquivo.

A ORDEM DAS OPERAÇÕES É O QUE PROTEGE A EVIDÊNCIA:

    1. já existe com o tamanho certo?   →  confirma sem regravar (retry)
    2. grava em blocos
    3. confere tamanho contra o registro
    4. só então declara gravado

O passo 3 não é cerimônia. Um upload que se interrompe no meio produz um
objeto menor, e sem a conferência ele fica lá parecendo íntegro — com o hash
certo no nome da chave, porque o hash foi calculado sobre os bytes que
CHEGARAM, não sobre os que foram gravados.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Iterator
from typing import final

from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.datasets.files import DatasetFile
from sports_intelligence.domain.shared.errors import (
    DependencyError,
    InvariantViolationError,
)
from sports_intelligence.ports.object_store import ObjectStorePort
from sports_intelligence.ports.raw_dataset_archive import ArchivedObject


@final
class RawDatasetArchive:
    """O arquivo bruto de datasets sobre um object store qualquer."""

    def __init__(self, store: ObjectStorePort) -> None:
        self._store = store

    async def store(self, file: DatasetFile, chunks: Iterator[bytes]) -> ArchivedObject:
        """Grava os bytes e confirma que são os que foram registrados."""
        existente = await self._store.head(file.object_key)
        if existente is not None:
            # O RETRY CONVERGINDO. A chave contém o hash do conteúdo, então
            # um objeto já presente nesta chave só pode ter estes bytes — a
            # menos que a gravação anterior tenha parado no meio, que é
            # exatamente o que o tamanho denuncia.
            if existente.size_bytes == file.size_bytes:
                return ArchivedObject(
                    key=file.object_key,
                    verified_hash=file.content_hash,
                    verified_size=existente.size_bytes,
                    already_present=True,
                )
            # Objeto truncado de uma tentativa anterior. Regravar sob a mesma
            # chave é legítimo e NÃO fere a imutabilidade: o conteúdo alvo é
            # o mesmo — o hash está no caminho —, o que havia lá era um
            # fragmento, e um fragmento nunca foi evidência de nada.
            pass

        try:
            gravado = await self._store.put_stream(
                file.object_key,
                chunks,
                content_type=file.media_type,
                size_bytes=file.size_bytes,
            )
        except Exception as erro:  # noqa: BLE001 — traduzir a falha do store
            raise DependencyError(
                f"falha ao gravar {file.safe_filename!r} no arquivo bruto: {erro}",
                context={"object_key": file.object_key},
            ) from erro

        if gravado.size_bytes != file.size_bytes:
            # A EVIDÊNCIA NÃO É A QUE DISSEMOS TER GUARDADO. Invariante e não
            # validação: não é entrada ruim do usuário, é o motor tendo
            # afirmado algo falso sobre o próprio armazenamento.
            raise InvariantViolationError(
                f"gravamos {gravado.size_bytes} bytes e registramos {file.size_bytes} "
                f"para {file.safe_filename!r} — o arquivo bruto não confere com o registro",
                context={
                    "object_key": file.object_key,
                    "expected": file.size_bytes,
                    "stored": gravado.size_bytes,
                },
            )

        # Quando o backend calcula o próprio checksum, ele é confrontado com
        # o nosso — e o NOSSO manda (ADR-0015). O do backend é uma segunda
        # opinião útil, não a autoridade: ele foi calculado sobre o que
        # chegou ao backend, e o nosso sobre o que chegou ao motor.
        if gravado.checksum_sha256 and gravado.checksum_sha256 != file.content_hash.value:
            raise InvariantViolationError(
                f"o object store reporta SHA-256 {gravado.checksum_sha256[:12]} e "
                f"o motor calculou {file.content_hash.short}",
                context={"object_key": file.object_key},
            )

        return ArchivedObject(
            key=file.object_key,
            verified_hash=file.content_hash,
            verified_size=gravado.size_bytes,
            already_present=False,
        )

    def open(self, file: DatasetFile) -> AsyncIterator[bytes]:
        return self._store.open_stream(file.object_key)

    async def verify(self, file: DatasetFile) -> bool:
        metadados = await self._store.head(file.object_key)
        return metadados is not None and metadados.size_bytes == file.size_bytes

    async def recompute_hash(self, file: DatasetFile) -> ContentHash:
        """Relê o objeto inteiro e recalcula o hash.

        CARO, E POR ISSO NÃO É CHAMADO NA VALIDAÇÃO NORMAL. Existe para a
        auditoria profunda — provar, para alguém que precisa da prova, que os
        bytes guardados hoje são os mesmos que registramos naquele dia. É a
        operação que dá sentido a "evidência imutável"; fazê-la a cada
        validação transformaria cada execução numa leitura completa do
        arquivo bruto.
        """
        digest = hashlib.sha256()
        async for bloco in self._store.open_stream(file.object_key):
            digest.update(bloco)
        return ContentHash(digest.hexdigest())
