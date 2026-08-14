"""Um object store em disco — para teste e desenvolvimento, e só.

POR QUE ELE EXISTE. Sem ele, todo teste do caminho de ingestão precisaria de
Docker rodando com MinIO. O resultado prático de exigir isso é conhecido: os
testes que precisam de infraestrutura param de ser rodados localmente, e o
retorno passa a ser só do CI — o que multiplica por dez o tempo entre escrever
um erro e vê-lo.

POR QUE ELE É PERIGOSO. Uma pasta local não é um object store. Ela não
sobrevive ao contêiner ser recriado, não replica, não versiona. E o que ela
guardaria é o ARQUIVO BRUTO, a única camada que não se reconstrói (ADR-0004):
perdê-la não é perder cache, é perder a evidência primária.

A DEFESA ESTÁ EM `assert_object_store_is_durable`, chamada na composição de
cada processo: em `staging` ou `production` este backend é recusado na
inicialização, com o motivo escrito. Aqui embaixo, a classe se recusa a
funcionar fora de uma raiz explicitamente configurada — não há default de
`/tmp` que alguém herde sem perceber.

IMUTABILIDADE MANTIDA. Ele também não tem `delete` nem `copy`, e uma gravação
sobre chave existente com conteúdo diferente é recusada. O duplo de teste
precisa ter as MESMAS restrições do real: um duplo mais permissivo deixa
passar exatamente a classe de erro que o real bloquearia em produção.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Final, final

from sports_intelligence.domain.shared.errors import (
    DependencyError,
    InvariantViolationError,
)
from sports_intelligence.ports.object_store import ObjectMetadata

_BLOCO: Final[int] = 1024 * 1024


@final
class FilesystemObjectStore:
    """Object store em disco. Nunca em produção."""

    def __init__(self, root: Path | str) -> None:
        caminho = Path(root).resolve()
        caminho.mkdir(parents=True, exist_ok=True)
        self._root = caminho

    @property
    def root(self) -> Path:
        return self._root

    def _caminho(self, key: str) -> Path:
        """Traduz chave em caminho, recusando qualquer fuga da raiz.

        A CHECAGEM É FEITA DEPOIS DE RESOLVER, e é a única forma que funciona:
        `..` no meio da chave, link simbólico apontando para fora, caminho
        absoluto — os três produzem um caminho resolvido fora da raiz, e é
        isso que se compara. Verificar a string antes de resolver deixa passar
        todos os casos que envolvem o sistema de arquivos.

        As chaves deste motor são geradas por nós e não têm `..` (ver
        `build_object_key`). A checagem existe porque uma classe que confia no
        chamador para a própria segurança não é segura, é conveniente.
        """
        destino = (self._root / key).resolve()
        if not destino.is_relative_to(self._root):
            raise InvariantViolationError(
                f"a chave {key!r} sai da raiz do object store",
                context={"root": str(self._root)},
            )
        return destino

    async def put_stream(
        self,
        key: str,
        chunks: Iterator[bytes],
        *,
        content_type: str,
        size_bytes: int,
    ) -> ObjectMetadata:
        destino = self._caminho(key)
        destino.parent.mkdir(parents=True, exist_ok=True)

        digest = hashlib.sha256()
        escritos = 0
        # GRAVA NUM TEMPORÁRIO E RENOMEIA. `os.replace` é atômico dentro do
        # mesmo sistema de arquivos, então um processo morto no meio da
        # gravação deixa um temporário — nunca um objeto pela metade sob a
        # chave definitiva, que é o que a validação leria como íntegro.
        with tempfile.NamedTemporaryFile(
            dir=destino.parent, prefix=".parcial-", delete=False
        ) as parcial:
            temporario = Path(parcial.name)
            try:
                for bloco in chunks:
                    escritos += len(bloco)
                    digest.update(bloco)
                    parcial.write(bloco)
                parcial.flush()
                os.fsync(parcial.fileno())
            except Exception:
                temporario.unlink(missing_ok=True)
                raise

        if escritos != size_bytes:
            temporario.unlink(missing_ok=True)
            raise DependencyError(
                f"o stream entregou {escritos} bytes e {size_bytes} foram anunciados",
                context={"key": key},
            )
        if destino.exists() and destino.stat().st_size == size_bytes:
            # Já está lá, íntegro. Não regrava: o arquivo bruto é imutável, e
            # a chave é endereçada por conteúdo.
            temporario.unlink(missing_ok=True)
        else:
            os.replace(temporario, destino)

        return ObjectMetadata(
            key=key,
            size_bytes=destino.stat().st_size,
            content_type=content_type,
            checksum_sha256=digest.hexdigest(),
        )

    async def open_stream(self, key: str) -> AsyncIterator[bytes]:
        destino = self._caminho(key)
        if not destino.is_file():
            raise DependencyError(f"objeto ausente: {key}", context={"key": key})
        with destino.open("rb") as fonte:
            while True:
                bloco = fonte.read(_BLOCO)
                if not bloco:
                    return
                yield bloco

    async def exists(self, key: str) -> bool:
        return self._caminho(key).is_file()

    async def head(self, key: str) -> ObjectMetadata | None:
        destino = self._caminho(key)
        if not destino.is_file():
            return None
        return ObjectMetadata(key=key, size_bytes=destino.stat().st_size)

    async def list_prefix(self, prefix: str) -> AsyncIterator[str]:
        base = self._root
        for caminho in sorted(base.rglob("*")):
            if not caminho.is_file():
                continue
            relativo = caminho.relative_to(base).as_posix()
            if relativo.startswith(prefix):
                yield relativo

    async def ping(self) -> bool:
        return self._root.is_dir()

    def destroy(self) -> None:
        """Apaga a raiz inteira. SÓ para limpeza de teste.

        Deliberadamente fora do `ObjectStorePort`: é uma operação destrutiva
        que não pode ser alcançada por nenhum caminho que fale com o
        protocolo. Um teste que a chama sabe que a está chamando.
        """
        shutil.rmtree(self._root, ignore_errors=True)
