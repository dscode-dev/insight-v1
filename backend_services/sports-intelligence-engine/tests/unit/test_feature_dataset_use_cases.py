"""Criar, construir, conferir e publicar — os quatro passos, com duplos.

O QUE ESTES TESTES PROVAM:

    a construção produz 91 linhas POR PARTIDA        contadas, não estimadas
    a divisão é ATÔMICA                              nenhuma partida em duas
                                                     metades
    a impressão é REPRODUTÍVEL                       duas construções, um número
    a validação RECONSTRÓI e compara                 e reprova quando diverge
    a validação acusa ORDEM invertida                num arquivo
    publicar sem validar NÃO é alcançável            o grafo recusa
    publicar SUPERA a versão anterior                e a trilha registra as duas
    a origem é CONFERIDA                             construir sobre outra
                                                     versão do corpus é recusado
    a falha derruba a versão                         em vez de deixá-la em
                                                     BUILDING para sempre

A VALIDAÇÃO REPROVANDO É O TESTE MAIS IMPORTANTE. Uma conferência que nenhum
teste quebra é uma conferência que ninguém sabe se funciona.
"""

from __future__ import annotations

import functools
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from sports_intelligence.application.use_cases.feature_dataset import (
    BuildHistoricalFeatureDatasetVersion,
    CreateHistoricalFeatureDatasetVersion,
    FeatureDatasetBuildOutput,
    PublishHistoricalFeatureDatasetVersion,
    ValidateHistoricalFeatureDatasetVersion,
    _EscritorDeParticoes,
)
from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.corpus.scope import CorpusScope, ScopeEntry
from sports_intelligence.domain.corpus.versions import (
    DatasetVersionStatus,
    HistoricalCanonicalDataset,
    HistoricalCanonicalDatasetVersion,
    VersionInputs,
)
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.features.dataset.grid import SnapshotGridPolicy
from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
    MaterializedFeatureRow,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.dataset.versions import (
    DEFAULT_FEATURE_DATASET_NAME,
)
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import instant
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.ports.clock import FrozenClock
from tests.support.dataset_doubles import (
    FakeContextSource,
    FakeFeatureDatasetBuildRepository,
    FakeFeatureDatasetManifestRepository,
    FakeFeatureDatasetRepository,
    FakeFeatureMaterializer,
    FakeStateSource,
)
from tests.support.dataset_fixtures import (
    AVALIACAO_ESPERADA,
    PARTIDAS_DO_CENARIO,
    REFERENCIA_ESPERADA,
    corpus_do_cenario,
    divisao,
    grade,
    origem_do_cenario,
)
from tests.support.feature_fixtures import competicao, temporada
from tests.support.registry_fakes import FakeAuditLog

AGORA = instant(datetime(2026, 5, 1, 12, 0, tzinfo=UTC))
ATOR = Actor.service("pr0551")
NOME = DEFAULT_FEATURE_DATASET_NAME

#: 6 partidas em 91 cortes cada. Contado à mão, e é o número que o PR promete.
LINHAS_ESPERADAS = PARTIDAS_DO_CENARIO * 91


@functools.cache
def _snapshot_compartilhado() -> Any:
    """Um snapshot só, reusado pelas linhas do teste de memória.

    ELAS EXERCITAM A POLÍTICA DE DESCARGA, e não a extração: construir trezentos
    snapshots reais faria o teste medir o extrator.
    """
    from tests.support.v2_fixtures import extrair_v2

    return extrair_v2()


class FakeCorpusRepo:
    """Só o que a criação usa: buscar a versão do corpus por id."""

    def __init__(self, versao: HistoricalCanonicalDatasetVersion | None) -> None:
        self.versao = versao

    async def version_by_id(self, version_id: str) -> HistoricalCanonicalDatasetVersion | None:
        return self.versao


def _versao_de_corpus(
    *, status: DatasetVersionStatus = DatasetVersionStatus.READY
) -> HistoricalCanonicalDatasetVersion:
    origem = origem_do_cenario()
    dataset = HistoricalCanonicalDataset.create(name="historical-core", at=AGORA, created_by=ATOR)
    base = HistoricalCanonicalDatasetVersion.draft(
        dataset_id=dataset.id,
        version=origem.version,
        scope=CorpusScope.of(
            ScopeEntry(
                competition=CompetitionCode.PREMIER_LEAGUE,
                season_label="2025/26",
                competition_id=competicao().id,
                season_id=temporada().id,
            ),
            usage=UsageScope.RESEARCH,
        ),
        inputs=VersionInputs(build_run_ids=("b1",), quality_run_ids=()),
        at=AGORA,
        created_by=ATOR,
    )
    return replace(
        base,
        id=origem.version_id,
        status=status,
        corpus_fingerprint=origem.corpus_fingerprint,
        manifest_id="m1" if status is DatasetVersionStatus.READY else None,
        completed_at=AGORA if status.is_terminal else None,
    )


class Cenario:
    """Os quatro casos de uso montados sobre os mesmos duplos."""

    def __init__(self, *, partidas: int = PARTIDAS_DO_CENARIO) -> None:
        self.corpus = corpus_do_cenario(partidas=partidas)
        self.origem = origem_do_cenario()
        self.estado = FakeStateSource(self.corpus)
        self.contexto = FakeContextSource()
        self.repo = FakeFeatureDatasetRepository()
        self.builds = FakeFeatureDatasetBuildRepository()
        self.manifests = FakeFeatureDatasetManifestRepository()
        self.materializer = FakeFeatureMaterializer()
        self.clock = FrozenClock(AGORA)
        self.audit = FakeAuditLog()
        self.corpus_repo = FakeCorpusRepo(_versao_de_corpus())

    @property
    def criar(self) -> CreateHistoricalFeatureDatasetVersion:
        return CreateHistoricalFeatureDatasetVersion(
            datasets=self.repo,
            corpus=self.corpus_repo,  # type: ignore[arg-type]
            clock=self.clock,
            audit=self.audit,
        )

    @property
    def construir(self) -> BuildHistoricalFeatureDatasetVersion:
        return BuildHistoricalFeatureDatasetVersion(
            datasets=self.repo,
            builds=self.builds,
            manifests=self.manifests,
            state_source=self.estado,
            context_source=self.contexto,
            materializer=self.materializer,
            clock=self.clock,
            audit=self.audit,
        )

    @property
    def validar(self) -> ValidateHistoricalFeatureDatasetVersion:
        return ValidateHistoricalFeatureDatasetVersion(
            datasets=self.repo,
            builds=self.builds,
            manifests=self.manifests,
            materializer=self.materializer,
            state_source=self.estado,
            context_source=self.contexto,
            clock=self.clock,
            audit=self.audit,
        )

    @property
    def publicar(self) -> PublishHistoricalFeatureDatasetVersion:
        return PublishHistoricalFeatureDatasetVersion(
            datasets=self.repo,
            manifests=self.manifests,
            materializer=self.materializer,
            clock=self.clock,
            audit=self.audit,
        )

    async def criar_versao(
        self,
        *,
        version: DatasetVersion | None = None,
        grid: SnapshotGridPolicy | None = None,
    ) -> Any:
        return await self.criar.execute(
            dataset_name=NOME,
            version=version or DatasetVersion(major=1, minor=0),
            source_version_id=self.origem.version_id,
            split=divisao(),
            grid=grid or grade(),
            actor=ATOR,
            published_families=self.origem.published_families,
        )

    async def construir_versao(self, version_id: str) -> FeatureDatasetBuildOutput:
        return await self.construir.execute(
            version_id=version_id,
            source=self.origem,
            dataset_name=NOME,
            actor=ATOR,
        )


@pytest.fixture
def cenario() -> Cenario:
    return Cenario()


class TestACriacao:
    async def test_a_versao_nasce_em_draft_com_as_politicas_congeladas(
        self, cenario: Cenario
    ) -> None:
        versao = await cenario.criar_versao()
        assert versao.status is DatasetVersionStatus.DRAFT
        assert versao.spec.grid_fingerprint == grade().fingerprint
        assert versao.spec.split_fingerprint == divisao().fingerprint
        assert versao.source_corpus_fingerprint == cenario.origem.corpus_fingerprint

    async def test_corpus_nao_publicado_e_recusado(self, cenario: Cenario) -> None:
        """Features sobre corpus em construção descreveriam um corpus que
        nunca existiu."""
        cenario.corpus_repo.versao = _versao_de_corpus(status=DatasetVersionStatus.BUILDING)
        with pytest.raises(ValidationError, match="BUILDING"):
            await cenario.criar_versao()

    async def test_familia_exigida_e_ausente_e_recusada_antes_de_construir(
        self, cenario: Cenario
    ) -> None:
        """Descobrir isso depois de noventa mil snapshots custaria a
        construção inteira para chegar a uma máscara vazia."""
        with pytest.raises(ValidationError, match="EVENT"):
            await cenario.criar.execute(
                dataset_name=NOME,
                version=DatasetVersion(major=1, minor=0),
                source_version_id=cenario.origem.version_id,
                split=divisao(),
                actor=ATOR,
                published_families=frozenset({CoverageFamily.MATCH}),
            )

    async def test_a_mesma_versao_duas_vezes_e_recusada(self, cenario: Cenario) -> None:
        await cenario.criar_versao()
        with pytest.raises(Exception, match="já existe"):
            await cenario.criar_versao()

    async def test_a_criacao_e_auditada(self, cenario: Cenario) -> None:
        await cenario.criar_versao()
        assert "FEATURE_DATASET_CREATED" in cenario.audit.actions()
        assert "FEATURE_DATASET_VERSION_CREATED" in cenario.audit.actions()


class TestAConstrucao:
    async def test_ela_produz_noventa_e_uma_linhas_por_partida(self, cenario: Cenario) -> None:
        versao = await cenario.criar_versao()
        saida = await cenario.construir_versao(versao.id)
        assert saida.matches_processed == PARTIDAS_DO_CENARIO
        assert saida.rows_written == LINHAS_ESPERADAS

    async def test_a_divisao_e_atomica_por_partida(self, cenario: Cenario) -> None:
        """Nenhuma partida aparece nas duas metades — é o vazamento que a
        divisão temporal existe para impedir."""
        versao = await cenario.criar_versao()
        await cenario.construir_versao(versao.id)
        por_partida: dict[str, set[str]] = {}
        for linha in cenario.materializer.linhas:
            por_partida.setdefault(linha.key.match_key, set()).add(linha.split.value)
        assert all(len(metades) == 1 for metades in por_partida.values())

    async def test_as_contagens_por_metade_batem_com_o_cenario(self, cenario: Cenario) -> None:
        versao = await cenario.criar_versao()
        saida = await cenario.construir_versao(versao.id)
        assert saida.counts.reference_matches == REFERENCIA_ESPERADA
        assert saida.counts.evaluation_matches == AVALIACAO_ESPERADA
        assert saida.counts.reference_rows == REFERENCIA_ESPERADA * 91
        assert saida.counts.evaluation_rows == AVALIACAO_ESPERADA * 91

    async def test_a_versao_termina_em_validating_e_nao_em_ready(self, cenario: Cenario) -> None:
        """Ao fim da construção nada foi conferido — ninguém pode lê-la ainda."""
        versao = await cenario.criar_versao()
        saida = await cenario.construir_versao(versao.id)
        assert saida.version.status is DatasetVersionStatus.VALIDATING
        assert not saida.version.is_readable

    async def test_a_impressao_e_reproduzivel_entre_construcoes(self) -> None:
        primeira, segunda = Cenario(), Cenario()
        v1 = await primeira.criar_versao()
        v2 = await segunda.criar_versao()
        a = await primeira.construir_versao(v1.id)
        b = await segunda.construir_versao(v2.id)
        assert a.raw_content_fingerprint == b.raw_content_fingerprint

    async def test_o_manifesto_e_salvo_e_reconcilia_com_os_objetos(self, cenario: Cenario) -> None:
        versao = await cenario.criar_versao()
        saida = await cenario.construir_versao(versao.id)
        assert saida.manifest.row_count == LINHAS_ESPERADAS
        assert sum(o.row_count for o in saida.manifest.objects) == LINHAS_ESPERADAS
        registrados = await cenario.builds.objects_of(versao.id)
        assert {o.object_key for o in registrados} == {o.object_key for o in saida.manifest.objects}

    async def test_construir_sobre_outra_versao_do_corpus_e_recusado(
        self, cenario: Cenario
    ) -> None:
        """O nome do dataset deixaria de dizer de onde ele veio."""
        versao = await cenario.criar_versao()
        outra = replace(cenario.origem, version_id="99999999-9999-4999-8999-999999999999")
        with pytest.raises(ValidationError, match="declara construir sobre"):
            await cenario.construir.execute(
                version_id=versao.id,
                source=outra,
                dataset_name=NOME,
                actor=ATOR,
            )

    async def test_impressao_de_corpus_diferente_e_recusada(self, cenario: Cenario) -> None:
        versao = await cenario.criar_versao()
        outra = replace(cenario.origem, corpus_fingerprint=ContentHash("f" * 64))
        with pytest.raises(ValidationError, match="impressão do corpus mudou"):
            await cenario.construir.execute(
                version_id=versao.id,
                source=outra,
                dataset_name=NOME,
                actor=ATOR,
            )

    async def test_uma_falha_de_escrita_derruba_a_versao(self, cenario: Cenario) -> None:
        """Em vez de deixá-la em BUILDING para sempre, esperando alguém notar."""
        versao = await cenario.criar_versao()
        cenario.materializer.falhar_na_particao = 0
        with pytest.raises(RuntimeError):
            await cenario.construir_versao(versao.id)
        caida = await cenario.repo.version_by_id(versao.id)
        assert caida is not None
        assert caida.status is DatasetVersionStatus.FAILED
        assert caida.failure_reason
        assert "FEATURE_DATASET_VERSION_FAILED" in cenario.audit.actions()

    async def test_uma_grade_NAO_PADRAO_e_respeitada_na_construcao(self, cenario: Cenario) -> None:
        """O DEFEITO QUE ESTE TESTE PEGA: reconstruir a política por nome e
        versão traz os limites PADRÃO, e uma grade de cinco cortes voltaria com
        noventa e um. A `spec` carrega os PARÂMETROS, e não só a impressão."""
        reduzida = SnapshotGridPolicy(
            name="GRADE_CURTA_V1", first_half_last_minute=2, second_half_last_minute=4
        )
        assert reduzida.regulation_size == 5
        versao = await cenario.criar_versao(grid=reduzida)
        saida = await cenario.construir_versao(versao.id)
        assert saida.rows_written == PARTIDAS_DO_CENARIO * 5
        assert saida.version.spec.grid.name == "GRADE_CURTA_V1"

    async def test_a_construcao_registra_o_custo_da_execucao(self, cenario: Cenario) -> None:
        versao = await cenario.criar_versao()
        saida = await cenario.construir_versao(versao.id)
        execucoes = await cenario.builds.runs_of(versao.id)
        assert len(execucoes) == 1
        assert execucoes[0].rows_written == saida.rows_written
        assert execucoes[0].matches_processed == PARTIDAS_DO_CENARIO


class TestOTetoDeMemoria:
    """O escritor não pode acumular uma partição por competição aberta."""

    async def test_o_teto_global_limita_a_soma_de_todas_as_particoes(self) -> None:
        """O DEFEITO QUE ESTE TESTE PEGA, e que só uma medição revelou: com teto
        POR PARTIÇÃO apenas, uma varredura que atravessa vinte competições mantém
        vinte buffers de cinco mil linhas vivos ao mesmo tempo — e o pico deixa
        de seguir o lote para seguir quantas partições o corpus tem.
        """
        escritor = _EscritorDeParticoes(
            materializer=FakeFeatureMaterializer(),
            dataset_name=NOME,
            version="v1.0",
            part_rows=50,
            max_pending_rows=100,
        )
        maximo = 0
        linhas = [_linha_qualquer(i) for i in range(10)]
        for rodada in range(30):
            competicao = f"LIGA_{rodada % 12}"
            await escritor.acrescentar(DatasetSplit.REFERENCE, competicao, "2025/26", linhas)
            maximo = max(maximo, sum(len(b) for b in escritor.pendentes.values()))
        assert maximo <= 100, f"pico de {maximo} linhas em espera com teto de 100"

    async def test_o_teto_e_respeitado_com_particoes_INTERCALADAS(self) -> None:
        """§31, §32. A carga adversarial: as partições se intercalam.

        UM CENÁRIO ORDENADO SERIA FÁCIL DEMAIS. Se todas as linhas de `LIGA_A`
        chegassem juntas, o teto por PEDAÇO já bastaria — a partição encheria e
        seria descarregada antes de a próxima abrir. É a intercalação que
        mantém vinte buffers vivos ao mesmo tempo, e é ela que o teto global
        existe para cobrir.
        """
        escritor = _EscritorDeParticoes(
            materializer=FakeFeatureMaterializer(),
            dataset_name=NOME,
            version="v1.0",
            part_rows=91,
            max_pending_rows=500,
        )
        abertas_no_pico = 0
        for rodada in range(120):
            # A, B, C, ... T, A, B, ... — e nunca AAAA, BBBB, CCCC.
            competicao = f"LIGA_{rodada % 20}"
            temporada = f"202{rodada % 3}/2{rodada % 3 + 1}"
            await escritor.acrescentar(
                DatasetSplit.REFERENCE,
                competicao,
                temporada,
                [_linha_qualquer(i, competicao=competicao, temporada=temporada) for i in range(13)],
            )
            em_espera = sum(len(b) for b in escritor.pendentes.values())
            assert em_espera <= 500, f"{em_espera} linhas em espera com teto de 500"
            abertas_no_pico = max(abertas_no_pico, sum(1 for b in escritor.pendentes.values() if b))
        assert escritor.pico_em_espera <= 500
        assert escritor.pico_de_particoes >= 5, escritor.pico_de_particoes
        assert abertas_no_pico >= 5

    async def test_ao_atingir_o_teto_a_MAIOR_particao_e_descarregada(self) -> None:
        """§22, §39, §40. A escolha é a que libera mais memória por arquivo.

        DESCARREGAR A MENOR aliviaria o pico do mesmo jeito e produziria uma
        enxurrada de `part-*.parquet` minúsculos; descarregar a MAIS ANTIGA
        deixaria a maior crescendo até ela virar a antiga.
        """
        materializador = FakeFeatureMaterializer()
        escritor = _EscritorDeParticoes(
            materializer=materializador,
            dataset_name=NOME,
            version="v1.0",
            part_rows=100,
            max_pending_rows=100,
        )
        # `GRANDE` acumula 60 linhas; `PEQUENA`, 20. Nenhuma das duas enche o
        # pedaço de cem, então só o teto GLOBAL pode disparar a descarga.
        await escritor.acrescentar(
            DatasetSplit.REFERENCE,
            "GRANDE",
            "2025/26",
            [_linha_qualquer(i, competicao="GRANDE") for i in range(60)],
        )
        await escritor.acrescentar(
            DatasetSplit.REFERENCE,
            "PEQUENA",
            "2025/26",
            [_linha_qualquer(i, competicao="PEQUENA") for i in range(20)],
        )
        assert not materializador.objects, "nenhuma partição encheu o pedaço ainda"

        # Mais 30 linhas na PEQUENA levam o total a 110 — acima do teto de 100.
        await escritor.acrescentar(
            DatasetSplit.REFERENCE,
            "PEQUENA",
            "2025/26",
            [_linha_qualquer(i, competicao="PEQUENA") for i in range(30)],
        )
        escritas = list(materializador.objects)
        assert len(escritas) == 1, escritas
        assert "competition=GRANDE" in escritas[0], escritas
        assert materializador.objects[escritas[0]][0].competition_code == "GRANDE"
        # E a PEQUENA continua aberta, com as cinquenta linhas dela.
        assert escritor.em_espera == 50

    async def test_um_teto_global_menor_que_o_pedaco_e_recusado(self) -> None:
        """Ele descarregaria antes de um pedaço encher, e produziria um arquivo
        por partida."""
        with pytest.raises(ValidationError, match="menor que o pedaço"):
            _EscritorDeParticoes(
                materializer=FakeFeatureMaterializer(),
                dataset_name=NOME,
                version="v1.0",
                part_rows=5_000,
                max_pending_rows=100,
            )


def _linha_qualquer(indice: int, *, competicao: str = "LIGA", temporada: str = "2025/26") -> Any:
    """Uma linha mínima para exercitar o ESCRITOR, e não a extração.

    ELA NÃO PASSA PELO EXTRATOR de propósito: o que se mede aqui é a política
    de descarga, e construir noventa e um snapshots reais por rodada faria o
    teste medir a extração.
    """
    snapshot = _snapshot_compartilhado()
    return MaterializedFeatureRow(
        key=HistoricalFeatureSnapshotKey(match_key=str(snapshot.as_of.match_id), grid_index=indice),
        snapshot=snapshot,
        split=DatasetSplit.REFERENCE,
        competition_code=competicao,
        season_label=temporada,
        kickoff=AGORA,
        grid_label=f"2H_{indice:03d}",
    )


class TestAValidacao:
    async def test_um_dataset_integro_passa(self, cenario: Cenario) -> None:
        versao = await cenario.criar_versao()
        await cenario.construir_versao(versao.id)
        relatorio = await cenario.validar.execute(
            version_id=versao.id, source=cenario.origem, actor=ATOR
        )
        assert relatorio.passed, relatorio.failures()
        assert relatorio.rows_verified == LINHAS_ESPERADAS
        assert relatorio.matches_rebuilt > 0

    async def test_ela_so_corre_sobre_validating(self, cenario: Cenario) -> None:
        versao = await cenario.criar_versao()
        with pytest.raises(ValidationError, match="VALIDATING"):
            await cenario.validar.execute(version_id=versao.id, source=cenario.origem, actor=ATOR)

    async def test_ordem_invertida_num_arquivo_e_acusada(self, cenario: Cenario) -> None:
        versao = await cenario.criar_versao()
        await cenario.construir_versao(versao.id)
        cenario.materializer.embaralhar = next(iter(cenario.materializer.objects))
        relatorio = await cenario.validar.execute(
            version_id=versao.id, source=cenario.origem, actor=ATOR
        )
        assert not relatorio.passed
        assert relatorio.out_of_order_objects

    async def test_um_objeto_faltando_no_registro_e_acusado(self, cenario: Cenario) -> None:
        versao = await cenario.criar_versao()
        await cenario.construir_versao(versao.id)
        registro = cenario.builds.objects[versao.id]
        registro.pop(next(iter(registro)))
        relatorio = await cenario.validar.execute(
            version_id=versao.id, source=cenario.origem, actor=ATOR
        )
        assert not relatorio.passed
        assert relatorio.missing_objects

    async def test_a_reprovacao_derruba_a_versao_para_failed(self, cenario: Cenario) -> None:
        versao = await cenario.criar_versao()
        await cenario.construir_versao(versao.id)
        cenario.materializer.embaralhar = next(iter(cenario.materializer.objects))
        await cenario.validar.execute(version_id=versao.id, source=cenario.origem, actor=ATOR)
        caida = await cenario.repo.version_by_id(versao.id)
        assert caida is not None
        assert caida.status is DatasetVersionStatus.FAILED

    async def test_uma_impressao_adulterada_e_acusada(self, cenario: Cenario) -> None:
        """A impressão reconstruída LENDO tem de bater com a calculada
        ESCREVENDO — se não bate, o conteúdo não é o que se pretendia."""
        versao = await cenario.criar_versao()
        await cenario.construir_versao(versao.id)
        atual = cenario.repo.versions[versao.id]
        cenario.repo.versions[versao.id] = replace(
            atual, raw_content_fingerprint=ContentHash("0" * 64)
        )
        relatorio = await cenario.validar.execute(
            version_id=versao.id, source=cenario.origem, actor=ATOR
        )
        assert not relatorio.passed
        assert relatorio.fingerprint_mismatch


class TestAPublicacao:
    async def _pronta(self, cenario: Cenario) -> Any:
        versao = await cenario.criar_versao()
        await cenario.construir_versao(versao.id)
        await cenario.validar.execute(version_id=versao.id, source=cenario.origem, actor=ATOR)
        return versao

    async def test_ela_publica_e_grava_o_manifesto_ao_lado_dos_dados(
        self, cenario: Cenario
    ) -> None:
        versao = await self._pronta(cenario)
        publicada = await cenario.publicar.execute(
            version_id=versao.id,
            dataset_name=NOME,
            actor=ATOR,
            reason="primeira população",
        )
        assert publicada.status is DatasetVersionStatus.READY
        assert publicada.is_readable
        assert cenario.materializer.manifests

    async def test_publicar_sem_validar_nao_e_alcancavel(self, cenario: Cenario) -> None:
        versao = await cenario.criar_versao()
        with pytest.raises(ValidationError, match="publicar sem validar"):
            await cenario.publicar.execute(
                version_id=versao.id, dataset_name=NOME, actor=ATOR, reason="cedo demais"
            )

    async def test_publicar_exige_motivo(self, cenario: Cenario) -> None:
        """Publicar é decidir que esta população é a base de comparação."""
        versao = await self._pronta(cenario)
        with pytest.raises(ValidationError, match="exige motivo"):
            await cenario.publicar.execute(
                version_id=versao.id, dataset_name=NOME, actor=ATOR, reason=""
            )

    async def test_a_segunda_publicacao_supera_a_primeira(self, cenario: Cenario) -> None:
        primeira = await self._pronta(cenario)
        await cenario.publicar.execute(
            version_id=primeira.id, dataset_name=NOME, actor=ATOR, reason="v1"
        )
        segunda = await cenario.criar_versao(version=DatasetVersion(major=1, minor=1))
        await cenario.construir_versao(segunda.id)
        await cenario.validar.execute(version_id=segunda.id, source=cenario.origem, actor=ATOR)
        await cenario.publicar.execute(
            version_id=segunda.id, dataset_name=NOME, actor=ATOR, reason="v1.1"
        )
        anterior = await cenario.repo.version_by_id(primeira.id)
        assert anterior is not None
        assert anterior.status is DatasetVersionStatus.SUPERSEDED
        assert anterior.superseded_by == segunda.id
        assert "FEATURE_DATASET_VERSION_SUPERSEDED" in cenario.audit.actions()

    async def test_a_ultima_publicada_e_a_que_a_producao_consulta(self, cenario: Cenario) -> None:
        versao = await self._pronta(cenario)
        await cenario.publicar.execute(
            version_id=versao.id, dataset_name=NOME, actor=ATOR, reason="v1"
        )
        dataset = await cenario.repo.dataset_by_name(NOME)
        assert dataset is not None
        atual = await cenario.repo.latest_ready(dataset.id)
        assert atual is not None
        assert atual.id == versao.id
