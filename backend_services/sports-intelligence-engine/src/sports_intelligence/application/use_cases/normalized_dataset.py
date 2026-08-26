"""Os casos de uso do ajuste causal e do dataset normalizado.

SEIS ETAPAS, E A SEPARAÇÃO ENTRE AS DUAS PRIMEIRAS E AS QUATRO SEGUINTES É A
DECISÃO CENTRAL DESTE ARQUIVO:

    fit               ajusta mediana e IQR sobre a REFERÊNCIA
    validate-fit      confere o ajuste e o publica
    ---------------------------------------------------------
    create            declara a versão normalizada
    build             transforma as linhas
    validate          reconfere o que foi escrito
    publish           torna a representação a base de comparação

O AJUSTE NÃO PERTENCE À CONSTRUÇÃO. Um mesmo conjunto de artefatos alimenta
VÁRIAS versões normalizadas — reconstruir o dataset depois de um defeito no
materializador não pode obrigar a reajustar noventa e um mil linhas, e sobretudo
não pode PRODUZIR OUTROS NÚMEROS. Se o ajuste fosse um passo da construção, duas
construções da mesma versão seriam dois ajustes, e a impressão diria que são
representações diferentes.

A ORDEM DAS DUAS LEITURAS TAMBÉM É DECISÃO. O ajuste lê SÓ a referência, com
projeção nos eixos `ROBUST`; a construção lê TUDO, com todos os eixos. São
custos muito diferentes, e juntá-los numa passagem faria o ajuste pagar a
leitura da avaliação — que ele não pode nem enxergar.

O QUE ESTE ARQUIVO NÃO FAZ, e cada ausência é decisão:

    não volta ao corpus       as features já foram extraídas (PR-05.5.1). Este
                              PR lê o Parquet cru e mais nada
    não reextrai              nem estado, nem contexto, nem consenso de mercado
    não pula linha            a normalização é 1:1, sempre
    não inventa escala        sem artefato a célula fica vazia, com o motivo
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, final

from sports_intelligence.domain.corpus.versions import DatasetVersionStatus
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit, SplitCounts
from sports_intelligence.domain.features.dataset.versions import (
    HistoricalFeatureDatasetVersion,
)
from sports_intelligence.domain.features.definitions import FeatureDefinition
from sports_intelligence.domain.features.extraction.catalog_v2 import (
    ExtendedFeatureCatalog,
    extended_feature_catalog,
)
from sports_intelligence.domain.features.fitting.artifact import FitStatus
from sports_intelligence.domain.features.normalized.artifacts import (
    CompetitionNormalizerArtifactBundle,
    NormalizerArtifactSet,
)
from sports_intelligence.domain.features.normalized.fit import (
    ReferenceFitScan,
    fit_bundles,
)
from sports_intelligence.domain.features.normalized.manifest import (
    NORMALIZED_MANIFEST_SCHEMA_VERSION,
    NormalizationAvailabilitySummary,
    NormalizedFeatureDatasetManifest,
    NormalizedObjectRef,
    artifact_map_of,
)
from sports_intelligence.domain.features.normalized.normalizer import (
    assert_fit_boundary_matches_split,
    causal_dataset_normalizer,
)
from sports_intelligence.domain.features.normalized.ordering import (
    PartitionKey,
    partition_of,
)
from sports_intelligence.domain.features.normalized.plan import (
    NormalizationPlan,
    plan_for,
)
from sports_intelligence.domain.features.normalized.rows import (
    NormalizedContentAccumulator,
    NormalizedFeatureRow,
    rebuild_normalized_content,
)
from sports_intelligence.domain.features.normalized.transform import (
    NormalizationTally,
    RawFeatureRowView,
    RowNormalizer,
)
from sports_intelligence.domain.features.normalized.versions import (
    DEFAULT_NORMALIZED_DATASET_NAME,
    NormalizedFeatureRepresentationSpec,
    NormalizedHistoricalFeatureDataset,
    NormalizedHistoricalFeatureDatasetVersion,
)
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.audit import AuditAction, AuditEntry
from sports_intelligence.domain.shared.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from sports_intelligence.domain.shared.identity import CompetitionId
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.ports.audit import AuditPort
from sports_intelligence.ports.clock import ClockPort
from sports_intelligence.ports.object_store.normalized_dataset import (
    NormalizedFeatureDatasetMaterializerPort,
    RawFeatureDatasetReaderPort,
)
from sports_intelligence.ports.repositories.corpus import (
    HistoricalCanonicalDatasetRepositoryPort,
)
from sports_intelligence.ports.repositories.feature_dataset import (
    HistoricalFeatureDatasetRepositoryPort,
)
from sports_intelligence.ports.repositories.normalized_dataset import (
    NormalizedDatasetBuildRepositoryPort,
    NormalizedFeatureDatasetRepositoryPort,
    NormalizerArtifactSetRepositoryPort,
)

#: Quantas linhas o leitor entrega por lote no AJUSTE.
#:
#: ELE PODE SER GRANDE porque o ajuste não segura linha nenhuma: cada lote é
#: consumido e descartado, e o que fica é um `array('d')` por eixo. Vinte mil
#: linhas de vinte e nove colunas são alguns megabytes transitórios.
FIT_BATCH_ROWS: Final[int] = 20_000

#: E quantas na CONSTRUÇÃO.
#:
#: ELE É MENOR porque aqui as linhas normalizadas ficam em buffer até o pedaço
#: fechar, e cada uma carrega cento e cinco células. O teto real é o do
#: escritor; este é só o tamanho da leitura.
BUILD_BATCH_ROWS: Final[int] = 2_000

#: Quantas linhas cabem num `part-*.parquet` normalizado.
#:
#: MAIOR QUE O DO CRU (5.000), e o motivo é medido em bytes por linha em
#: espera: uma `NormalizedFeatureRow` carrega cento e cinco `NormalizedCell`
#: com um `float` e dois textos curtos cada — uma fração do que um
#: `FeatureSnapshot` com cento e cinco `ComputedFeature` retém no dataset cru.
DEFAULT_PART_ROWS: Final[int] = 10_000

#: O TETO GLOBAL de linhas em espera, somando TODAS as partições abertas.
#:
#: ELE EXISTE PELA MESMA RAZÃO DO CRU e com o mesmo desenho: há um buffer por
#: `(metade, competição, temporada)` aberta, e uma varredura que atravessa vinte
#: partições mantém vinte buffers vivos. Sem o teto global, o pico deixa de
#: seguir o lote e passa a seguir quantas partições o dataset tem.
DEFAULT_MAX_PENDING_ROWS: Final[int] = 40_000

#: Teto de EXEMPLOS nomeados num relatório. Ele limita a LISTA, nunca a
#: contagem: despejar um milhão de chaves divergentes transformaria o relatório
#: no dataset, e truncar a contagem junto esconderia o tamanho do problema.
MAX_VALIDATION_EXAMPLES: Final[int] = 20


# ================================================================ ajuste ==


@final
@dataclass(frozen=True, slots=True)
class NormalizerFitOutput:
    """O que o ajuste produziu — contado, nunca estimado."""

    artifact_set: NormalizerArtifactSet
    reference_rows: int = 0
    competitions: int = 0
    artifacts: int = 0
    fitted: int = 0
    insufficient: int = 0
    degenerate: int = 0

    @property
    def fingerprint(self) -> str:
        return self.artifact_set.fingerprint

    def summary(self) -> Mapping[str, int]:
        return {
            "artifacts": self.artifacts,
            "competitions": self.competitions,
            "degenerate": self.degenerate,
            "fitted": self.fitted,
            "insufficient": self.insufficient,
            "reference_rows": self.reference_rows,
        }


@final
@dataclass(frozen=True, slots=True)
class FitNormalizerArtifactSet:
    """Ajusta a escala sobre a REFERÊNCIA de uma versão crua publicada.

    ELE LÊ `split=REFERENCE` E MAIS NADA (§29). A poda é por prefixo de chave,
    e não por filtro depois da leitura: filtrar depois funcionaria, leria o
    dobro, e faria a correção do ajuste depender de um `if`.

    A VARREDURA RECUSA uma linha de avaliação em vez de ignorá-la. Um leitor
    mal configurado — um que esquecesse a poda — produziria, com o filtro
    silencioso, um conjunto perfeitamente plausível sobre a população errada.
    """

    raw_datasets: HistoricalFeatureDatasetRepositoryPort
    corpus: HistoricalCanonicalDatasetRepositoryPort
    reader: RawFeatureDatasetReaderPort
    artifacts: NormalizerArtifactSetRepositoryPort
    clock: ClockPort
    audit: AuditPort

    async def execute(
        self,
        *,
        source_version_id: str,
        raw_dataset_name: str,
        actor: Actor,
        catalog: ExtendedFeatureCatalog | None = None,
        batch_rows: int = FIT_BATCH_ROWS,
        correlation_id: str | None = None,
        reuse_existing: bool = True,
    ) -> NormalizerFitOutput:
        origem = await _versao_crua_legivel(self.raw_datasets, source_version_id)
        catalogo = catalog or extended_feature_catalog()
        plano = plan_for(
            reference_end_exclusive_normalizer=causal_dataset_normalizer(
                reference_end_exclusive=origem.spec.reference_end_exclusive
            ),
            catalog=catalogo,
        )
        _conferir_espaco(plano, origem)
        normalizador = causal_dataset_normalizer(
            reference_end_exclusive=origem.spec.reference_end_exclusive
        )
        # AS DUAS FRONTEIRAS SÃO INDEPENDENTES NO CÓDIGO e têm de ser a mesma no
        # domínio: um normalizador cortado depois da divisão traria partidas de
        # avaliação para dentro da escala sem que número nenhum denunciasse.
        assert_fit_boundary_matches_split(
            normalizador, reference_end_exclusive=origem.spec.reference_end_exclusive
        )

        competicoes = await self._competicoes(origem)
        varredura = ReferenceFitScan(
            plan=plano,
            split_fingerprint=origem.spec.split_fingerprint,
            competitions=competicoes,
        )
        # A PROJEÇÃO É NOS EIXOS `ROBUST`, e só. Ler os cento e cinco para
        # ajustar vinte e nove pagaria quatro vezes o custo de leitura para
        # descartar o que sobra.
        async for lote in self.reader.stream_rows(
            dataset_name=raw_dataset_name,
            version=str(origem.version),
            split=DatasetSplit.REFERENCE,
            feature_keys=plano.robust_keys,
            batch_rows=batch_rows,
        ):
            for view in lote:
                varredura.observe(view)

        referencia = varredura.reference_identity()
        if not referencia.rows:
            raise ValidationError(
                f"a versão crua {origem.version} não tem linha de REFERÊNCIA: um "
                "ajuste sobre população vazia produziria um conjunto de artefatos que "
                "não normaliza nada, com impressão de conjunto completo",
                context={"source_version_id": source_version_id},
            )

        definicoes: dict[str, FeatureDefinition] = {
            spec.definition.key: spec.definition for spec in catalogo.specs
        }
        pacotes = fit_bundles(
            varredura,
            normalizer=normalizador,
            plan=plano,
            definitions=definicoes,
            reference=referencia,
        )
        return await self._persistir(
            pacotes,
            origem=origem,
            plano=plano,
            referencia_rows=referencia.rows,
            reference_fingerprint=referencia.fingerprint,
            actor=actor,
            correlation_id=correlation_id,
            reuse_existing=reuse_existing,
        )

    async def _persistir(
        self,
        pacotes: Sequence[CompetitionNormalizerArtifactBundle],
        *,
        origem: HistoricalFeatureDatasetVersion,
        plano: NormalizationPlan,
        referencia_rows: int,
        reference_fingerprint: str,
        actor: Actor,
        correlation_id: str | None,
        reuse_existing: bool,
    ) -> NormalizerFitOutput:
        agora = self.clock.now()
        conjunto = await self.artifacts.create_set(
            plan_fingerprint=plano.fingerprint,
            split_fingerprint=origem.spec.split_fingerprint,
            reference_end_exclusive=origem.spec.reference_end_exclusive,
            reference_fingerprint=reference_fingerprint,
            source_version_id=origem.id,
            source_raw_content_fingerprint=(
                ""
                if origem.raw_content_fingerprint is None
                else origem.raw_content_fingerprint.value
            ),
            reference_rows=referencia_rows,
            at=agora,
            created_by=actor,
        )
        await self.artifacts.save_bundles(conjunto.id, pacotes)
        # `DRAFT → BUILDING`, E AQUI O AJUSTE JÁ ACABOU. O grafo é o do corpus
        # e do dataset cru — `DRAFT → VALIDATING` não existe —, e o ajuste não
        # tem uma fase de construção separada da de cálculo: ele lê, calcula e
        # grava numa chamada. Marcar `BUILDING` ao fim é o que permite à
        # conferência seguir por `VALIDATING` sem que o salto proibido precise
        # ser aberto.
        await self.artifacts.transition(conjunto.id, target=DatasetVersionStatus.BUILDING, at=agora)
        completo = await self.artifacts.by_id(conjunto.id)
        if completo is None:  # pragma: no cover — acabou de ser gravado
            raise NotFoundError(f"o conjunto {conjunto.id} sumiu depois de gravado")

        if reuse_existing:
            # «ESTE AJUSTE JÁ EXISTE?» é perguntada DEPOIS de ajustar, e não
            # antes, porque a resposta depende da impressão — que só existe
            # quando os artefatos existem. O custo evitado não é o do ajuste: é
            # o de PUBLICAR uma segunda identidade para os mesmos números.
            anterior = await self._equivalente_publicado(completo)
            if anterior is not None:
                return _saida(anterior, referencia_rows)

        contagens = completo.counts()
        await _auditar(
            self.audit,
            self.clock,
            AuditAction.NORMALIZER_ARTIFACT_SET_FITTED,
            actor=actor,
            correlation_id=correlation_id,
            artifact_set_id=completo.id,
            artifact_set_fingerprint=completo.fingerprint,
            reference_fingerprint=reference_fingerprint,
            reference_rows=referencia_rows,
            competitions=len(completo.bundles),
            artifacts=completo.artifact_count,
            fitted=contagens[FitStatus.FITTED.value],
            degenerate=contagens[FitStatus.DEGENERATE_SCALE.value],
        )
        return _saida(completo, referencia_rows)

    async def _equivalente_publicado(
        self, conjunto: NormalizerArtifactSet
    ) -> NormalizerArtifactSet | None:
        existente = await self.artifacts.by_fingerprint(conjunto.fingerprint)
        if existente is None or existente.id == conjunto.id:
            return None
        return existente if existente.status.is_readable_corpus else None

    async def _competicoes(
        self, origem: HistoricalFeatureDatasetVersion
    ) -> Mapping[str, CompetitionId]:
        """`código → CompetitionId`, tirado do ESCOPO da versão do corpus.

        POR QUE ELE NÃO SAI DO PARQUET. O dataset cru grava o CÓDIGO da
        competição na partição, porque é ele que vira caminho legível; o
        artefato exige o `CompetitionId`, porque é ele que impede um artefato da
        Premier League de normalizar La Liga. A ponte entre os dois é o escopo
        do corpus — que é metadado de linhagem, e não uma tabela de fatos.
        """
        corpus = await self.corpus.version_by_id(origem.source_version_id)
        if corpus is None:
            raise NotFoundError(
                f"a versão de corpus {origem.source_version_id} não existe: sem o "
                "escopo dela não há como saber a que liga cada código pertence",
                context={"source_version_id": origem.source_version_id},
            )
        return {
            entrada.competition.value: entrada.competition_id for entrada in corpus.scope.entries
        }


@final
@dataclass(frozen=True, slots=True)
class ArtifactSetValidationReport:
    """O veredito do ajuste — com os números, e não só com um booleano."""

    artifact_set_id: str
    fingerprint: str
    competitions: int = 0
    artifacts: int = 0
    fitted: int = 0
    insufficient: int = 0
    degenerate: int = 0
    divergences: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.divergences

    def summary(self) -> Mapping[str, Any]:
        return {
            "artifacts": self.artifacts,
            "competitions": self.competitions,
            "degenerate": self.degenerate,
            "divergences": len(self.divergences),
            "fitted": self.fitted,
            "insufficient": self.insufficient,
            "passed": self.passed,
        }


@final
@dataclass(frozen=True, slots=True)
class ValidateNormalizerArtifactSet:
    """Confere o ajuste gravado e o publica.

    O QUE ELA CONFERE, e cada item é uma forma de a escala mentir:

        a impressão fecha           os números no banco são os que a produziram
        o plano é o mesmo           um pacote sob outro plano normalizaria sob
                                    decisões que ninguém tomou para o dataset
        a competição é a própria    um artefato da Premier no pacote da La Liga
        a fronteira é a da divisão  o corte do ajuste é o da metade
        FITTED tem IQR > 0          sem epsilon, e sem divisão por zero adiante
    """

    artifacts: NormalizerArtifactSetRepositoryPort
    raw_datasets: HistoricalFeatureDatasetRepositoryPort
    clock: ClockPort
    audit: AuditPort

    async def execute(
        self,
        *,
        artifact_set_id: str,
        actor: Actor,
        reason: str = "",
        correlation_id: str | None = None,
        publish: bool = True,
    ) -> ArtifactSetValidationReport:
        conjunto = await self.artifacts.by_id(artifact_set_id)
        if conjunto is None:
            raise NotFoundError(
                f"o conjunto de artefatos {artifact_set_id} não existe",
                context={"artifact_set_id": artifact_set_id},
            )
        divergencias = await self._conferir(conjunto)
        contagens = conjunto.counts()
        relatorio = ArtifactSetValidationReport(
            artifact_set_id=conjunto.id,
            fingerprint=conjunto.fingerprint,
            competitions=len(conjunto.bundles),
            artifacts=conjunto.artifact_count,
            fitted=contagens[FitStatus.FITTED.value],
            insufficient=contagens[FitStatus.INSUFFICIENT_SAMPLE.value],
            degenerate=contagens[FitStatus.DEGENERATE_SCALE.value],
            divergences=tuple(divergencias[:MAX_VALIDATION_EXAMPLES]),
        )
        agora = self.clock.now()
        if not relatorio.passed:
            if conjunto.can_move_to(DatasetVersionStatus.FAILED):
                await self.artifacts.transition(
                    conjunto.id,
                    target=DatasetVersionStatus.FAILED,
                    at=agora,
                    failure_reason="; ".join(relatorio.divergences)[:480],
                )
            await _auditar(
                self.audit,
                self.clock,
                AuditAction.NORMALIZER_ARTIFACT_SET_FAILED,
                actor=actor,
                correlation_id=correlation_id,
                reason="; ".join(relatorio.divergences)[:480],
                artifact_set_id=conjunto.id,
                divergences=len(divergencias),
            )
            return relatorio

        await _auditar(
            self.audit,
            self.clock,
            AuditAction.NORMALIZER_ARTIFACT_SET_VALIDATED,
            actor=actor,
            correlation_id=correlation_id,
            artifact_set_id=conjunto.id,
            artifact_set_fingerprint=conjunto.fingerprint,
            artifacts=relatorio.artifacts,
            fitted=relatorio.fitted,
            degenerate=relatorio.degenerate,
        )
        if not publish:
            return relatorio

        # BUILDING → VALIDATING → READY, e nunca um salto. O grafo é o mesmo
        # do corpus e do dataset cru, e a ausência de `DRAFT → READY` é o que
        # torna «publicar sem conferir» inalcançável por engano.
        #
        # O ESTADO É RELIDO DE CADA TRANSIÇÃO, e não do objeto carregado no
        # início: decidir a segunda transição olhando para um estado de antes
        # da primeira funciona por coincidência de sequência, e para de
        # funcionar no dia em que uma etapa for acrescentada no meio.
        estado = conjunto.status
        if estado is DatasetVersionStatus.BUILDING:
            estado = (
                await self.artifacts.transition(
                    conjunto.id, target=DatasetVersionStatus.VALIDATING, at=agora
                )
            ).status
        if not estado.is_readable_corpus:
            await self.artifacts.transition(
                conjunto.id, target=DatasetVersionStatus.READY, at=agora
            )
            await _auditar(
                self.audit,
                self.clock,
                AuditAction.NORMALIZER_ARTIFACT_SET_PUBLISHED,
                actor=actor,
                correlation_id=correlation_id,
                reason=reason or "ajuste conferido",
                artifact_set_id=conjunto.id,
                artifact_set_fingerprint=conjunto.fingerprint,
            )
        return relatorio

    async def _conferir(self, conjunto: NormalizerArtifactSet) -> list[str]:
        problemas: list[str] = []
        if not conjunto.bundles:
            problemas.append("o conjunto não tem pacote nenhum")
        for pacote in conjunto.bundles:
            if pacote.plan_fingerprint != conjunto.plan_fingerprint:
                problemas.append(
                    f"{pacote.competition}: ajustado sob outro plano "
                    f"({pacote.plan_fingerprint[:12]})"
                )
            for artefato in pacote.artifacts:
                if artefato.competition_id != pacote.competition_id:
                    problemas.append(
                        f"{pacote.competition}/{artefato.feature_key}: artefato de outra competição"
                    )
                if artefato.source_corpus_fingerprint != pacote.reference_fingerprint:
                    problemas.append(
                        f"{pacote.competition}/{artefato.feature_key}: ajustado sobre "
                        "uma referência diferente da do pacote"
                    )
                if artefato.status is FitStatus.FITTED and (
                    artefato.iqr is None or artefato.iqr <= 0
                ):
                    problemas.append(
                        f"{pacote.competition}/{artefato.feature_key}: FITTED com IQR "
                        f"{artefato.iqr}"
                    )
        origem = (
            None
            if not conjunto.source_version_id
            else await self.raw_datasets.version_by_id(conjunto.source_version_id)
        )
        if origem is not None:
            if origem.spec.split_fingerprint != conjunto.split_fingerprint:
                problemas.append("a divisão do conjunto não é a da versão crua de origem")
            if origem.spec.reference_end_exclusive != conjunto.reference_end_exclusive:
                problemas.append(
                    f"a fronteira do ajuste ({conjunto.reference_end_exclusive}) não é "
                    f"a da divisão ({origem.spec.reference_end_exclusive})"
                )
        return problemas


# ============================================================== criação ==


@final
@dataclass(frozen=True, slots=True)
class CreateNormalizedFeatureDatasetVersion:
    """Cria a versão normalizada em `DRAFT`, com a representação congelada.

    A REPRESENTAÇÃO ENTRA AQUI, E NÃO NA CONSTRUÇÃO. Uma versão cujo conjunto de
    artefatos fosse escolhido na hora de construir teria a identidade decidida
    depois de o nome existir — e duas construções da «1.0» sob ajustes
    diferentes seriam as duas legítimas.
    """

    normalized: NormalizedFeatureDatasetRepositoryPort
    raw_datasets: HistoricalFeatureDatasetRepositoryPort
    artifacts: NormalizerArtifactSetRepositoryPort
    clock: ClockPort
    audit: AuditPort

    async def execute(
        self,
        *,
        version: DatasetVersion,
        source_version_id: str,
        artifact_set_id: str,
        actor: Actor,
        dataset_name: str = DEFAULT_NORMALIZED_DATASET_NAME,
        catalog: ExtendedFeatureCatalog | None = None,
        description: str | None = None,
        correlation_id: str | None = None,
    ) -> NormalizedHistoricalFeatureDatasetVersion:
        origem = await _versao_crua_legivel(self.raw_datasets, source_version_id)
        conjunto = await self.artifacts.by_id(artifact_set_id)
        if conjunto is None:
            raise NotFoundError(
                f"o conjunto de artefatos {artifact_set_id} não existe",
                context={"artifact_set_id": artifact_set_id},
            )
        if not conjunto.is_readable:
            raise ValidationError(
                f"o conjunto de artefatos está em {conjunto.status}: normalizar sobre "
                "um ajuste não publicado produziria um dataset cuja escala ainda pode "
                "mudar debaixo dele",
                context={"status": conjunto.status.value},
            )
        if conjunto.split_fingerprint != origem.spec.split_fingerprint:
            raise ValidationError(
                "o ajuste foi feito sob outra divisão: a referência dele não é a "
                "metade de referência desta versão crua, e a invariância sob mutação "
                "da avaliação deixaria de valer sem que nada denunciasse",
                context={
                    "artifact_split": conjunto.split_fingerprint,
                    "raw_split": origem.spec.split_fingerprint,
                },
            )

        plano = plan_for(
            reference_end_exclusive_normalizer=causal_dataset_normalizer(
                reference_end_exclusive=origem.spec.reference_end_exclusive
            ),
            catalog=catalog or extended_feature_catalog(),
        )
        if plano.fingerprint != conjunto.plan_fingerprint:
            raise ValidationError(
                "o plano de hoje não é o plano sob o qual o ajuste foi feito: "
                "normalizar assim aplicaria escalas ajustadas para uma classificação "
                "de eixos a outra classificação",
                context={
                    "plan": plano.fingerprint,
                    "artifact_set_plan": conjunto.plan_fingerprint,
                },
            )
        _conferir_espaco(plano, origem)

        agora = self.clock.now()
        dataset = await self._dataset(
            dataset_name,
            source_dataset_id=origem.dataset_id,
            at=agora,
            actor=actor,
            description=description,
        )
        existente = await self.normalized.version_of(dataset.id, version)
        if existente is not None:
            raise ConflictError(
                f"a versão {version} do dataset {dataset_name} já existe: «1.0» "
                "precisa significar um conteúdo só, para sempre",
                context={"version_id": existente.id, "status": existente.status.value},
            )
        representacao = NormalizedFeatureRepresentationSpec.of(
            plan=plano,
            artifact_set_id=conjunto.id,
            artifact_set_fingerprint=conjunto.fingerprint,
        )
        criada = await self.normalized.create_version(
            dataset_id=dataset.id,
            version=version,
            source_version_id=origem.id,
            source_version=origem.version,
            source_raw_content_fingerprint=_impressao_crua(origem),
            source_row_count=origem.row_count,
            representation=representacao,
            at=agora,
            created_by=actor,
        )
        await _auditar(
            self.audit,
            self.clock,
            AuditAction.NORMALIZED_DATASET_VERSION_CREATED,
            actor=actor,
            correlation_id=correlation_id,
            dataset_name=dataset_name,
            version=str(version),
            version_id=criada.id,
            source_version=str(origem.version),
            source_rows=origem.row_count,
            artifact_set_id=conjunto.id,
            representation_fingerprint=representacao.fingerprint,
        )
        return criada

    async def _dataset(
        self,
        name: str,
        *,
        source_dataset_id: str,
        at: Instant,
        actor: Actor,
        description: str | None,
    ) -> NormalizedHistoricalFeatureDataset:
        existente = await self.normalized.dataset_by_name(name)
        if existente is not None:
            return existente
        criado = await self.normalized.create_dataset(
            name=name,
            source_dataset_id=source_dataset_id,
            at=at,
            created_by=actor,
            description=description,
        )
        await _auditar(
            self.audit,
            self.clock,
            AuditAction.NORMALIZED_DATASET_CREATED,
            actor=actor,
            correlation_id=None,
            dataset_name=name,
            # `feature_dataset_id` E NÃO `dataset_id`: aquele nome é PARÂMETRO
            # de `AuditEntry.of`, tipado como `DatasetId`. Passar um id de
            # dataset normalizado por ele o faria ser lido como um dataset de
            # ingestão — e a gravação quebra na hora, que é o melhor jeito de
            # descobrir.
            feature_dataset_id=criado.id,
        )
        return criado


# ========================================================== construção ==


@final
@dataclass(frozen=True, slots=True)
class NormalizedBuildOutput:
    """O que a construção produziu — contado, nunca estimado."""

    version: NormalizedHistoricalFeatureDatasetVersion
    rows_read: int = 0
    rows_written: int = 0
    matches: int = 0
    objects: tuple[NormalizedObjectRef, ...] = ()
    bytes: int = 0
    counts: SplitCounts = field(default_factory=SplitCounts)
    fingerprint: str = ""
    reference_fingerprint: str = ""
    evaluation_fingerprint: str = ""
    availability: NormalizationAvailabilitySummary = field(
        default_factory=NormalizationAvailabilitySummary
    )
    rows_by_partition: Mapping[str, int] = field(default_factory=dict)
    peak_pending_rows: int = 0
    peak_open_partitions: int = 0


@final
@dataclass(frozen=True, slots=True)
class BuildNormalizedFeatureDatasetVersion:
    """Transforma as linhas cruas, 1:1, e grava o manifesto.

    A MEMÓRIA É LIMITADA POR CONSTRUÇÃO, e não por esperança: o leitor entrega
    lotes, o escritor tem teto global, e as impressões são acumuladas em fluxo.
    Nada aqui cresce com o tamanho do dataset.

    A LEITURA É DE TUDO — as duas metades. Diferente do ajuste, a construção
    normaliza também a avaliação: as linhas dela continuam existindo, com os
    mesmos eixos, sob a mesma escala. É isso que torna a comparação possível.
    """

    normalized: NormalizedFeatureDatasetRepositoryPort
    builds: NormalizedDatasetBuildRepositoryPort
    raw_datasets: HistoricalFeatureDatasetRepositoryPort
    artifacts: NormalizerArtifactSetRepositoryPort
    reader: RawFeatureDatasetReaderPort
    materializer: NormalizedFeatureDatasetMaterializerPort
    clock: ClockPort
    audit: AuditPort

    async def execute(
        self,
        *,
        version_id: str,
        dataset_name: str,
        raw_dataset_name: str,
        actor: Actor,
        catalog: ExtendedFeatureCatalog | None = None,
        part_rows: int = DEFAULT_PART_ROWS,
        max_pending_rows: int = DEFAULT_MAX_PENDING_ROWS,
        batch_rows: int = BUILD_BATCH_ROWS,
        correlation_id: str | None = None,
    ) -> NormalizedBuildOutput:
        versao = await self._versao(version_id)
        versao.require_transition(DatasetVersionStatus.BUILDING)
        origem = await _versao_crua_legivel(self.raw_datasets, versao.source_version_id)
        conjunto = await self.artifacts.by_id(versao.representation.artifact_set_id)
        if conjunto is None:
            raise NotFoundError(
                f"o conjunto {versao.representation.artifact_set_id} não existe",
                context={"artifact_set_id": versao.representation.artifact_set_id},
            )
        plano = plan_for(
            reference_end_exclusive_normalizer=causal_dataset_normalizer(
                reference_end_exclusive=origem.spec.reference_end_exclusive
            ),
            catalog=catalog or extended_feature_catalog(),
        )
        # O `RowNormalizer` RECUSA a combinação errada de plano, conjunto e
        # representação — as três impressões têm de fechar antes da primeira
        # linha, e não na milésima.
        normalizador = RowNormalizer(
            plan=plano,
            artifact_set=conjunto,
            representation=versao.representation,
        )

        agora = self.clock.now()
        await self.normalized.transition(version_id, target=DatasetVersionStatus.BUILDING, at=agora)
        execucao = await self.builds.start_run(version_id=version_id, at=agora, started_by=actor)
        try:
            resultado = await self._materializar(
                versao,
                normalizador=normalizador,
                plano=plano,
                dataset_name=dataset_name,
                raw_dataset_name=raw_dataset_name,
                raw_version=str(origem.version),
                part_rows=part_rows,
                max_pending_rows=max_pending_rows,
                batch_rows=batch_rows,
            )
        except Exception as erro:
            momento = self.clock.now()
            await self.builds.finish_run(
                execucao.id,
                status=DatasetVersionStatus.FAILED,
                at=momento,
                failure_reason=str(erro)[:480],
            )
            await self.normalized.transition(
                version_id,
                target=DatasetVersionStatus.FAILED,
                at=momento,
                failure_reason=str(erro)[:480],
            )
            await _auditar(
                self.audit,
                self.clock,
                AuditAction.NORMALIZED_DATASET_VERSION_FAILED,
                actor=actor,
                correlation_id=correlation_id,
                reason=str(erro)[:480],
                version_id=version_id,
            )
            raise

        manifesto = _manifesto(
            versao,
            origem=origem,
            plano=plano,
            conjunto=conjunto,
            dataset_name=dataset_name,
            resultado=resultado,
            at=self.clock.now(),
        )
        await self.builds.record_objects(version_id, resultado.objects)
        await self.builds.save_manifest(
            manifesto,
            manifest_key=self.materializer.manifest_key(
                dataset_name=dataset_name, version=str(versao.version)
            ),
            manifest_sha256=manifesto.manifest_sha256,
        )
        fim = self.clock.now()
        await self.builds.finish_run(
            execucao.id,
            status=DatasetVersionStatus.VALIDATING,
            at=fim,
            rows_read=resultado.rows_read,
            rows_written=resultado.rows_written,
            objects_written=len(resultado.objects),
            bytes_written=resultado.bytes,
            artifact_unavailable_cells=resultado.availability.artifact_unavailable,
        )
        movida = await self.normalized.transition(
            version_id,
            target=DatasetVersionStatus.VALIDATING,
            at=fim,
            normalized_content_fingerprint=ContentHash(resultado.fingerprint),
            normalized_reference_content_fingerprint=ContentHash(resultado.reference_fingerprint),
            normalized_evaluation_content_fingerprint=ContentHash(resultado.evaluation_fingerprint),
            manifest_id=manifesto.id,
            match_count=resultado.matches,
            row_count=resultado.rows_written,
            counts=resultado.counts,
        )
        await _auditar(
            self.audit,
            self.clock,
            AuditAction.NORMALIZED_DATASET_VERSION_BUILT,
            actor=actor,
            correlation_id=correlation_id,
            version_id=version_id,
            rows=resultado.rows_written,
            matches=resultado.matches,
            objects=len(resultado.objects),
            normalized_fingerprint=resultado.fingerprint,
            reference_fingerprint=resultado.reference_fingerprint,
            artifact_unavailable_cells=resultado.availability.artifact_unavailable,
            peak_pending_rows=resultado.peak_pending_rows,
        )
        return _com_versao(resultado, movida)

    async def _versao(self, version_id: str) -> NormalizedHistoricalFeatureDatasetVersion:
        versao = await self.normalized.version_by_id(version_id)
        if versao is None:
            raise NotFoundError(
                f"a versão normalizada {version_id} não existe",
                context={"version_id": version_id},
            )
        return versao

    async def _materializar(
        self,
        versao: NormalizedHistoricalFeatureDatasetVersion,
        *,
        normalizador: RowNormalizer,
        plano: NormalizationPlan,
        dataset_name: str,
        raw_dataset_name: str,
        raw_version: str,
        part_rows: int,
        max_pending_rows: int,
        batch_rows: int,
    ) -> NormalizedBuildOutput:
        escritor = _EscritorNormalizado(
            materializer=self.materializer,
            dataset_name=dataset_name,
            version=str(versao.version),
            part_rows=part_rows,
            max_pending_rows=max_pending_rows,
        )
        acumulador = NormalizedContentAccumulator(
            representation_fingerprint=versao.representation.fingerprint,
            plan_fingerprint=plano.fingerprint,
            artifact_set_fingerprint=versao.representation.artifact_set_fingerprint,
        )
        contagem = NormalizationTally()
        partidas: set[str] = set()
        por_metade: dict[DatasetSplit, set[str]] = {
            DatasetSplit.REFERENCE: set(),
            DatasetSplit.EVALUATION: set(),
        }
        linhas_por_metade = {DatasetSplit.REFERENCE: 0, DatasetSplit.EVALUATION: 0}
        lidas = 0

        async for lote in self.reader.stream_rows(
            dataset_name=raw_dataset_name,
            version=raw_version,
            feature_keys=None,
            batch_rows=batch_rows,
        ):
            # AS LINHAS SÃO AGRUPADAS POR PARTIÇÃO DENTRO DO LOTE, e não
            # entregues uma a uma ao escritor: um lote atravessa no máximo
            # duas partições em condições normais, e agrupar evita uma
            # chamada de admissão por linha.
            for chave, normalizadas in _por_particao(lote, normalizador).items():
                for linha in normalizadas:
                    acumulador.update(linha)
                    contagem.update(linha)
                    partidas.add(linha.key.match_key)
                    por_metade[linha.split].add(linha.key.match_key)
                    linhas_por_metade[linha.split] += 1
                await escritor.acrescentar(*chave, normalizadas)
            lidas += len(lote)
        await escritor.finalizar()

        identidade = acumulador.finalize()
        return NormalizedBuildOutput(
            version=versao,
            rows_read=lidas,
            rows_written=identidade.rows,
            matches=len(partidas),
            objects=tuple(escritor.objetos),
            bytes=sum(o.size_bytes for o in escritor.objetos),
            counts=SplitCounts(
                reference_matches=len(por_metade[DatasetSplit.REFERENCE]),
                evaluation_matches=len(por_metade[DatasetSplit.EVALUATION]),
                reference_rows=linhas_por_metade[DatasetSplit.REFERENCE],
                evaluation_rows=linhas_por_metade[DatasetSplit.EVALUATION],
            ),
            fingerprint=identidade.fingerprint,
            reference_fingerprint=identidade.reference_fingerprint,
            evaluation_fingerprint=identidade.evaluation_fingerprint,
            availability=NormalizationAvailabilitySummary(
                total_cells=contagem.total_cells,
                by_state=dict(sorted(contagem.by_state.items())),
                by_source_state=dict(sorted(contagem.by_source_state.items())),
            ),
            rows_by_partition=dict(escritor.linhas_por_particao),
            peak_pending_rows=escritor.pico_em_espera,
            peak_open_partitions=escritor.pico_de_particoes,
        )


@final
class _EscritorNormalizado:
    """Acumula linhas normalizadas por partição e descarrega quando enche.

    É O MESMO DESENHO DO ESCRITOR DO DATASET CRU, e a repetição é deliberada:
    generalizar os dois num escritor comum exigiria parametrizar o tipo da linha,
    o tipo do objeto e o materializador — e produziria uma abstração cujo único
    uso seria esconder duas listas de cinquenta linhas.

    O TETO É CONFERIDO ANTES DA ADMISSÃO, e a ordem é o que torna o limite
    EXATO. Conferir depois deixaria o pico ser `teto + lote`.
    """

    __slots__ = (
        "_dataset_name",
        "_em_espera",
        "_materializer",
        "_max_pending_rows",
        "_part_rows",
        "_pedacos",
        "_version",
        "linhas_por_particao",
        "objetos",
        "pendentes",
        "pico_de_particoes",
        "pico_em_espera",
    )

    def __init__(
        self,
        *,
        materializer: NormalizedFeatureDatasetMaterializerPort,
        dataset_name: str,
        version: str,
        part_rows: int,
        max_pending_rows: int,
    ) -> None:
        if part_rows < 1:
            raise ValidationError(f"pedaço de {part_rows} linhas: ele nunca fecharia")
        if max_pending_rows < part_rows:
            raise ValidationError(
                f"teto global de {max_pending_rows} linhas menor que o pedaço de "
                f"{part_rows}: o escritor descarregaria antes de um pedaço encher e "
                "produziria uma enxurrada de arquivos miúdos"
            )
        self._materializer = materializer
        self._dataset_name = dataset_name
        self._version = version
        self._part_rows = part_rows
        self._max_pending_rows = max_pending_rows
        self._em_espera = 0
        self.pendentes: dict[tuple[DatasetSplit, str, str], list[NormalizedFeatureRow]] = {}
        self._pedacos: dict[tuple[DatasetSplit, str, str], int] = {}
        self.objetos: list[NormalizedObjectRef] = []
        self.linhas_por_particao: dict[str, int] = {}
        # A INSTRUMENTAÇÃO É PÚBLICA, e não de teste: «a memória é limitada» é
        # afirmação sobre execução, e sem estes números ela só se confere com um
        # profiler acoplado — que ninguém acopla em produção.
        self.pico_em_espera = 0
        self.pico_de_particoes = 0

    async def acrescentar(
        self,
        split: DatasetSplit,
        competition: str,
        season: str,
        rows: Sequence[NormalizedFeatureRow],
    ) -> None:
        if not rows:
            return
        chave = (split, competition, season)
        while self._em_espera + len(rows) > self._max_pending_rows:
            maior = max(self.pendentes, key=lambda c: len(self.pendentes[c]), default=None)
            if maior is None or not self.pendentes[maior]:
                break
            await self._descarregar(maior)
        buffer = self.pendentes.setdefault(chave, [])
        buffer.extend(rows)
        self._em_espera += len(rows)
        self.pico_em_espera = max(self.pico_em_espera, self._em_espera)
        self.pico_de_particoes = max(
            self.pico_de_particoes, sum(1 for b in self.pendentes.values() if b)
        )
        if len(buffer) >= self._part_rows:
            await self._descarregar(chave)

    async def finalizar(self) -> None:
        for chave in sorted(self.pendentes, key=lambda c: (c[0].value, c[1], c[2])):
            await self._descarregar(chave)

    async def _descarregar(self, chave: tuple[DatasetSplit, str, str]) -> None:
        linhas = self.pendentes.get(chave)
        if not linhas:
            return
        split, competition, season = chave
        indice = self._pedacos.get(chave, 0)
        self._em_espera -= len(linhas)
        objeto = await self._materializer.materialize_partition(
            dataset_name=self._dataset_name,
            version=self._version,
            split=split,
            competition=competition,
            season=season,
            part_index=indice,
            rows=linhas,
        )
        self._pedacos[chave] = indice + 1
        self.pendentes[chave] = []
        if objeto is None:
            return
        self.objetos.append(objeto)
        rotulo = f"{split.value}/{competition}/{season}"
        self.linhas_por_particao[rotulo] = (
            self.linhas_por_particao.get(rotulo, 0) + objeto.row_count
        )


# ============================================================= validação ==


@final
@dataclass(frozen=True, slots=True)
class NormalizedValidationReport:
    """O veredito da construção — com os números, e não só com um booleano."""

    version_id: str
    objects: int = 0
    rows: int = 0
    source_rows: int = 0
    fingerprint: str = ""
    reference_fingerprint: str = ""
    evaluation_fingerprint: str = ""
    integrity_failures: tuple[str, ...] = ()
    content_failures: tuple[str, ...] = ()
    cardinality_failures: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.failures

    @property
    def failures(self) -> tuple[str, ...]:
        return (
            *self.integrity_failures,
            *self.content_failures,
            *self.cardinality_failures,
        )

    def summary(self) -> Mapping[str, Any]:
        return {
            "cardinality_failures": len(self.cardinality_failures),
            "content_failures": len(self.content_failures),
            "integrity_failures": len(self.integrity_failures),
            "objects": self.objects,
            "passed": self.passed,
            "rows": self.rows,
            "source_rows": self.source_rows,
        }


@final
@dataclass(frozen=True, slots=True)
class ValidateNormalizedFeatureDatasetVersion:
    """Reconfere o que foi escrito, LENDO — e não confiando na construção.

    TRÊS FAMÍLIAS DE CONFERÊNCIA, e cada uma pega um defeito diferente:

        integridade    o sha256 de cada objeto ainda fecha
        conteúdo       as impressões reconstruídas das linhas gravadas
                       coincidem com as que a construção calculou
        cardinalidade  o dataset normalizado tem EXATAMENTE tantas linhas
                       quanto o cru (§94)

    A SEGUNDA É A QUE IMPORTA MAIS. A construção calcula as impressões
    ESCREVENDO; a validação as recalcula LENDO, e as duas só coincidem se o que
    foi escrito for o que foi calculado. Reusar o número da construção aqui
    conferiria a construção contra ela mesma.
    """

    normalized: NormalizedFeatureDatasetRepositoryPort
    builds: NormalizedDatasetBuildRepositoryPort
    raw_datasets: HistoricalFeatureDatasetRepositoryPort
    reader: RawFeatureDatasetReaderPort
    materializer: NormalizedFeatureDatasetMaterializerPort
    clock: ClockPort
    audit: AuditPort

    async def execute(
        self,
        *,
        version_id: str,
        raw_dataset_name: str,
        actor: Actor,
        correlation_id: str | None = None,
    ) -> NormalizedValidationReport:
        versao = await self.normalized.version_by_id(version_id)
        if versao is None:
            raise NotFoundError(
                f"a versão normalizada {version_id} não existe",
                context={"version_id": version_id},
            )
        objetos = [
            o
            for o in await self.builds.objects_of(version_id)
            if o.content_type != "application/json"
        ]
        if not objetos:
            raise ValidationError(
                f"a versão {versao.version} não registrou objeto nenhum: validar um "
                "dataset sem conteúdo alcançável aprovaria um nome apontando para nada"
            )

        integridade: list[str] = []
        linhas: list[tuple[PartitionKey, HistoricalFeatureSnapshotKey, DatasetSplit, str]] = []
        for objeto in sorted(objetos, key=lambda o: o.object_key):
            sha, tamanho, conteudo = await self.materializer.verify_object(
                object_key=objeto.object_key
            )
            if sha != objeto.sha256.value:
                integridade.append(f"{objeto.object_key}: sha256 divergente")
            if tamanho != objeto.size_bytes:
                integridade.append(
                    f"{objeto.object_key}: {tamanho} bytes contra {objeto.size_bytes} registrados"
                )
            if len(conteudo) != objeto.row_count:
                integridade.append(
                    f"{objeto.object_key}: {len(conteudo)} linhas contra "
                    f"{objeto.row_count} registradas"
                )
            particao = partition_of(
                split=objeto.split.value,
                competition=objeto.competition,
                season=objeto.season,
            )
            for partida, indice, metade, digesto in conteudo:
                linhas.append(
                    (
                        particao,
                        HistoricalFeatureSnapshotKey(match_key=partida, grid_index=indice),
                        DatasetSplit(metade),
                        digesto,
                    )
                )

        # A ORDEM CANÔNICA É RESTAURADA AQUI, e ela é em DOIS níveis: as
        # partições em ordem de `(metade, competição, temporada)`, e as chaves
        # em ordem dentro de cada uma. É a mesma ordem em que a construção
        # percorreu o dataset — e ordenar só pela chave, como a primeira versão
        # fazia, reprovaria um dataset correto de mais de uma partição: as
        # partidas são `uuid5`, e as chaves de duas competições se intercalam.
        linhas.sort(key=lambda t: (t[0], t[1]))
        conteudo_falhas: list[str] = []
        try:
            reconstruida = rebuild_normalized_content(
                linhas,
                representation_fingerprint=versao.representation.fingerprint,
                plan_fingerprint=versao.representation.plan_fingerprint,
                artifact_set_fingerprint=(versao.representation.artifact_set_fingerprint),
            )
        except ValidationError as erro:
            conteudo_falhas.append(f"reconstrução recusada: {erro}")
            reconstruida = None
        if reconstruida is not None:
            conteudo_falhas.extend(_comparar(versao, reconstruida))

        cardinalidade = await self._cardinalidade(
            versao, raw_dataset_name=raw_dataset_name, gravadas=len(linhas)
        )
        relatorio = NormalizedValidationReport(
            version_id=version_id,
            objects=len(objetos),
            rows=len(linhas),
            source_rows=versao.source_row_count,
            fingerprint="" if reconstruida is None else reconstruida.fingerprint,
            reference_fingerprint=(
                "" if reconstruida is None else reconstruida.reference_fingerprint
            ),
            evaluation_fingerprint=(
                "" if reconstruida is None else reconstruida.evaluation_fingerprint
            ),
            integrity_failures=tuple(integridade[:MAX_VALIDATION_EXAMPLES]),
            content_failures=tuple(conteudo_falhas[:MAX_VALIDATION_EXAMPLES]),
            cardinality_failures=tuple(cardinalidade[:MAX_VALIDATION_EXAMPLES]),
        )
        await _auditar(
            self.audit,
            self.clock,
            AuditAction.NORMALIZED_DATASET_VERSION_VALIDATED,
            actor=actor,
            correlation_id=correlation_id,
            reason=None if relatorio.passed else "; ".join(relatorio.failures)[:480],
            version_id=version_id,
            objects=relatorio.objects,
            rows=relatorio.rows,
            passed=relatorio.passed,
        )
        if not relatorio.passed and versao.can_move_to(DatasetVersionStatus.FAILED):
            await self.normalized.transition(
                version_id,
                target=DatasetVersionStatus.FAILED,
                at=self.clock.now(),
                failure_reason="; ".join(relatorio.failures)[:480],
            )
        return relatorio

    async def _cardinalidade(
        self,
        versao: NormalizedHistoricalFeatureDatasetVersion,
        *,
        raw_dataset_name: str,
        gravadas: int,
    ) -> list[str]:
        """O contrato 1:1, conferido contra o RODAPÉ do Parquet cru.

        A CONTAGEM DO CRU VEM DO ARQUIVO, e não da coluna do banco. A coluna diz
        o que a construção CONTOU; o rodapé diz o que está lá — e a diferença
        entre os dois é exatamente o defeito que esta conferência procura.
        """
        problemas: list[str] = []
        origem = await self.raw_datasets.version_by_id(versao.source_version_id)
        if origem is None:
            problemas.append("a versão crua de origem não existe mais")
            return problemas
        no_arquivo = await self.reader.row_count(
            dataset_name=raw_dataset_name, version=str(origem.version)
        )
        if gravadas != no_arquivo:
            problemas.append(
                f"{gravadas} linhas normalizadas contra {no_arquivo} cruas: a "
                "normalização é 1:1, e uma linha a menos é uma partida "
                "silenciosamente fora do conjunto de comparação"
            )
        if origem.row_count and no_arquivo != origem.row_count:
            problemas.append(
                f"o dataset cru registra {origem.row_count} linhas e o arquivo tem "
                f"{no_arquivo}: o defeito é a MONTANTE deste PR"
            )
        return problemas


# ============================================================ publicação ==


@final
@dataclass(frozen=True, slots=True)
class PublishNormalizedFeatureDatasetVersion:
    """`VALIDATING → READY`, com o manifesto gravado ao lado dos dados.

    PUBLICAR É UMA DECISÃO, e a trilha exige motivo: a partir daqui esta
    representação é a base sob a qual duas partidas passam a ser comparáveis, e
    «por que esta e não a anterior» tem de ter resposta depois.
    """

    normalized: NormalizedFeatureDatasetRepositoryPort
    builds: NormalizedDatasetBuildRepositoryPort
    materializer: NormalizedFeatureDatasetMaterializerPort
    clock: ClockPort
    audit: AuditPort

    async def execute(
        self,
        *,
        version_id: str,
        dataset_name: str,
        actor: Actor,
        reason: str,
        correlation_id: str | None = None,
        supersede_previous: bool = True,
    ) -> NormalizedHistoricalFeatureDatasetVersion:
        versao = await self.normalized.version_by_id(version_id)
        if versao is None:
            raise NotFoundError(
                f"a versão normalizada {version_id} não existe",
                context={"version_id": version_id},
            )
        versao.require_transition(DatasetVersionStatus.READY)
        manifesto = await self.builds.manifest_by_version(version_id)
        if manifesto is None:
            raise ValidationError(
                "publicar uma versão sem manifesto: o dataset chegaria ao consumidor "
                "sem plano, sem mapa de artefatos e sem impressão"
            )
        if versao.row_count <= 0:
            raise ValidationError(
                "publicar uma versão com zero linhas: quem a consultasse receberia "
                "«sem vizinhos» em vez de um erro"
            )
        if versao.normalized_reference_content_fingerprint is None:
            raise ValidationError(
                "publicar sem a impressão de REFERÊNCIA: sem ela, «a base de "
                "comparação não mudou» deixa de ser verificável entre duas publicações"
            )

        # O MANIFESTO VAI PARA O BUCKET AGORA, e não na construção: um
        # `manifest.json` ao lado de dados ainda não conferidos afirmaria que
        # eles estão publicados.
        await self.materializer.write_manifest(
            dataset_name=dataset_name,
            version=str(versao.version),
            document=manifesto.to_json(),
        )

        anterior = await self.normalized.latest_ready(versao.dataset_id)
        agora = self.clock.now()
        publicada = await self.normalized.transition(
            version_id, target=DatasetVersionStatus.READY, at=agora
        )
        await _auditar(
            self.audit,
            self.clock,
            AuditAction.NORMALIZED_DATASET_VERSION_PUBLISHED,
            actor=actor,
            correlation_id=correlation_id,
            reason=reason,
            version_id=version_id,
            version=str(versao.version),
            rows=versao.row_count,
            matches=versao.match_count,
            representation_fingerprint=versao.representation.fingerprint,
            reference_fingerprint=(versao.normalized_reference_content_fingerprint.value),
        )
        if supersede_previous and anterior is not None and anterior.id != version_id:
            await self.normalized.transition(
                anterior.id,
                target=DatasetVersionStatus.SUPERSEDED,
                at=agora,
                superseded_by=version_id,
            )
            await _auditar(
                self.audit,
                self.clock,
                AuditAction.NORMALIZED_DATASET_VERSION_SUPERSEDED,
                actor=actor,
                correlation_id=correlation_id,
                reason=reason,
                version_id=anterior.id,
                superseded_by=version_id,
                # A PERGUNTA DO PR, RESPONDIDA NA TRILHA: a base de comparação
                # mudou entre a anterior e esta? Duas linhas da trilha bastam.
                previous_reference_fingerprint=(
                    ""
                    if anterior.normalized_reference_content_fingerprint is None
                    else anterior.normalized_reference_content_fingerprint.value
                ),
            )
        return publicada


# ================================================================ apoio ==


def _por_particao(
    lote: Sequence[RawFeatureRowView], normalizador: RowNormalizer
) -> dict[tuple[DatasetSplit, str, str], list[NormalizedFeatureRow]]:
    """As linhas do lote normalizadas e agrupadas, PRESERVANDO a ordem.

    `dict` MANTÉM A ORDEM DE INSERÇÃO em Python, e é dela que se depende aqui:
    as linhas chegam em ordem de chave, e sair agrupadas por partição não pode
    embaralhá-las dentro de cada grupo.
    """
    grupos: dict[tuple[DatasetSplit, str, str], list[NormalizedFeatureRow]] = {}
    for view in lote:
        linha = normalizador.normalize(view)
        chave = (linha.split, linha.competition, linha.season)
        grupos.setdefault(chave, []).append(linha)
    return grupos


def _comparar(versao: NormalizedHistoricalFeatureDatasetVersion, reconstruida: Any) -> list[str]:
    """As três impressões reconstruídas contra as três gravadas."""
    problemas: list[str] = []
    for rotulo, gravada, refeita in (
        (
            "global",
            versao.normalized_content_fingerprint,
            reconstruida.fingerprint,
        ),
        (
            "de referência",
            versao.normalized_reference_content_fingerprint,
            reconstruida.reference_fingerprint,
        ),
        (
            "de avaliação",
            versao.normalized_evaluation_content_fingerprint,
            reconstruida.evaluation_fingerprint,
        ),
    ):
        if gravada is None:
            problemas.append(f"a versão não gravou a impressão {rotulo}")
        elif gravada.value != refeita:
            problemas.append(
                f"a impressão {rotulo} reconstruída ({refeita[:16]}) não é a gravada "
                f"({gravada.value[:16]}): o que foi escrito não é o que foi calculado"
            )
    return problemas


def _manifesto(
    versao: NormalizedHistoricalFeatureDatasetVersion,
    *,
    origem: HistoricalFeatureDatasetVersion,
    plano: NormalizationPlan,
    conjunto: NormalizerArtifactSet,
    dataset_name: str,
    resultado: NormalizedBuildOutput,
    at: Instant,
) -> NormalizedFeatureDatasetManifest:
    import uuid

    return NormalizedFeatureDatasetManifest(
        id=str(uuid.uuid4()),
        schema_version=NORMALIZED_MANIFEST_SCHEMA_VERSION,
        dataset_id=versao.dataset_id,
        dataset_name=dataset_name,
        dataset_version=versao.version,
        dataset_version_id=versao.id,
        source_dataset_version_id=origem.id,
        source_version=origem.version,
        source_raw_content_fingerprint=_impressao_crua(origem),
        source_row_count=origem.row_count,
        representation=versao.representation,
        plan=plano,
        counts=resultado.counts,
        match_count=resultado.matches,
        row_count=resultado.rows_written,
        availability=resultado.availability,
        normalized_content_fingerprint=ContentHash(resultado.fingerprint),
        normalized_reference_content_fingerprint=ContentHash(resultado.reference_fingerprint),
        normalized_evaluation_content_fingerprint=ContentHash(resultado.evaluation_fingerprint),
        reference_end_exclusive=conjunto.reference_end_exclusive,
        created_at=at,
        objects=resultado.objects,
        artifact_map=artifact_map_of(conjunto.bundles, plano),
        rows_by_partition=dict(resultado.rows_by_partition),
    )


def _com_versao(
    resultado: NormalizedBuildOutput,
    versao: NormalizedHistoricalFeatureDatasetVersion,
) -> NormalizedBuildOutput:
    from dataclasses import replace

    return replace(resultado, version=versao)


def _saida(conjunto: NormalizerArtifactSet, referencia_rows: int) -> NormalizerFitOutput:
    contagens = conjunto.counts()
    return NormalizerFitOutput(
        artifact_set=conjunto,
        reference_rows=referencia_rows,
        competitions=len(conjunto.bundles),
        artifacts=conjunto.artifact_count,
        fitted=contagens[FitStatus.FITTED.value],
        insufficient=contagens[FitStatus.INSUFFICIENT_SAMPLE.value],
        degenerate=contagens[FitStatus.DEGENERATE_SCALE.value],
    )


async def _versao_crua_legivel(
    repositorio: HistoricalFeatureDatasetRepositoryPort, version_id: str
) -> HistoricalFeatureDatasetVersion:
    versao = await repositorio.version_by_id(version_id)
    if versao is None:
        raise NotFoundError(
            f"a versão de features {version_id} não existe",
            context={"version_id": version_id},
        )
    if not versao.is_readable:
        raise ValidationError(
            f"a versão crua {versao.version} está em {versao.status}: ajustar ou "
            "normalizar sobre um dataset não publicado produziria uma escala sobre "
            "linhas que ainda podem mudar",
            context={"status": versao.status.value},
        )
    return versao


def _impressao_crua(versao: HistoricalFeatureDatasetVersion) -> ContentHash:
    if versao.raw_content_fingerprint is None:
        raise ValidationError(
            f"a versão crua {versao.version} não tem impressão de conteúdo: sem ela "
            "«normalizado a partir da 1.0» não é verificável"
        )
    return versao.raw_content_fingerprint


def _conferir_espaco(plano: NormalizationPlan, origem: HistoricalFeatureDatasetVersion) -> None:
    """O plano e o dataset cru falam do MESMO espaço de features.

    SEM ISSO, UM EIXO NOVO NO CATÁLOGO passaria despercebido: o plano teria
    cento e seis decisões, o Parquet teria cento e cinco colunas, e a
    normalização produziria uma coluna inteira sem valor nenhum — com o motivo
    dizendo «a origem não tinha valor», que é verdade e não é a causa.
    """
    if plano.space_fingerprint != origem.spec.space_fingerprint:
        raise ValidationError(
            f"o plano descreve o espaço {plano.space_fingerprint[:12]} e o dataset "
            f"cru foi construído sob {origem.spec.space_fingerprint[:12]}: são "
            "conjuntos de eixos diferentes, e normalizar assim produziria colunas "
            "inteiras vazias com o motivo errado",
            context={
                "plan_space": plano.space_fingerprint,
                "raw_space": origem.spec.space_fingerprint,
            },
        )


async def _auditar(
    audit: AuditPort,
    clock: ClockPort,
    action: AuditAction,
    *,
    actor: Actor,
    correlation_id: str | None,
    reason: str | None = None,
    **detalhe: Any,
) -> None:
    await audit.record(
        AuditEntry.of(
            action,
            actor=actor,
            at=clock.now(),
            correlation_id=correlation_id,
            reason=reason,
            **detalhe,
        )
    )
