"""PostgreSQL e object store DE VERDADE para os testes de integração.

DUAS FORMAS DE OBTÊ-LOS, e a ordem importa:

    1. o ambiente já oferece    `SIE_TEST_POSTGRES_DSN` apontando para um
                                PostgreSQL que já está de pé — o compose
                                local, ou o serviço do CI. É o caminho
                                rápido, e é o que roda no dia a dia.

    2. Testcontainers           sobe um PostgreSQL descartável. É o caminho
                                de quem clonou o repositório e tem Docker,
                                sem precisar subir nada antes.

    3. nenhum dos dois          os testes são PULADOS, com o motivo dito.

O PULO É DELIBERADO E VISÍVEL. A alternativa seria cair para um duplo em
memória — e aí a suíte ficaria verde sem ter provado nada sobre o que ela
existe para provar: que os bytes chegam ao object store e os metadados ao
PostgreSQL. Um teste de integração que silenciosamente vira teste de unidade é
pior que um teste ausente, porque parece cobertura.

O OBJECT STORE tem o mesmo desenho: MinIO por variável de ambiente, e
`FilesystemObjectStore` quando não há. Aqui a queda para disco é aceitável e
está dita: o que se prova com ele é o protocolo de três fases e a
idempotência, que são lógica nossa. O que ele NÃO prova — multipart, checksum
do S3, paginação de listagem — só o MinIO prova, e há um teste específico
marcado para isso.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest

import sports_intelligence.adapters.postgres.migrations as migrations
from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.config.settings import ObjectStoreSettings, PostgresSettings

RAIZ = Path(__file__).resolve().parents[2]
MIGRATIONS = RAIZ / "migrations"


def _dsn_do_ambiente() -> str | None:
    return os.environ.get("SIE_TEST_POSTGRES_DSN")


@pytest.fixture(scope="session")
def postgres_dsn() -> Iterator[str]:
    """O DSN de um PostgreSQL de verdade, de onde quer que ele venha."""
    do_ambiente = _dsn_do_ambiente()
    if do_ambiente:
        yield do_ambiente
        return

    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip(
            "sem PostgreSQL: defina SIE_TEST_POSTGRES_DSN ou instale testcontainers"
        )

    try:
        with PostgresContainer("postgres:17-alpine", driver=None) as container:
            yield container.get_connection_url()
    except Exception as erro:  # noqa: BLE001 — Docker ausente é motivo de pulo
        pytest.skip(f"Testcontainers não conseguiu subir o PostgreSQL: {erro}")


@pytest.fixture(scope="session")
def _settings_de_postgres(postgres_dsn: str) -> PostgresSettings:
    """Traduz o DSN para `PostgresSettings`.

    Os testes usam o MESMO objeto de configuração que a aplicação usa. Um
    caminho de conexão paralelo só para teste é um caminho que não é testado.
    """
    from urllib.parse import urlparse

    partes = urlparse(postgres_dsn)
    return PostgresSettings(
        host=partes.hostname or "localhost",
        port=partes.port or 5432,
        database=(partes.path or "/postgres").lstrip("/"),
        user=partes.username or "postgres",
        password=partes.password or "postgres",  # type: ignore[arg-type]
    )


@pytest.fixture
async def database(_settings_de_postgres: PostgresSettings) -> AsyncIterator[Database]:
    """Um banco conectado, com o schema aplicado e as tabelas limpas.

    O SCHEMA VEM DAS MIGRATIONS DE VERDADE, não de um `CREATE TABLE` escrito
    no teste. É o que faz a suíte falhar quando uma migration quebra — que é
    o único jeito de descobrir isso antes do deploy.

    A limpeza é `TRUNCATE ... CASCADE` entre testes, e não `DROP SCHEMA`:
    reaplicar as migrations a cada teste custaria segundos por teste, e o que
    se quer isolar é o DADO, não o schema.
    """
    banco = Database(_settings_de_postgres)
    await banco.connect()
    await migrations.migrate(banco, MIGRATIONS)
    async with banco.acquire() as conexao:
        await conexao.execute(
            "TRUNCATE datasets, dataset_audit_log RESTART IDENTITY CASCADE"
        )
    try:
        yield banco
    finally:
        await banco.close()


@pytest.fixture
def object_store(tmp_path: Path) -> Any:
    """O object store dos testes de integração.

    MinIO quando o ambiente o oferece; disco quando não. A escolha é reportada
    pelo nome do fixture no relatório de falha, então nunca é silenciosa.
    """
    endpoint = os.environ.get("SIE_TEST_OBJECT_STORE_ENDPOINT")
    if not endpoint:
        from sports_intelligence.adapters.s3.filesystem import FilesystemObjectStore

        return FilesystemObjectStore(tmp_path / "bruto")

    from sports_intelligence.adapters.s3.object_store import S3ObjectStore

    return S3ObjectStore(
        ObjectStoreSettings(
            backend="s3",  # type: ignore[arg-type]
            endpoint_url=endpoint,
            bucket=os.environ.get("SIE_TEST_OBJECT_STORE_BUCKET", "sie-test"),
            access_key_id=os.environ.get("SIE_TEST_OBJECT_STORE_KEY", "minioadmin"),  # type: ignore[arg-type]
            secret_access_key=os.environ.get(  # type: ignore[arg-type]
                "SIE_TEST_OBJECT_STORE_SECRET", "minioadmin"
            ),
            secure=False,
        )
    )


@pytest.fixture
def minio_only(object_store: Any) -> Any:
    """Pula quando o object store não é MinIO/S3 de verdade."""
    if type(object_store).__name__ != "S3ObjectStore":
        pytest.skip("exige MinIO: defina SIE_TEST_OBJECT_STORE_ENDPOINT")
    return object_store


@pytest.fixture
def prefixo_unico() -> str:
    """Um prefixo por teste, para que execuções paralelas não se cruzem."""
    return uuid.uuid4().hex[:8]
