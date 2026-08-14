"""Os casos de uso no caminho real: intenção, gravação, confirmação.

O QUE ESTE ARQUIVO PROVA QUE OS TESTES DE DOMÍNIO NÃO PODEM PROVAR. Os
invariantes do domínio são verificados por testes que os chamam diretamente; o
caminho real — coordenar repositório, arquivo bruto, relógio e barramento na
ordem certa — nunca é exercitado por eles. É nesse caminho que a regra vaza.

O ARQUIVO BRUTO AQUI É DE VERDADE, sobre disco (`FilesystemObjectStore` em
`tmp_path`). Não é um mock: os bytes são gravados, relidos e conferidos. É a
única forma de o teste de idempotência significar alguma coisa — com um mock,
"não regravou" seria uma afirmação sobre o mock.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sports_intelligence.adapters.event_bus import CollectingEventPublisher
from sports_intelligence.adapters.s3.filesystem import FilesystemObjectStore
from sports_intelligence.application.use_cases.datasets import (
    AttachDatasetFile,
    ReconcilePendingUploads,
    RegisterDataset,
    StageDataset,
    ValidateDataset,
)
from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.datasets.formats import DatasetFormat
from sports_intelligence.domain.datasets.lifecycle import DatasetLifecycle
from sports_intelligence.domain.datasets.source import DatasetSource
from sports_intelligence.domain.events.envelope_types import (
    DATASET_FILE_STORED,
    DATASET_REGISTERED,
    DATASET_STAGED,
)
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.errors import ConflictError, ValidationError
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
from tests.support.registry_fakes import (
    FakeAuditLog,
    FakeDatasetFileRepository,
    FakeDatasetRepository,
    FakeManifestRepository,
    FakeUnitOfWork,
    FakeValidationRepository,
)

AGORA: Instant = instant(datetime(2026, 8, 13, 12, 0, tzinfo=UTC))
V1 = DatasetVersion(major=1, minor=0)
ATOR = Actor(id="darlan", kind=ActorKind.HUMAN_OPERATOR)

CSV_BOM = b"Date,HomeTeam,AwayTeam,FTHG,FTAG\n2019-08-09,Liverpool,Norwich,4,1\n"
CSV_RUIM = b"Date,HomeTeam,AwayTeam\n2019-08-09,Liverpool\n2019-08-10\nx\n"


async def stream(dados: bytes, bloco: int = 8) -> AsyncIterator[bytes]:
    for i in range(0, len(dados), bloco):
        yield dados[i : i + bloco]


class Ambiente:
    """O grafo montado com duplos no registro e disco de verdade no bruto."""

    def __init__(self, tmp: Path) -> None:
        self.clock = FrozenClock(AGORA)
        self.store = FilesystemObjectStore(tmp / "bruto")
        self.archive = RawDatasetArchive(self.store)
        self.datasets = FakeDatasetRepository()
        self.files = FakeDatasetFileRepository(self.datasets)
        self.validations = FakeValidationRepository()
        self.manifests = FakeManifestRepository()
        self.audit = FakeAuditLog()
        self.publisher = CollectingEventPublisher()
        self.uow = FakeUnitOfWork()

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
            max_file_size_bytes=1024 * 1024,
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
                    max_file_size_bytes=1024 * 1024,
                    max_rows_per_file=1_000_000,
                    max_issues=50,
                ),
            ),
            clock=self.clock,
            audit=self.audit,
            publisher=self.publisher,
            uow=self.uow,
        )
        self.stage = StageDataset(
            datasets=self.datasets,
            validations=self.validations,
            clock=self.clock,
            audit=self.audit,
            publisher=self.publisher,
        )

    async def registrar(self, **mudancas: Any) -> Any:
        argumentos: dict[str, Any] = {
            "actor": ATOR,
            "name": "premier-league-2019",
            "version": V1,
            "source": DatasetSource(
                source_name="football-data.co.uk",
                source_type=SourceType.OPEN_DATA,
                license_class=LicenseClass.ATTRIBUTION_REQUIRED,
                retrieved_at=instant(datetime(2026, 8, 1, tzinfo=UTC)),
                provider_id=ProviderId("football_data"),
            ),
            "declared_competitions": frozenset({CompetitionCode.PREMIER_LEAGUE}),
            "declared_seasons": ("2019-2020",),
        }
        argumentos.update(mudancas)
        return await self.register.execute(**argumentos)

    async def fluxo_completo(self, conteudo: bytes = CSV_BOM) -> Any:
        dataset, _ = await self.registrar()
        await self.attach.execute(
            actor=ATOR,
            dataset_id=dataset.id,
            filename="e0.csv",
            file_format=DatasetFormat.CSV,
            stream=stream(conteudo),
        )
        await self.validate.execute(actor=ATOR, dataset_id=dataset.id)
        return dataset


@pytest.fixture
def ambiente(tmp_path: Path) -> Ambiente:
    return Ambiente(tmp_path)


class TestRegistro:
    async def test_registra_e_publica(self, ambiente: Ambiente) -> None:
        dataset, criado = await ambiente.registrar()
        assert criado
        assert dataset.lifecycle is DatasetLifecycle.REGISTERED
        assert ambiente.publisher.of_type(DATASET_REGISTERED)
        assert "DATASET_REGISTERED" in ambiente.audit.actions()

    async def test_registrar_de_novo_nao_cria_um_segundo(self, ambiente: Ambiente) -> None:
        """A idempotência que vem da identidade derivada de (nome, versão)."""
        primeiro, criado1 = await ambiente.registrar()
        segundo, criado2 = await ambiente.registrar()
        assert criado1
        assert not criado2
        assert primeiro.id == segundo.id
        assert len(ambiente.datasets.datasets) == 1
        # Só o primeiro publica: um evento por reenvio faria o consumidor
        # contar registros que não aconteceram.
        assert len(ambiente.publisher.of_type(DATASET_REGISTERED)) == 1

    async def test_mesma_versao_com_outra_fonte_e_recusada(self, ambiente: Ambiente) -> None:
        """Sobrescrever a ficha de origem apagaria a licença sob a qual os
        bytes foram aceitos — e é ela que decide o que se pode fazer com eles."""
        await ambiente.registrar()
        outra = DatasetSource(
            source_name="outra-fonte",
            source_type=SourceType.MANUAL,
            license_class=LicenseClass.RESEARCH_ONLY,
            retrieved_at=instant(datetime(2026, 8, 1, tzinfo=UTC)),
        )
        with pytest.raises(ConflictError, match="outra fonte"):
            await ambiente.registrar(source=outra)


class TestUploadEIdempotencia:
    async def test_upload_grava_confere_e_confirma(self, ambiente: Ambiente) -> None:
        dataset, _ = await ambiente.registrar()
        resultado = await ambiente.attach.execute(
            actor=ATOR,
            dataset_id=dataset.id,
            filename="e0.csv",
            file_format=DatasetFormat.CSV,
            stream=stream(CSV_BOM),
        )
        assert not resultado.was_duplicate
        assert resultado.bytes_written == len(CSV_BOM)
        assert await ambiente.store.exists(resultado.file.object_key)

        atual = await ambiente.datasets.by_id(dataset.id)
        assert atual is not None
        assert len(atual.stored_files) == 1
        assert not atual.has_pending_uploads
        # A JANELA FECHA SOZINHA quando não sobra promessa em aberto.
        assert atual.lifecycle is DatasetLifecycle.UPLOADED
        assert ambiente.publisher.of_type(DATASET_FILE_STORED)

    async def test_reenviar_os_mesmos_bytes_nao_grava_de_novo(
        self, ambiente: Ambiente
    ) -> None:
        """Retry de rede é operação normal, não conflito."""
        dataset, _ = await ambiente.registrar()
        argumentos: dict[str, Any] = {
            "actor": ATOR,
            "dataset_id": dataset.id,
            "filename": "e0.csv",
            "file_format": DatasetFormat.CSV,
        }
        primeiro = await ambiente.attach.execute(**argumentos, stream=stream(CSV_BOM))
        segundo = await ambiente.attach.execute(**argumentos, stream=stream(CSV_BOM))
        assert segundo.was_duplicate
        assert segundo.bytes_written == 0
        assert primeiro.file.id == segundo.file.id
        assert len(await ambiente.files.by_dataset(dataset.id)) == 1

    async def test_nome_diferente_com_os_mesmos_bytes_e_reconhecido(
        self, ambiente: Ambiente
    ) -> None:
        """`E0.csv` e `premier_2019.csv` baixados do mesmo lugar em dias
        diferentes. Sem detecção, cada linha entraria duas vezes."""
        dataset, _ = await ambiente.registrar()
        await ambiente.attach.execute(
            actor=ATOR,
            dataset_id=dataset.id,
            filename="e0.csv",
            file_format=DatasetFormat.CSV,
            stream=stream(CSV_BOM),
        )
        segundo = await ambiente.attach.execute(
            actor=ATOR,
            dataset_id=dataset.id,
            filename="premier_2019.csv",
            file_format=DatasetFormat.CSV,
            stream=stream(CSV_BOM),
        )
        assert segundo.was_duplicate
        assert len(await ambiente.files.by_dataset(dataset.id)) == 1

    async def test_mesmo_nome_com_bytes_diferentes_e_outro_arquivo(
        self, ambiente: Ambiente
    ) -> None:
        dataset, _ = await ambiente.registrar()
        argumentos: dict[str, Any] = {
            "actor": ATOR,
            "dataset_id": dataset.id,
            "filename": "e0.csv",
            "file_format": DatasetFormat.CSV,
        }
        a = await ambiente.attach.execute(**argumentos, stream=stream(CSV_BOM))
        b = await ambiente.attach.execute(
            **argumentos, stream=stream(CSV_BOM + b"2019-08-10,Arsenal,Chelsea,1,1\n")
        )
        assert not b.was_duplicate
        assert a.file.id != b.file.id
        assert len(await ambiente.files.by_dataset(dataset.id)) == 2

    async def test_arquivo_vazio_e_recusado_antes_de_gravar(
        self, ambiente: Ambiente
    ) -> None:
        """Gravá-lo gastaria uma chave do arquivo bruto para guardar nada."""
        dataset, _ = await ambiente.registrar()
        with pytest.raises(ValidationError, match="zero bytes"):
            await ambiente.attach.execute(
                actor=ATOR,
                dataset_id=dataset.id,
                filename="vazio.csv",
                file_format=DatasetFormat.CSV,
                stream=stream(b""),
            )
        assert not await ambiente.files.by_dataset(dataset.id)

    async def test_arquivo_compactado_e_recusado_antes_de_gravar(
        self, ambiente: Ambiente
    ) -> None:
        """Um zip que entra no arquivo bruto é uma bomba esperando a validação."""
        dataset, _ = await ambiente.registrar()
        with pytest.raises(ValidationError, match="compactado"):
            await ambiente.attach.execute(
                actor=ATOR,
                dataset_id=dataset.id,
                filename="dados.csv",
                file_format=DatasetFormat.CSV,
                stream=stream(b"PK\x03\x04" + b"x" * 100),
            )

    async def test_upload_acima_do_limite_para_a_leitura(self, tmp_path: Path) -> None:
        """O teto é cobrado bloco a bloco, não depois de ler tudo."""
        ambiente = Ambiente(tmp_path)
        ambiente.attach = AttachDatasetFile(
            datasets=ambiente.datasets,
            files=ambiente.files,
            archive=ambiente.archive,
            clock=ambiente.clock,
            audit=ambiente.audit,
            publisher=ambiente.publisher,
            max_file_size_bytes=32,
        )
        dataset, _ = await ambiente.registrar()
        with pytest.raises(ValidationError, match="excede o limite"):
            await ambiente.attach.execute(
                actor=ATOR,
                dataset_id=dataset.id,
                filename="grande.csv",
                file_format=DatasetFormat.CSV,
                stream=stream(b"x" * 4096),
            )

    async def test_arquivo_recusado_apos_selar(self, ambiente: Ambiente) -> None:
        dataset = await ambiente.fluxo_completo()
        with pytest.raises(ConflictError, match="não aceita mais arquivos"):
            await ambiente.attach.execute(
                actor=ATOR,
                dataset_id=dataset.id,
                filename="tarde.csv",
                file_format=DatasetFormat.CSV,
                stream=stream(b"a,b\n1,2\n"),
            )


class TestValidacaoNoCaminhoReal:
    async def test_dataset_valido_chega_a_validated_com_manifesto(
        self, ambiente: Ambiente
    ) -> None:
        dataset = await ambiente.fluxo_completo()
        atual = await ambiente.datasets.by_id(dataset.id)
        assert atual is not None
        assert atual.lifecycle is DatasetLifecycle.VALIDATED
        assert ambiente.uow.entered == 1
        manifesto = await ambiente.manifests.latest_for(dataset.id)
        assert manifesto is not None
        assert manifesto.files[0].row_count == 1

    async def test_arquivo_com_defeito_grave_leva_a_invalid(
        self, ambiente: Ambiente
    ) -> None:
        dataset = await ambiente.fluxo_completo(CSV_RUIM)
        atual = await ambiente.datasets.by_id(dataset.id)
        assert atual is not None
        assert atual.lifecycle is DatasetLifecycle.INVALID
        relatorio = await ambiente.validations.latest_for(dataset.id)
        assert relatorio is not None
        assert relatorio.has_blocking_issues
        # NENHUM MANIFESTO PARA DATASET INVÁLIDO: ele afirmaria ter congelado
        # um conjunto estruturalmente apto, e ele não é.
        assert await ambiente.manifests.latest_for(dataset.id) is None

    async def test_validacao_sem_arquivo_confirmado_e_recusada(
        self, ambiente: Ambiente
    ) -> None:
        dataset, _ = await ambiente.registrar()
        with pytest.raises(ConflictError, match="não há arquivo"):
            await ambiente.validate.execute(actor=ATOR, dataset_id=dataset.id)

    async def test_duas_validacoes_simultaneas_disputam_o_estado(
        self, ambiente: Ambiente
    ) -> None:
        """A transição para `VALIDATING` É o lock.

        Em Python as duas leriam `UPLOADED` e as duas seguiriam; aqui a
        segunda perde a transição condicional e recebe conflito.
        """
        dataset, _ = await ambiente.registrar()
        await ambiente.attach.execute(
            actor=ATOR,
            dataset_id=dataset.id,
            filename="e0.csv",
            file_format=DatasetFormat.CSV,
            stream=stream(CSV_BOM),
        )
        ambiente.datasets.force_state(dataset.id, DatasetLifecycle.VALIDATING)
        with pytest.raises(ConflictError, match="já está em"):
            await ambiente.validate.execute(actor=ATOR, dataset_id=dataset.id)

    async def test_licenca_desconhecida_gera_aviso_e_nao_bloqueia(
        self, tmp_path: Path
    ) -> None:
        ambiente = Ambiente(tmp_path)
        fonte = DatasetSource(
            source_name="planilha-interna",
            source_type=SourceType.MANUAL,
            license_class=LicenseClass.UNKNOWN,
            retrieved_at=instant(datetime(2026, 8, 1, tzinfo=UTC)),
        )
        dataset, _ = await ambiente.registrar(source=fonte)
        await ambiente.attach.execute(
            actor=ATOR,
            dataset_id=dataset.id,
            filename="e0.csv",
            file_format=DatasetFormat.CSV,
            stream=stream(CSV_BOM),
        )
        relatorio = await ambiente.validate.execute(actor=ATOR, dataset_id=dataset.id)
        assert any(
            i.code.value == "LICENSE_REVIEW_REQUIRED" for i in relatorio.issues
        )
        assert not relatorio.has_blocking_issues


class TestStaging:
    async def test_dataset_validado_pode_ser_promovido(self, ambiente: Ambiente) -> None:
        dataset = await ambiente.fluxo_completo()
        promovido = await ambiente.stage.execute(
            actor=ATOR, dataset_id=dataset.id, reason="conferi as cinco temporadas"
        )
        assert promovido.lifecycle is DatasetLifecycle.STAGED
        assert "DATASET_STAGED" in ambiente.audit.actions()

    async def test_evento_de_staging_diz_que_nao_esta_pronto_para_inteligencia(
        self, ambiente: Ambiente
    ) -> None:
        """DITO NO PAYLOAD, para que nenhum consumidor precise inferir."""
        dataset = await ambiente.fluxo_completo()
        await ambiente.stage.execute(actor=ATOR, dataset_id=dataset.id, reason="ok")
        evento = ambiente.publisher.of_type(DATASET_STAGED)[0]
        assert evento.payload["intelligence_ready"] is False

    async def test_dataset_invalido_nao_sobe(self, ambiente: Ambiente) -> None:
        """O fluxo inválido inteiro, ponta a ponta."""
        dataset = await ambiente.fluxo_completo(CSV_RUIM)
        with pytest.raises(ConflictError, match="VALIDATED"):
            await ambiente.stage.execute(
                actor=ATOR, dataset_id=dataset.id, reason="quero mesmo assim"
            )

    async def test_promover_sem_validacao_e_recusado(self, ambiente: Ambiente) -> None:
        dataset, _ = await ambiente.registrar()
        with pytest.raises(ConflictError, match="não há relatório"):
            await ambiente.stage.execute(actor=ATOR, dataset_id=dataset.id, reason="x")

    async def test_promover_sem_motivo_e_recusado(self, ambiente: Ambiente) -> None:
        dataset = await ambiente.fluxo_completo()
        with pytest.raises(ValidationError, match="exige motivo"):
            await ambiente.stage.execute(actor=ATOR, dataset_id=dataset.id, reason="  ")

    async def test_trilha_registra_o_motivo_da_decisao(self, ambiente: Ambiente) -> None:
        dataset = await ambiente.fluxo_completo()
        await ambiente.stage.execute(
            actor=ATOR, dataset_id=dataset.id, reason="fonte conferida com o site"
        )
        decisao = next(e for e in ambiente.audit.entries if e.action.is_decision)
        assert decisao.reason == "fonte conferida com o site"
        assert decisao.actor.id == "darlan"


class TestReconciliacao:
    async def test_pendente_com_bytes_presentes_e_confirmado(
        self, ambiente: Ambiente
    ) -> None:
        """A falha entre as fases 2 e 3: os bytes chegaram, a confirmação não.

        A reconciliação encontra o objeto e converge — sem reenvio.
        """
        from sports_intelligence.domain.datasets.content import ContentHash
        from sports_intelligence.domain.datasets.files import DatasetFile

        dataset, _ = await ambiente.registrar()
        # A intenção é registrada e os bytes são gravados — mas a confirmação
        # nunca acontece. É exatamente o estado que fica quando o processo
        # morre entre a fase 2 e a 3.
        intencao = DatasetFile.intent(
            dataset_id=dataset.id,
            version=V1,
            original_filename="e0.csv",
            file_format=DatasetFormat.CSV,
            content_hash=ContentHash.of(CSV_BOM),
            size_bytes=len(CSV_BOM),
            uploaded_at=AGORA,
            uploaded_by="darlan",
            provenance=dataset.source.to_provenance(ingested_at=AGORA),
        )
        await ambiente.files.register_intent(intencao)
        await ambiente.archive.store(intencao, iter([CSV_BOM]))

        ambiente.clock.advance(7200)
        reconciliador = ReconcilePendingUploads(
            files=ambiente.files, archive=ambiente.archive, clock=ambiente.clock
        )
        confirmados, falhados = await reconciliador.execute()
        assert (confirmados, falhados) == (1, 0)

    async def test_pendente_sem_bytes_e_marcado_como_falha(
        self, ambiente: Ambiente, tmp_path: Path
    ) -> None:
        """O upload morreu no meio. A linha FICA, marcada.

        Apagá-la esconderia que alguém tentou enviar este arquivo — e é esse
        rastro que permite descobrir depois por que o dataset está incompleto.
        """
        from sports_intelligence.domain.datasets.content import ContentHash
        from sports_intelligence.domain.datasets.files import DatasetFile

        dataset, _ = await ambiente.registrar()
        orfao = DatasetFile.intent(
            dataset_id=dataset.id,
            version=V1,
            original_filename="perdido.csv",
            file_format=DatasetFormat.CSV,
            content_hash=ContentHash.of(b"nunca gravado"),
            size_bytes=13,
            uploaded_at=AGORA,
            uploaded_by="darlan",
            provenance=dataset.source.to_provenance(ingested_at=AGORA),
        )
        await ambiente.files.register_intent(orfao)
        ambiente.clock.advance(7200)

        reconciliador = ReconcilePendingUploads(
            files=ambiente.files, archive=ambiente.archive, clock=ambiente.clock
        )
        confirmados, falhados = await reconciliador.execute()
        assert (confirmados, falhados) == (0, 1)
