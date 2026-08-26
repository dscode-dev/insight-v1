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
        pytest.skip("sem PostgreSQL: defina SIE_TEST_POSTGRES_DSN ou instale testcontainers")

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


@pytest.fixture(scope="session", autouse=True)
def exclusividade_da_integracao(
    _settings_de_postgres: PostgresSettings,
) -> Iterator[None]:
    """UMA suíte destrutiva por banco, por vez — e a integração É destrutiva.

    O `database` abaixo dá `TRUNCATE ... CASCADE` a CADA teste. Rodar isso ao
    mesmo tempo que o benchmark faz uma suíte arrancar as tabelas debaixo da
    outra, e a falha se apresenta como defeito do motor. Aconteceu no
    PR-05.5.1, e os números daquela execução foram descartados.

    O LOCK É O MESMO DA PERFORMANCE, e essa é a correção: uma chave só, tomada
    pelas duas suítes. Quem chegar depois espera.
    """
    from tests.support.db_exclusivity import exclusividade_do_banco

    with exclusividade_do_banco(_settings_de_postgres.dsn(), rotulo="integração"):
        yield


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
            # `historical_feature_datasets` NÃO cai por cascata de `datasets`:
            # ele não tem chave estrangeira para lá, e é identidade própria
            # (PR-05.5.1). Sem ele na lista, um dataset criado por um teste
            # sobrevive para o próximo — e o próximo passa a exercitar o
            # caminho «já existe» em vez do caminho de criação.
            "TRUNCATE datasets, dataset_audit_log, historical_feature_datasets "
            "RESTART IDENTITY CASCADE"
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


# ============================== o dataset de features (PR-05.5.1) ==
#
# ELES MORAM AQUI, e não num módulo de teste: dois E2E os usam — o do caminho
# feliz e o da cadeia de integridade —, e importar fixture de um arquivo de
# teste para outro faz o `pytest` registrar a mesma função duas vezes.


@pytest.fixture
async def publicado(database: Database, object_store: Any) -> dict[str, Any]:
    """O corpus READY do PR-05.2, pronto para virar dataset de features."""
    from tests.integration.test_match_state_e2e import montar_corpus_publicado

    return await montar_corpus_publicado(database, object_store)


@pytest.fixture
async def construido(
    database: Database, object_store: Any, publicado: dict[str, Any]
) -> dict[str, Any]:
    """Uma versão do dataset já materializada, parada em `VALIDATING`."""
    from tests.support.dataset_e2e import Montagem, construir_versao

    montagem = Montagem(database, object_store)
    saida = await construir_versao(montagem, publicado)
    return {"montagem": montagem, "saida": saida, "publicado": publicado}


# ============================ o dataset normalizado (PR-05.5.2) ==


@pytest.fixture
async def cru_publicado(construido: dict[str, Any]) -> dict[str, Any]:
    """A versão crua levada a `READY` — o insumo do ajuste.

    ELA EXISTE PORQUE O AJUSTE RECUSA UMA VERSÃO NÃO PUBLICADA (§26): a escala
    sairia sobre linhas que ainda podem mudar, e a impressão do ajuste
    apontaria para um conteúdo que deixou de existir.
    """
    from tests.support.normalized_e2e import publicar_versao_crua

    publicada = await publicar_versao_crua(construido)
    return {**construido, "versao_crua": publicada}


@pytest.fixture
async def normalizado(
    database: Database, object_store: Any, cru_publicado: dict[str, Any]
) -> dict[str, Any]:
    """O ajuste feito e conferido, sobre a versão crua publicada."""
    from tests.support.normalized_e2e import ATOR, MontagemNormalizada

    crua = cru_publicado["versao_crua"]
    montagem = MontagemNormalizada(
        database,
        object_store,
        reference_end_exclusive=crua.spec.reference_end_exclusive,
    )
    ajuste = await montagem.ajustar.execute(
        source_version_id=crua.id,
        raw_dataset_name=crua.spec.space_name and "match-state-raw",
        actor=ATOR,
    )
    return {**cru_publicado, "montagem_n": montagem, "ajuste": ajuste}
