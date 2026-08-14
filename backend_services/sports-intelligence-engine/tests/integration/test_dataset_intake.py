"""O fluxo de intake contra PostgreSQL e object store de verdade.

O QUE SÓ ESTES TESTES PODEM PROVAR, e nenhum duplo prova:

    bytes  →  object store          gravados, relidos, conferidos
    metadados  →  PostgreSQL        com as constraints valendo
    idempotência                     imposta pelo banco, não por Python
    atomicidade                      a transação de fato commita e reverte

Os testes de unidade exercitam a lógica com duplos que imitam as constraints.
Estes exercitam as constraints. A diferença aparece quando o duplo e o banco
discordam — e é aí que o teste de unidade fica verde e a produção quebra.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest

from sports_intelligence.adapters.event_bus import CollectingEventPublisher
from sports_intelligence.adapters.postgres.audit import PostgresAuditLog
from sports_intelligence.adapters.postgres.database import Database, PostgresUnitOfWork
from sports_intelligence.adapters.postgres.dataset_registry import (
    PostgresDatasetFileRepository,
    PostgresDatasetManifestRepository,
    PostgresDatasetRepository,
    PostgresDatasetValidationRepository,
)
from sports_intelligence.application.use_cases.datasets import (
    AttachDatasetFile,
    ListDatasets,
    RegisterDataset,
    StageDataset,
    ValidateDataset,
)
from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.datasets.formats import DatasetFormat
from sports_intelligence.domain.datasets.lifecycle import DatasetLifecycle
from sports_intelligence.domain.datasets.models import DatasetFilter, Page
from sports_intelligence.domain.datasets.source import DatasetSource
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.errors import ConflictError, DependencyError
from sports_intelligence.domain.shared.identity import ProviderId
from sports_intelligence.domain.shared.provenance import LicenseClass, SourceType
from sports_intelligence.domain.shared.temporal import Instant, instant
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.ingestion.historical.raw_archive import RawDatasetArchive
from sports_intelligence.ingestion.validation.structural import (
    StructuralValidator,
    ValidationLimits,
)
from sports_intelligence.ports.clock import FrozenClock

pytestmark = pytest.mark.integration

AGORA: Instant = instant(datetime(2026, 8, 13, 12, 0, tzinfo=UTC))
V1 = DatasetVersion(major=1, minor=0)
ATOR = Actor(id="darlan", kind=ActorKind.HUMAN_OPERATOR)

CSV_BOM = (
    b"Date,HomeTeam,AwayTeam,FTHG,FTAG\n"
    b"2019-08-09,Liverpool,Norwich,4,1\n"
    b"2019-08-10,West Ham,Man City,0,5\n"
)
CSV_RUIM = b"Date,HomeTeam,AwayTeam\n2019-08-09,Liverpool\n2019-08-10\nx\ny\nz\n"


async def stream(dados: bytes, bloco: int = 16) -> AsyncIterator[bytes]:
    for i in range(0, len(dados), bloco):
        yield dados[i : i + bloco]


class Pilha:
    """O grafo real: adapters de verdade dos dois lados."""

    def __init__(self, database: Database, object_store: Any, sufixo: str) -> None:
        self.sufixo = sufixo
        self.clock = FrozenClock(AGORA)
        self.store = object_store
        self.archive = RawDatasetArchive(object_store)
        self.datasets = PostgresDatasetRepository(database)
        self.files = PostgresDatasetFileRepository(database)
        self.validations = PostgresDatasetValidationRepository(database)
        self.manifests = PostgresDatasetManifestRepository(database)
        self.audit = PostgresAuditLog(database)
        self.publisher = CollectingEventPublisher()

        self.register = RegisterDataset(
            datasets=self.datasets,
            clock=self.clock,
            audit=self.audit,
            publisher=self.publisher,
        )
        self.attach = AttachDatasetFile(
            datasets=self.datasets,
            files=self.files,
            archive=self.archive,
            clock=self.clock,
            audit=self.audit,
            publisher=self.publisher,
            max_file_size_bytes=8 * 1024 * 1024,
        )
        self.validate = ValidateDataset(
            datasets=self.datasets,
            files=self.files,
            validations=self.validations,
            manifests=self.manifests,
            validator=StructuralValidator(
                archive=self.archive,
                clock=self.clock,
                limits=ValidationLimits(
                    max_file_size_bytes=8 * 1024 * 1024,
                    max_rows_per_file=1_000_000,
                    max_issues=100,
                ),
            ),
            clock=self.clock,
            audit=self.audit,
            publisher=self.publisher,
            uow=PostgresUnitOfWork(database),
        )
        self.stage = StageDataset(
            datasets=self.datasets,
            validations=self.validations,
            clock=self.clock,
            audit=self.audit,
            publisher=self.publisher,
        )
        self.listing = ListDatasets(datasets=self.datasets)

    async def registrar(self, nome: str | None = None, **mudancas: Any) -> Any:
        argumentos: dict[str, Any] = {
            "actor": ATOR,
            "name": nome or f"premier-{self.sufixo}",
            "version": V1,
            "source": DatasetSource(
                source_name="football-data.co.uk",
                source_type=SourceType.OPEN_DATA,
                license_class=LicenseClass.ATTRIBUTION_REQUIRED,
                retrieved_at=instant(datetime(2026, 8, 1, tzinfo=UTC)),
                provider_id=ProviderId("football_data"),
                source_url="https://www.football-data.co.uk/englandm.php",
            ),
            "declared_competitions": frozenset({CompetitionCode.PREMIER_LEAGUE}),
            "declared_seasons": ("2019-2020", "2020-2021"),
        }
        argumentos.update(mudancas)
        return await self.register.execute(**argumentos)


@pytest.fixture
async def pilha(database: Database, object_store: Any, prefixo_unico: str) -> Pilha:
    if hasattr(object_store, "ensure_bucket"):
        await object_store.ensure_bucket()
    return Pilha(database, object_store, prefixo_unico)


class TestMigrations:
    async def test_schema_esta_aplicado_e_o_checksum_confere(
        self, database: Database
    ) -> None:
        from sports_intelligence.adapters.postgres import migrations
        from tests.integration.conftest import MIGRATIONS

        estados = await migrations.status(database, MIGRATIONS)
        assert estados
        assert all(e.applied for e in estados)
        assert all(e.checksum_matches for e in estados)

    async def test_reaplicar_nao_faz_nada(self, database: Database) -> None:
        from sports_intelligence.adapters.postgres import migrations
        from tests.integration.conftest import MIGRATIONS

        assert await migrations.migrate(database, MIGRATIONS) == ()

    async def test_migration_modificada_e_recusada(
        self, database: Database, tmp_path: Any
    ) -> None:
        """O banco e o repositório discordando é silencioso até a primeira
        consulta usar o que ninguém criou."""
        from sports_intelligence.adapters.postgres import migrations

        falsa = tmp_path / "0001_dataset_registry.sql"
        falsa.write_text("SELECT 1;", encoding="utf-8")
        with pytest.raises(DependencyError, match="foi modificada"):
            await migrations.migrate(database, tmp_path)


class TestFluxoCompletoValido:
    async def test_registrar_enviar_validar_promover(self, pilha: Pilha) -> None:
        """O fluxo que a Definition of Done exige, ponta a ponta.

        create → upload real → SHA-256 → bruto gravado → metadados
        persistidos → validar → relatório → STAGED.
        """
        dataset, criado = await pilha.registrar()
        assert criado

        resultado = await pilha.attach.execute(
            actor=ATOR,
            dataset_id=dataset.id,
            filename="E0.csv",
            file_format=DatasetFormat.CSV,
            stream=stream(CSV_BOM),
        )
        # OS BYTES ESTÃO NO OBJECT STORE, e o hash é o dos bytes que chegaram.
        assert await pilha.store.exists(resultado.file.object_key)
        cabeca = await pilha.store.head(resultado.file.object_key)
        assert cabeca is not None
        assert cabeca.size_bytes == len(CSV_BOM)

        # OS METADADOS ESTÃO NO POSTGRESQL.
        persistido = await pilha.datasets.by_id(dataset.id)
        assert persistido is not None
        assert persistido.lifecycle is DatasetLifecycle.UPLOADED
        assert len(persistido.stored_files) == 1
        assert persistido.stored_files[0].content_hash == resultado.file.content_hash

        relatorio = await pilha.validate.execute(actor=ATOR, dataset_id=dataset.id)
        assert not relatorio.has_blocking_issues
        assert relatorio.rows_observed == 2

        recarregado = await pilha.validations.latest_for(dataset.id)
        assert recarregado is not None
        assert recarregado.id == relatorio.id
        assert recarregado.status is relatorio.status

        promovido = await pilha.stage.execute(
            actor=ATOR, dataset_id=dataset.id, reason="conferido contra o site da fonte"
        )
        assert promovido.lifecycle is DatasetLifecycle.STAGED

        final = await pilha.datasets.by_id(dataset.id)
        assert final is not None
        assert final.lifecycle is DatasetLifecycle.STAGED

    async def test_manifesto_e_persistido_e_relido_identico(self, pilha: Pilha) -> None:
        dataset, _ = await pilha.registrar()
        await pilha.attach.execute(
            actor=ATOR,
            dataset_id=dataset.id,
            filename="E0.csv",
            file_format=DatasetFormat.CSV,
            stream=stream(CSV_BOM),
        )
        await pilha.validate.execute(actor=ATOR, dataset_id=dataset.id)

        manifesto = await pilha.manifests.latest_for(dataset.id)
        assert manifesto is not None
        # A IMPRESSÃO SOBREVIVE À IDA E VOLTA DO BANCO. Se não sobrevivesse, a
        # pergunta "este resultado saiu de quais bytes" deixaria de ter
        # resposta assim que o processo reiniciasse.
        por_impressao = await pilha.manifests.by_fingerprint(manifesto.fingerprint.value)
        assert por_impressao is not None
        assert por_impressao.fingerprint == manifesto.fingerprint
        assert por_impressao.files == manifesto.files
        assert por_impressao.canonical_bytes() == manifesto.canonical_bytes()

    async def test_contagem_de_linhas_da_inspecao_vai_para_o_banco(
        self, pilha: Pilha
    ) -> None:
        dataset, _ = await pilha.registrar()
        await pilha.attach.execute(
            actor=ATOR,
            dataset_id=dataset.id,
            filename="E0.csv",
            file_format=DatasetFormat.CSV,
            stream=stream(CSV_BOM),
        )
        await pilha.validate.execute(actor=ATOR, dataset_id=dataset.id)
        arquivos = await pilha.files.by_dataset(dataset.id)
        assert arquivos[0].row_count == 2
        assert arquivos[0].column_count == 5

    async def test_trilha_de_auditoria_registra_o_fluxo(self, pilha: Pilha) -> None:
        dataset, _ = await pilha.registrar()
        await pilha.attach.execute(
            actor=ATOR,
            dataset_id=dataset.id,
            filename="E0.csv",
            file_format=DatasetFormat.CSV,
            stream=stream(CSV_BOM),
        )
        await pilha.validate.execute(actor=ATOR, dataset_id=dataset.id)
        await pilha.stage.execute(actor=ATOR, dataset_id=dataset.id, reason="ok, conferido")

        entradas = await pilha.audit.recent_for_dataset(dataset.id)
        acoes = {e.action.value for e in entradas}
        assert {
            "DATASET_REGISTERED",
            "DATASET_FILE_STORED",
            "DATASET_VALIDATION_COMPLETED",
            "DATASET_STAGED",
        } <= acoes
        decisao = next(e for e in entradas if e.action.is_decision)
        assert decisao.reason == "ok, conferido"
        assert decisao.actor.id == "darlan"

    async def test_historico_de_transicoes_e_persistido(self, pilha: Pilha) -> None:
        dataset, _ = await pilha.registrar()
        await pilha.attach.execute(
            actor=ATOR,
            dataset_id=dataset.id,
            filename="E0.csv",
            file_format=DatasetFormat.CSV,
            stream=stream(CSV_BOM),
        )
        transicoes = await pilha.datasets.transitions_of(dataset.id)
        assert transicoes
        assert all(motivo.strip() for _, _, motivo, _ in transicoes)


class TestFluxoInvalido:
    async def test_dataset_com_impeditivo_nao_chega_a_staged(self, pilha: Pilha) -> None:
        """O fluxo inválido que a Definition of Done exige.

        arquivo ruim → issue impeditiva → staging recusado.
        """
        dataset, _ = await pilha.registrar()
        await pilha.attach.execute(
            actor=ATOR,
            dataset_id=dataset.id,
            filename="quebrado.csv",
            file_format=DatasetFormat.CSV,
            stream=stream(CSV_RUIM),
        )
        relatorio = await pilha.validate.execute(actor=ATOR, dataset_id=dataset.id)
        assert relatorio.has_blocking_issues

        atual = await pilha.datasets.by_id(dataset.id)
        assert atual is not None
        assert atual.lifecycle is DatasetLifecycle.INVALID

        with pytest.raises(ConflictError):
            await pilha.stage.execute(
                actor=ATOR, dataset_id=dataset.id, reason="quero mesmo assim"
            )

        depois = await pilha.datasets.by_id(dataset.id)
        assert depois is not None
        assert depois.lifecycle is DatasetLifecycle.INVALID

    async def test_issues_sao_persistidas_com_severidade_e_local(
        self, pilha: Pilha
    ) -> None:
        dataset, _ = await pilha.registrar()
        await pilha.attach.execute(
            actor=ATOR,
            dataset_id=dataset.id,
            filename="quebrado.csv",
            file_format=DatasetFormat.CSV,
            stream=stream(CSV_RUIM),
        )
        original = await pilha.validate.execute(actor=ATOR, dataset_id=dataset.id)
        relido = await pilha.validations.by_id(original.id)
        assert relido is not None
        assert len(relido.issues) == len(original.issues)
        assert relido.has_blocking_issues
        # A ORDEM VEM DO ÍNDICE: impeditivo primeiro. Quem lê um relatório em
        # terminal lê as primeiras linhas.
        assert relido.issues[0].severity >= relido.issues[-1].severity


class TestIdempotenciaImpostaPeloBanco:
    async def test_registrar_duas_vezes_nao_cria_duas_linhas(self, pilha: Pilha) -> None:
        primeiro, criado1 = await pilha.registrar()
        segundo, criado2 = await pilha.registrar()
        assert criado1
        assert not criado2
        assert primeiro.id == segundo.id
        _, total = await pilha.listing.execute(
            filters=DatasetFilter(), page=Page(limit=50)
        )
        assert total == 1

    async def test_mesmo_conteudo_nao_cria_dois_arquivos(self, pilha: Pilha) -> None:
        """A constraint UNIQUE (dataset_id, sha256) é quem decide.

        Lógica Python não protege contra dois processos concorrentes: os dois
        consultam, os dois não encontram, os dois inserem.
        """
        dataset, _ = await pilha.registrar()
        argumentos: dict[str, Any] = {
            "actor": ATOR,
            "dataset_id": dataset.id,
            "file_format": DatasetFormat.CSV,
        }
        a = await pilha.attach.execute(
            **argumentos, filename="E0.csv", stream=stream(CSV_BOM)
        )
        b = await pilha.attach.execute(
            **argumentos, filename="premier_2019.csv", stream=stream(CSV_BOM)
        )
        assert b.was_duplicate
        assert a.file.id == b.file.id
        assert len(await pilha.files.by_dataset(dataset.id)) == 1

    async def test_conteudo_diferente_com_o_mesmo_nome_sao_dois(
        self, pilha: Pilha
    ) -> None:
        dataset, _ = await pilha.registrar()
        argumentos: dict[str, Any] = {
            "actor": ATOR,
            "dataset_id": dataset.id,
            "filename": "E0.csv",
            "file_format": DatasetFormat.CSV,
        }
        await pilha.attach.execute(**argumentos, stream=stream(CSV_BOM))
        await pilha.attach.execute(
            **argumentos, stream=stream(CSV_BOM + b"2019-08-11,Arsenal,Chelsea,1,1\n")
        )
        assert len(await pilha.files.by_dataset(dataset.id)) == 2

    async def test_manifesto_reemitido_nao_duplica(self, pilha: Pilha) -> None:
        """A impressão é a chave primária: reemitir o mesmo manifesto produz
        a mesma linha, não uma segunda."""
        dataset, _ = await pilha.registrar()
        await pilha.attach.execute(
            actor=ATOR,
            dataset_id=dataset.id,
            filename="E0.csv",
            file_format=DatasetFormat.CSV,
            stream=stream(CSV_BOM),
        )
        await pilha.validate.execute(actor=ATOR, dataset_id=dataset.id)
        manifesto = await pilha.manifests.latest_for(dataset.id)
        assert manifesto is not None
        await pilha.manifests.save(manifesto)
        await pilha.manifests.save(manifesto)
        assert await pilha.manifests.by_fingerprint(manifesto.fingerprint.value) is not None


class TestConcorrencia:
    async def test_transicao_condicional_recusa_o_segundo(self, pilha: Pilha) -> None:
        """O `UPDATE ... WHERE lifecycle = $esperado` é o lock.

        Duas validações simultâneas: a primeira toma o estado, a segunda
        encontra `VALIDATING` e perde. Em Python as duas leriam `UPLOADED` e
        as duas seguiriam.
        """
        dataset, _ = await pilha.registrar()
        await pilha.attach.execute(
            actor=ATOR,
            dataset_id=dataset.id,
            filename="E0.csv",
            file_format=DatasetFormat.CSV,
            stream=stream(CSV_BOM),
        )
        primeira = await pilha.datasets.transition(
            dataset.id,
            expected=DatasetLifecycle.UPLOADED,
            target=DatasetLifecycle.VALIDATING,
            at=AGORA,
            reason="primeira",
            actor_id="a",
        )
        segunda = await pilha.datasets.transition(
            dataset.id,
            expected=DatasetLifecycle.UPLOADED,
            target=DatasetLifecycle.VALIDATING,
            at=AGORA,
            reason="segunda",
            actor_id="b",
        )
        assert primeira, "a primeira transição deveria tomar o estado"
        assert not segunda, "a segunda deveria perder a corrida"

    async def test_validacao_simultanea_recebe_conflito(self, pilha: Pilha) -> None:
        dataset, _ = await pilha.registrar()
        await pilha.attach.execute(
            actor=ATOR,
            dataset_id=dataset.id,
            filename="E0.csv",
            file_format=DatasetFormat.CSV,
            stream=stream(CSV_BOM),
        )
        await pilha.datasets.transition(
            dataset.id,
            expected=DatasetLifecycle.UPLOADED,
            target=DatasetLifecycle.VALIDATING,
            at=AGORA,
            reason="outra já começou",
            actor_id="outro",
        )
        with pytest.raises(ConflictError, match="já está em"):
            await pilha.validate.execute(actor=ATOR, dataset_id=dataset.id)


class TestTransacao:
    async def test_excecao_dentro_do_escopo_reverte(self, database: Database) -> None:
        """O que os duplos não conseguem provar: a transação de fato reverte."""
        async with database.acquire() as conexao:
            await conexao.execute(
                "CREATE TABLE IF NOT EXISTS _teste_uow (id integer PRIMARY KEY)"
            )
            await conexao.execute("TRUNCATE _teste_uow")

        async def _escrever_e_falhar() -> None:
            async with PostgresUnitOfWork(database), database.acquire() as conexao:
                await conexao.execute("INSERT INTO _teste_uow (id) VALUES (1)")
                raise RuntimeError("falha no meio")

        with pytest.raises(RuntimeError):
            await _escrever_e_falhar()

        async with database.acquire() as conexao:
            assert await conexao.fetchval("SELECT count(*) FROM _teste_uow") == 0

    async def test_saida_normal_commita(self, database: Database) -> None:
        async with database.acquire() as conexao:
            await conexao.execute(
                "CREATE TABLE IF NOT EXISTS _teste_uow (id integer PRIMARY KEY)"
            )
            await conexao.execute("TRUNCATE _teste_uow")

        async with PostgresUnitOfWork(database), database.acquire() as conexao:
            await conexao.execute("INSERT INTO _teste_uow (id) VALUES (2)")

        async with database.acquire() as conexao:
            assert await conexao.fetchval("SELECT count(*) FROM _teste_uow") == 1

    async def test_transacao_aninhada_e_recusada(self, database: Database) -> None:
        """Um savepoint implícito faria o bloco de dentro parecer atômico
        quando o de fora ainda pode reverter tudo."""
        async with PostgresUnitOfWork(database):
            with pytest.raises(DependencyError, match="já existe uma transação"):
                async with PostgresUnitOfWork(database):
                    pass


class TestFalhaDeInfraestrutura:
    async def test_falha_ao_gravar_nao_deixa_o_dataset_avancar(
        self, pilha: Pilha
    ) -> None:
        """`ObjectStore` falha no meio do upload.

        O que precisa acontecer: a linha do arquivo fica em `FAILED`, o
        dataset NÃO chega a `UPLOADED`, e a validação recusa começar. O que
        NÃO pode acontecer é o dataset seguir como se o arquivo estivesse lá.
        """
        dataset, _ = await pilha.registrar()

        class StoreQuebrado:
            async def head(self, key: str) -> None:
                return None

            async def put_stream(self, *args: Any, **kwargs: Any) -> None:
                raise OSError("disco cheio")

        pilha.attach.archive._store = StoreQuebrado()  # type: ignore[attr-defined]
        with pytest.raises(DependencyError):
            await pilha.attach.execute(
                actor=ATOR,
                dataset_id=dataset.id,
                filename="E0.csv",
                file_format=DatasetFormat.CSV,
                stream=stream(CSV_BOM),
            )

        atual = await pilha.datasets.by_id(dataset.id)
        assert atual is not None
        assert atual.lifecycle is not DatasetLifecycle.UPLOADED
        assert atual.stored_files == ()
        # A LINHA FICA, MARCADA. Apagá-la esconderia que alguém tentou enviar
        # este arquivo — e é esse rastro que explica o dataset incompleto.
        arquivos = await pilha.files.by_dataset(dataset.id)
        assert arquivos
        assert not arquivos[0].staging_state.counts_as_present

    async def test_objeto_ausente_impede_o_staging(self, pilha: Pilha) -> None:
        """O registro diz que os bytes estão lá e eles não estão.

        É o estado que sobra quando a gravação falha depois de a linha ter
        sido confirmada — e ele precisa ser detectado pela validação, não
        descoberto pelo PR-03.
        """
        dataset, _ = await pilha.registrar()
        resultado = await pilha.attach.execute(
            actor=ATOR,
            dataset_id=dataset.id,
            filename="E0.csv",
            file_format=DatasetFormat.CSV,
            stream=stream(CSV_BOM),
        )

        class StoreVazio:
            async def head(self, key: str) -> None:
                return None

        pilha.validate.validator._archive._store = StoreVazio()  # type: ignore[attr-defined]
        relatorio = await pilha.validate.execute(actor=ATOR, dataset_id=dataset.id)
        assert relatorio.has_blocking_issues
        assert "OBJECT_MISSING" in {i.code.value for i in relatorio.issues}
        assert resultado.file.object_key


class TestObjectStoreReal:
    async def test_grava_le_e_lista_no_minio(
        self, minio_only: Any, prefixo_unico: str
    ) -> None:
        """O que só o MinIO prova: checksum do S3, leitura em blocos e
        paginação da listagem."""
        chave = f"datasets/raw/dataset=teste-{prefixo_unico}/version=v1.0/sha256=x/e0.csv"
        await minio_only.ensure_bucket()
        gravado = await minio_only.put_stream(
            chave, iter([CSV_BOM]), content_type="text/csv", size_bytes=len(CSV_BOM)
        )
        assert gravado.size_bytes == len(CSV_BOM)

        lido = b""
        async for bloco in minio_only.open_stream(chave):
            lido += bloco
        assert lido == CSV_BOM

        chaves = [k async for k in minio_only.list_prefix("datasets/raw/")]
        assert chave in chaves

    async def test_checksum_do_backend_confere_com_o_nosso(
        self, minio_only: Any, prefixo_unico: str
    ) -> None:
        """O S3 devolve o checksum em base64; o nosso é hexadecimal.

        Sem a tradução, a comparação sempre falharia — dizendo que os bytes
        divergem, que é o pior alarme falso possível neste PR.
        """
        import hashlib

        chave = f"datasets/raw/dataset=chk-{prefixo_unico}/version=v1.0/sha256=y/e0.csv"
        await minio_only.ensure_bucket()
        gravado = await minio_only.put_stream(
            chave, iter([CSV_BOM]), content_type="text/csv", size_bytes=len(CSV_BOM)
        )
        if gravado.checksum_sha256:
            assert gravado.checksum_sha256 == hashlib.sha256(CSV_BOM).hexdigest()
