"""S3 e MinIO por trás do mesmo adapter.

UM ADAPTER PARA OS DOIS, e não é sorte: MinIO implementa a API do S3, então a
diferença entre eles é `endpoint_url`. Ter dois adapters seria manter duas
implementações do mesmo protocolo para acomodar uma variável de ambiente.

`aioboto3` E NÃO `boto3` NUMA THREAD. O boto3 é síncrono; usá-lo aqui exigiria
`run_in_executor` em toda operação, e o upload de um arquivo grande seguraria
uma thread do pool durante minutos. Num processo que também atende HTTP, isso
é latência que aparece em requisições que não têm nada a ver com o upload.

O QUE ESTE ADAPTER NÃO TEM: `delete`, `copy`, `update`. O protocolo não os
declara (ADR-0014), e implementá-los "só por precaução" criaria o caminho de
código que a imutabilidade existe para não ter.
"""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator, Iterator
from typing import IO, Any, Final, final

from sports_intelligence.config.settings import ObjectStoreSettings
from sports_intelligence.domain.shared.errors import DependencyError
from sports_intelligence.ports.object_store import ObjectMetadata

#: Tamanho de bloco na leitura. Igual ao da gravação, pelo mesmo motivo: o
#: pico de memória é o do bloco, e ele precisa ser previsível.
_BLOCO: Final[int] = 1024 * 1024


@final
class S3ObjectStore:
    """O arquivo bruto sobre S3 ou MinIO."""

    def __init__(self, settings: ObjectStoreSettings) -> None:
        self._settings = settings
        self._sessao: Any | None = None

    def _cliente(self) -> Any:
        """Um cliente por operação, como o aioboto3 espera.

        O cliente do aioboto3 é um gerente de contexto assíncrono e não é
        reutilizável entre operações; a sessão é. Guardar o cliente numa
        instância e usá-lo depois é o erro comum, e ele se manifesta como
        conexão fechada no meio de um upload longo.
        """
        import aioboto3

        if self._sessao is None:
            self._sessao = aioboto3.Session()
        return self._sessao.client(
            "s3",
            endpoint_url=self._settings.endpoint_url,
            region_name=self._settings.region,
            aws_access_key_id=self._settings.access_key_id.get_secret_value(),
            aws_secret_access_key=self._settings.secret_access_key.get_secret_value(),
            use_ssl=self._settings.secure,
        )

    async def ensure_bucket(self) -> None:
        """Cria o bucket se não existir. Para desenvolvimento e testes.

        EM PRODUÇÃO O BUCKET É PROVISIONADO FORA, com política de retenção,
        versionamento e cifra decididos por quem responde por eles. Um serviço
        que cria o próprio bucket cria um bucket com os defaults do provedor —
        e o default de retenção costuma ser "nenhuma".
        """
        async with self._cliente() as s3:
            try:
                await s3.head_bucket(Bucket=self._settings.bucket)
            except Exception:  # noqa: BLE001 — inexistente ou sem permissão
                try:
                    await s3.create_bucket(Bucket=self._settings.bucket)
                except Exception as erro:
                    raise DependencyError(
                        f"não foi possível criar o bucket {self._settings.bucket!r}: {erro}"
                    ) from erro

    async def put_stream(
        self,
        key: str,
        chunks: Iterator[bytes],
        *,
        content_type: str,
        size_bytes: int,
    ) -> ObjectMetadata:
        """Grava os blocos. Nunca materializa tudo em memória.

        O `aioboto3` aceita um objeto tipo arquivo em `Body`, e é assim que a
        gravação fica em streaming de verdade: os blocos vão para um
        temporário spooled — memória até um limiar, disco depois — e o boto lê
        dali em pedaços. Um `b"".join(chunks)` aqui satisfaria a assinatura e
        destruiria a propriedade inteira, que é a razão de o protocolo dizer
        isso por escrito.
        """
        # SIM115 suprimido: o buffer é fechado no `finally` logo abaixo. Um `with`
        # aqui aninharia o método inteiro e esconderia a ordem das fases, que
        # é justamente o que este código precisa deixar visível.
        buffer: IO[bytes] = tempfile.SpooledTemporaryFile(  # noqa: SIM115
            max_size=8 * 1024 * 1024, mode="w+b"
        )
        try:
            escritos = 0
            for bloco in chunks:
                escritos += len(bloco)
                buffer.write(bloco)
            buffer.seek(0)

            if escritos != size_bytes:
                raise DependencyError(
                    f"o stream entregou {escritos} bytes e {size_bytes} foram anunciados",
                    context={"key": key},
                )

            async with self._cliente() as s3:
                await s3.put_object(
                    Bucket=self._settings.bucket,
                    Key=key,
                    Body=buffer,
                    ContentType=content_type,
                    # O S3 calcula e devolve este checksum, e ele é confrontado
                    # com o nosso na camada acima. Segunda opinião, não
                    # autoridade: o nosso foi calculado sobre o que chegou ao
                    # motor, o dele sobre o que chegou ao bucket.
                    ChecksumAlgorithm="SHA256",
                )
                cabeca = await s3.head_object(Bucket=self._settings.bucket, Key=key)
        finally:
            buffer.close()

        return ObjectMetadata(
            key=key,
            size_bytes=int(cabeca["ContentLength"]),
            content_type=cabeca.get("ContentType"),
            etag=str(cabeca.get("ETag", "")).strip('"') or None,
            checksum_sha256=_sha256_hex(cabeca.get("ChecksumSHA256")),
        )

    async def open_stream(self, key: str) -> AsyncIterator[bytes]:
        """Lê o objeto em blocos.

        `async def` COM `yield` é um gerador assíncrono, e chamá-lo devolve o
        iterador sem `await` — que é o que o protocolo declara.
        """
        async with self._cliente() as s3:
            try:
                resposta = await s3.get_object(Bucket=self._settings.bucket, Key=key)
            except Exception as erro:
                raise DependencyError(
                    f"não foi possível ler {key!r} do arquivo bruto: {erro}",
                    context={"key": key},
                ) from erro
            corpo = resposta["Body"]
            while True:
                bloco = await corpo.read(_BLOCO)
                if not bloco:
                    return
                yield bloco

    async def exists(self, key: str) -> bool:
        return await self.head(key) is not None

    async def head(self, key: str) -> ObjectMetadata | None:
        async with self._cliente() as s3:
            try:
                cabeca = await s3.head_object(Bucket=self._settings.bucket, Key=key)
            except Exception:  # noqa: BLE001 — ausência é resposta, não falha
                return None
        return ObjectMetadata(
            key=key,
            size_bytes=int(cabeca["ContentLength"]),
            content_type=cabeca.get("ContentType"),
            etag=str(cabeca.get("ETag", "")).strip('"') or None,
            checksum_sha256=_sha256_hex(cabeca.get("ChecksumSHA256")),
        )

    async def list_prefix(self, prefix: str) -> AsyncIterator[str]:
        """As chaves sob um prefixo, paginadas.

        PAGINADO E NÃO `list_objects_v2` DIRETO: a chamada crua devolve no
        máximo mil chaves e um marcador, e quem ignora o marcador lista mil e
        acha que acabou — que é como uma reconciliação conclui que não há
        órfãos num bucket com dez mil objetos.
        """
        async with self._cliente() as s3:
            paginador = s3.get_paginator("list_objects_v2")
            async for pagina in paginador.paginate(Bucket=self._settings.bucket, Prefix=prefix):
                for objeto in pagina.get("Contents", []):
                    yield str(objeto["Key"])

    async def ping(self) -> bool:
        """Se o bucket responde. Para o `doctor` e o readiness."""
        try:
            async with self._cliente() as s3:
                await s3.head_bucket(Bucket=self._settings.bucket)
        except Exception:  # noqa: BLE001 — diagnóstico nunca derruba
            return False
        return True


def _sha256_hex(bruto: str | None) -> str | None:
    """O checksum do S3 vem em base64; o nosso é hexadecimal.

    Traduzir aqui é o que permite à camada acima comparar os dois sem saber
    que existem duas codificações. Sem isso, a comparação sempre falharia — e
    falharia dizendo que os bytes divergem, que é o pior alarme falso possível
    neste PR.
    """
    if not bruto:
        return None
    import base64
    import binascii

    try:
        return base64.b64decode(bruto).hex()
    except (binascii.Error, ValueError):  # pragma: no cover
        return None
