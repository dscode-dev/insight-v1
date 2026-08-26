"""Os casos de uso do dataset histórico de features — criar, construir, conferir, publicar.

    corpus publicado (imutável, impresso)
        ↓  grade e divisão                       decisões declaradas, impressas
    n partidas em 91 cortes
        ↓  MATCH_STATE_RAW_V2                    PR-05.4, sem mudança nenhuma
    FeatureSnapshot por corte
        ↓  MaterializedFeatureRow                coordenadas + digesto
    Parquet particionado + manifesto
        ↓  validação                             releitura, reconciliação, rebuild
    READY

QUATRO PASSOS E NÃO UM, e a separação é a decisão. «Construir e publicar» num
método só faria a publicação acontecer sempre que a construção terminasse — e
publicar é decidir que ESTA população passa a ser a base de comparação, que é
julgamento e não consequência mecânica de um `for` ter acabado.

A VALIDAÇÃO É UMA FASE COM VEREDITO, e pode reprovar uma versão já construída.
Ela relê o que foi escrito e reconfere tudo contra o que se pretendia escrever;
sem ela, `READY` significaria «o processo não levantou exceção», que é uma
afirmação sobre o código e não sobre o dado.

A ORDEM DA VARREDURA É A DA CHAVE DA PARTIDA, e isso não é conveniência. A
impressão de conteúdo encadeia os digestos EM ORDEM, e a ordem tem de ser
reproduzível por quem só tem os arquivos. `ORDER BY match_id` no PostgreSQL
ordena os dezesseis bytes do UUID; o `str()` dele é o mesmo hexadecimal com
hífens em posições fixas — as duas ordens coincidem, e é por isso que a
validação consegue reconstruir a cadeia sem consultar o banco.

ESTE MÓDULO NÃO NORMALIZA NADA, e a ausência é a fronteira do PR: não há
`fitter`, não há artefato de escala, e nenhuma coluna normalizada. Ajustar
escala exige uma população — e a população é justamente o que aqui se produz.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final, final

from sports_intelligence.application.use_cases.feature_state import (
    DEFAULT_STATE_BATCH,
)
from sports_intelligence.domain.corpus.versions import DatasetVersionStatus
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.features.availability import TemporalAvailabilityPolicy
from sports_intelligence.domain.features.context import CorpusSource
from sports_intelligence.domain.features.dataset.grid import (
    DEFAULT_SNAPSHOT_GRID,
    SnapshotGridPolicy,
    canonical_kickoff,
    extra_time_evidence,
)
from sports_intelligence.domain.features.dataset.manifest import (
    FEATURE_MANIFEST_SCHEMA_VERSION,
    AvailabilitySummary,
    FeatureObjectRef,
    HistoricalFeatureDatasetManifest,
)
from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
    MaterializedFeatureRow,
    OrderedRowFingerprint,
    rebuild_content_fingerprint,
)
from sports_intelligence.domain.features.dataset.split import (
    DatasetSplit,
    FeatureDatasetSplitPolicy,
    SplitCounts,
)
from sports_intelligence.domain.features.dataset.versions import (
    FeatureDatasetSpec,
    HistoricalFeatureDataset,
    HistoricalFeatureDatasetVersion,
)
from sports_intelligence.domain.features.extraction.catalog import (
    match_state_raw_space_v1,
)
from sports_intelligence.domain.features.extraction.catalog_v2 import (
    ExtendedFeatureCatalog,
    extended_feature_catalog,
    match_state_raw_space_v2,
)
from sports_intelligence.domain.features.extraction.extractor_v2 import (
    ExtendedFeatureExtractionContext,
    ExtendedMatchStateFeatureExtractor,
)
from sports_intelligence.domain.features.market.consensus import MarketConsensusPolicy
from sports_intelligence.domain.features.prematch.policy import (
    DEFAULT_CONTEXT_POLICY,
    HistoricalContextPolicy,
)
from sports_intelligence.domain.features.snapshot import FeatureSnapshot
from sports_intelligence.domain.features.space import FeatureSpaceDefinition
from sports_intelligence.domain.features.state.builder import (
    HistoricalMatchStateBuilder,
)
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.audit import AuditAction, AuditEntry
from sports_intelligence.domain.shared.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.ports.audit import AuditPort
from sports_intelligence.ports.clock import ClockPort
from sports_intelligence.ports.object_store.feature_dataset import (
    FeatureDatasetMaterializerPort,
)
from sports_intelligence.ports.repositories.corpus import (
    HistoricalCanonicalDatasetRepositoryPort,
)
from sports_intelligence.ports.repositories.feature_context import (
    HistoricalContextSourcePort,
)
from sports_intelligence.ports.repositories.feature_dataset import (
    FeatureDatasetBuildRepositoryPort,
    FeatureDatasetManifestRepositoryPort,
    HistoricalFeatureDatasetRepositoryPort,
)
from sports_intelligence.ports.repositories.feature_state import (
    HistoricalMatchStateSourcePort,
)

#: Quantas linhas cabem num `part-*.parquet`.
#:
#: O NÚMERO É UM TETO DE MEMÓRIA, e não uma preferência de arrumação. Cada
#: linha em espera carrega o `FeatureSnapshot` inteiro — cento e cinco
#: `ComputedFeature` —, então um buffer de cinquenta mil linhas seriam cinco
#: milhões de objetos vivos. Cinco mil linhas são cerca de cinquenta e cinco
#: partidas, e produzem arquivos de algumas centenas de kilobytes comprimidos:
#: grandes o bastante para não afogar o leitor em arquivinhos, pequenos o
#: bastante para o pico não depender do tamanho da maior temporada.
DEFAULT_PART_ROWS: Final[int] = 5_000

#: O TETO GLOBAL de linhas em espera, somando TODAS as partições abertas.
#:
#: O TETO POR PARTIÇÃO NÃO BASTA, e a diferença custou uma medição para
#: aparecer. O escritor mantém um buffer por `(metade, competição, temporada)`,
#: e uma varredura que atravessa vinte partições mantém vinte buffers vivos: com
#: cinco mil linhas em cada, o pico deixa de ser 130 MB e vira 2,6 GB.
#:
#:     medido: ~27 KB retidos por linha em espera — o `FeatureSnapshot` com
#:             cento e cinco `ComputedFeature`
#:     10.000 linhas ≈ 270 MB, INDEPENDENTE de quantas partições estejam abertas
#:
#: QUANDO O TETO SERIA ULTRAPASSADO, a MAIOR partição é descarregada ANTES de
#: as linhas novas entrarem — e é essa ordem que torna o limite EXATO em vez de
#: aproximado. A maior é a escolhida porque libera mais memória por arquivo
#: escrito; a menor aliviaria o mesmo pico produzindo arquivos miúdos.
#:
#: O PISO DO ORÇAMENTO É UMA GRADE INTEIRA. Uma partida entra ATÔMICA — os
#: noventa e um cortes dela vão ao mesmo arquivo —, então um teto menor que 91
#: é respeitado «até onde dá»: o escritor esvazia tudo e mesmo assim admite a
#: partida. É o único transbordo possível, e ele é do tamanho de uma partida.
DEFAULT_MAX_PENDING_ROWS: Final[int] = 10_000

#: Quantas partidas a validação semântica reconstrói por padrão. Reconstruir
#: TODAS é o certo num E2E pequeno e é o build inteiro de novo num dataset
#: grande — e uma validação que custa o dobro da construção não é executada.
DEFAULT_REBUILD_SAMPLE: Final[int] = 5

#: Teto de EXEMPLOS nomeados num relatório — da construção e da validação.
#:
#: O QUE ELE LIMITA É A LISTA, E NUNCA A CONTAGEM. As contagens são exatas; o
#: que se corta é quantos identificadores acompanham. Despejar um milhão de
#: chaves divergentes transformaria o relatório no dataset, e truncar a
#: contagem junto esconderia o tamanho do problema atrás de vinte nomes.
MAX_VALIDATION_EXAMPLES: Final[int] = 20


# ============================================================== criação ==


@final
@dataclass(frozen=True, slots=True)
class CreateHistoricalFeatureDatasetVersion:
    """Cria a versão em `DRAFT`, com as políticas já congeladas.

    AS POLÍTICAS ENTRAM AQUI, E NÃO NA CONSTRUÇÃO. Uma versão cuja grade fosse
    escolhida na hora de construir teria a identidade decidida depois de o nome
    existir — e duas construções da «1.0» sob grades diferentes seriam as duas
    legítimas.
    """

    datasets: HistoricalFeatureDatasetRepositoryPort
    corpus: HistoricalCanonicalDatasetRepositoryPort
    clock: ClockPort
    audit: AuditPort

    async def execute(
        self,
        *,
        dataset_name: str,
        version: DatasetVersion,
        source_version_id: str,
        split: FeatureDatasetSplitPolicy,
        actor: Actor,
        grid: SnapshotGridPolicy = DEFAULT_SNAPSHOT_GRID,
        space: FeatureSpaceDefinition | None = None,
        published_families: frozenset[Any] | None = None,
        description: str | None = None,
        correlation_id: str | None = None,
    ) -> HistoricalFeatureDatasetVersion:
        espaco = space or match_state_raw_space_v2()
        origem = await self.corpus.version_by_id(source_version_id)
        if origem is None:
            raise NotFoundError(
                f"a versão de corpus {source_version_id} não existe",
                context={"source_version_id": source_version_id},
            )
        if not origem.status.is_readable_corpus:
            raise ValidationError(
                f"a versão de corpus {origem.version} está em {origem.status}: um "
                "dataset de features construído sobre corpus não publicado descreveria "
                "um corpus que nunca existiu (PR-05.1 §2)",
                context={"status": origem.status.value},
            )
        if origem.corpus_fingerprint is None:
            raise ValidationError(
                f"a versão de corpus {origem.version} não tem impressão: sem ela «veio "
                "da 1.0» não é verificável"
            )
        # A EXIGÊNCIA DO ESPAÇO É CONFERIDA ANTES DE CONSTRUIR (§58). Descobrir
        # que o corpus não publica eventos depois de noventa mil snapshots
        # custaria a construção inteira para chegar a uma máscara toda vazia.
        if published_families is not None:
            faltando = espaco.requirement.missing_from(frozenset(published_families))
            if faltando:
                nomes = sorted(f.value for f in faltando)
                raise ValidationError(
                    f"o espaço {espaco.name} exige {nomes} e a versão de corpus "
                    f"{origem.version} não publica: o dataset inteiro sairia com as "
                    "dimensões correspondentes indisponíveis",
                    context={"missing": ",".join(nomes)},
                )

        agora = self.clock.now()
        dataset = await self._dataset(dataset_name, at=agora, actor=actor, description=description)
        existente = await self.datasets.version_of(dataset.id, version)
        if existente is not None:
            raise ConflictError(
                f"a versão {version} do dataset {dataset_name} já existe: «1.0» precisa "
                "significar um conteúdo só, para sempre",
                context={"version_id": existente.id, "status": existente.status.value},
            )

        criada = await self.datasets.create_version(
            dataset_id=dataset.id,
            version=version,
            source_version_id=origem.id,
            source_version=origem.version,
            source_corpus_fingerprint=origem.corpus_fingerprint,
            spec=FeatureDatasetSpec.of(space=espaco, grid=grid, split=split),
            at=agora,
            created_by=actor,
        )
        await _auditar(
            self.audit,
            self.clock,
            AuditAction.FEATURE_DATASET_VERSION_CREATED,
            actor=actor,
            correlation_id=correlation_id,
            dataset_name=dataset_name,
            version=str(version),
            version_id=criada.id,
            source_version=str(origem.version),
            grid=grid.name,
            grid_fingerprint=grid.fingerprint,
            split_fingerprint=split.fingerprint,
        )
        return criada

    async def _dataset(
        self, name: str, *, at: Instant, actor: Actor, description: str | None
    ) -> HistoricalFeatureDataset:
        existente = await self.datasets.dataset_by_name(name)
        if existente is not None:
            return existente
        criado = await self.datasets.create_dataset(
            name=name, at=at, created_by=actor, description=description
        )
        await _auditar(
            self.audit,
            self.clock,
            AuditAction.FEATURE_DATASET_CREATED,
            actor=actor,
            correlation_id=None,
            dataset_name=name,
            # `feature_dataset_id` E NÃO `dataset_id`: aquele nome é um
            # PARÂMETRO de `AuditEntry.of`, tipado como `DatasetId` e gravado
            # numa coluna própria da trilha. Passar o id do dataset de features
            # por ele o faria ser lido como um dataset de INGESTÃO — e a
            # gravação quebra na hora, que é o melhor jeito de descobrir.
            feature_dataset_id=criado.id,
        )
        return criado


# ============================================================ construção ==


@final
@dataclass(frozen=True, slots=True)
class FeatureDatasetBuildOutput:
    """O que a construção produziu — contado, nunca estimado."""

    version: HistoricalFeatureDatasetVersion
    manifest: HistoricalFeatureDatasetManifest
    matches_processed: int
    rows_written: int
    objects_written: int
    bytes_written: int
    counts: SplitCounts
    raw_content_fingerprint: ContentHash
    #: Partidas da versão do corpus que a construção NÃO pôde processar. Elas
    #: são CONTADAS todas e NOMEADAS até um teto — uma construção que as
    #: ignorasse em silêncio produziria um dataset menor sem que ninguém
    #: soubesse por quê, e uma lista truncada sem contagem esconderia o
    #: tamanho do buraco.
    skipped_matches: tuple[str, ...] = ()
    skipped_count: int = 0
    #: O MAIOR número de linhas em espera observado, somando todas as partições
    #: abertas — a prova executável de que a memória segue o orçamento, e não o
    #: tamanho do dataset. E quantas partições estavam abertas no pico: sem ele,
    #: «limitada» poderia significar apenas «o corpus tinha poucas partições».
    peak_pending_rows: int = 0
    peak_open_partitions: int = 0
    #: A MAIOR unidade ATÔMICA admitida — as linhas de UMA partida, que
    #: entram juntas porque os cortes dela precisam ir ao mesmo arquivo.
    #:
    #: ELA É O PISO DO ORÇAMENTO, e é o que torna a cota EXATA em vez de
    #: aproximada:
    #:
    #:     peak_pending_rows <= max(max_pending_rows, largest_atomic_match_rows)
    #:
    #: Se a grade for maior que o teto, o pico é do tamanho da grade — e isso
    #: NÃO é transbordo, é a unidade indivisível. Sem este número, a mesma
    #: observação pareceria o orçamento sendo violado.
    largest_atomic_match_rows: int = 0


@final
@dataclass(frozen=True, slots=True)
class BuildHistoricalFeatureDatasetVersion:
    """Materializa a versão: `DRAFT → BUILDING → VALIDATING`.

    ELA NÃO PUBLICA. Ao fim, a versão está em `VALIDATING` com manifesto salvo
    e impressão calculada — e ninguém pode lê-la ainda, porque nada foi
    conferido.
    """

    datasets: HistoricalFeatureDatasetRepositoryPort
    builds: FeatureDatasetBuildRepositoryPort
    manifests: FeatureDatasetManifestRepositoryPort
    state_source: HistoricalMatchStateSourcePort
    context_source: HistoricalContextSourcePort
    materializer: FeatureDatasetMaterializerPort
    clock: ClockPort
    audit: AuditPort
    policy: TemporalAvailabilityPolicy = field(default_factory=TemporalAvailabilityPolicy.default)
    context_policy: HistoricalContextPolicy = DEFAULT_CONTEXT_POLICY
    market_policy: MarketConsensusPolicy = field(default_factory=MarketConsensusPolicy)
    catalog: ExtendedFeatureCatalog = field(default_factory=extended_feature_catalog)
    space: FeatureSpaceDefinition = field(default_factory=match_state_raw_space_v2)
    v1_space: FeatureSpaceDefinition = field(default_factory=match_state_raw_space_v1)
    batch_size: int = DEFAULT_STATE_BATCH
    part_rows: int = DEFAULT_PART_ROWS
    max_pending_rows: int = DEFAULT_MAX_PENDING_ROWS

    async def execute(
        self,
        *,
        version_id: str,
        source: CorpusSource,
        dataset_name: str,
        actor: Actor,
        correlation_id: str | None = None,
    ) -> FeatureDatasetBuildOutput:
        versao = await self._versao(version_id)
        versao.require_transition(DatasetVersionStatus.BUILDING)
        self._conferir_origem(versao, source)

        agora = self.clock.now()
        execucao = await self.builds.start_run(version_id=version_id, at=agora, started_by=actor)
        await self.datasets.transition(version_id, target=DatasetVersionStatus.BUILDING, at=agora)
        try:
            resultado = await self._materializar(versao, source, dataset_name=dataset_name)
        except Exception as erro:
            fim = self.clock.now()
            await self.builds.finish_run(
                execucao.id,
                status=DatasetVersionStatus.FAILED,
                at=fim,
                failure_reason=str(erro)[:500],
            )
            await self.datasets.transition(
                version_id,
                target=DatasetVersionStatus.FAILED,
                at=fim,
                failure_reason=str(erro)[:500],
            )
            await _auditar(
                self.audit,
                self.clock,
                AuditAction.FEATURE_DATASET_VERSION_FAILED,
                actor=actor,
                correlation_id=correlation_id,
                version_id=version_id,
                phase="BUILD",
                error=str(erro)[:200],
            )
            raise

        # OS OBJETOS SÃO REGISTRADOS ANTES DO MANIFESTO. A validação reconcilia
        # os dois lados, e um manifesto salvo sobre um registro vazio faria a
        # reconciliação acusar tudo como «fora do manifesto» — um alarme sobre
        # a ordem de gravação, e não sobre o dado.
        await self.builds.record_objects(version_id, resultado.objects)

        fim = self.clock.now()
        manifesto = _montar_manifesto(
            versao=versao,
            dataset_name=dataset_name,
            resultado=resultado,
            at=fim,
        )
        salvo = await self.manifests.save(
            manifesto,
            manifest_key=self.materializer.manifest_key(
                dataset_name=dataset_name, version=str(versao.version)
            ),
            manifest_sha256=manifesto.manifest_sha256,
        )
        atualizada = await self.datasets.transition(
            version_id,
            target=DatasetVersionStatus.VALIDATING,
            at=fim,
            raw_content_fingerprint=resultado.fingerprint,
            manifest_id=salvo.id,
            match_count=resultado.matches,
            row_count=resultado.rows,
            counts=resultado.counts,
        )
        await self.builds.finish_run(
            execucao.id,
            status=DatasetVersionStatus.VALIDATING,
            at=fim,
            matches_processed=resultado.matches,
            rows_written=resultado.rows,
            objects_written=len(resultado.objects),
            bytes_written=resultado.bytes,
        )
        await _auditar(
            self.audit,
            self.clock,
            AuditAction.FEATURE_DATASET_VERSION_BUILT,
            actor=actor,
            correlation_id=correlation_id,
            version_id=version_id,
            matches=resultado.matches,
            rows=resultado.rows,
            objects=len(resultado.objects),
            skipped=resultado.skipped_count,
            raw_content_fingerprint=resultado.fingerprint.value,
        )
        return FeatureDatasetBuildOutput(
            version=atualizada,
            manifest=salvo,
            matches_processed=resultado.matches,
            rows_written=resultado.rows,
            objects_written=len(resultado.objects),
            bytes_written=resultado.bytes,
            counts=resultado.counts,
            raw_content_fingerprint=resultado.fingerprint,
            skipped_matches=resultado.skipped,
            skipped_count=resultado.skipped_count,
            peak_pending_rows=resultado.peak_pending_rows,
            peak_open_partitions=resultado.peak_open_partitions,
            largest_atomic_match_rows=resultado.largest_atomic_match_rows,
        )

    # ------------------------------------------------------------ interno --

    async def _versao(self, version_id: str) -> HistoricalFeatureDatasetVersion:
        versao = await self.datasets.version_by_id(version_id)
        if versao is None:
            raise NotFoundError(
                f"a versão de features {version_id} não existe",
                context={"version_id": version_id},
            )
        return versao

    def _conferir_origem(
        self, versao: HistoricalFeatureDatasetVersion, source: CorpusSource
    ) -> None:
        """A origem passada TEM de ser a que a versão declarou.

        SEM ISTO, A VERSÃO SERIA UM RÓTULO. Ela diz «features da 1.0»; se a
        construção pudesse receber a 1.1, o nome deixaria de significar o
        conteúdo — e a impressão do corpus gravada na criação apontaria para
        fatos que não foram usados.
        """
        if source.version_id != versao.source_version_id:
            raise ValidationError(
                f"a versão declara construir sobre {versao.source_version_id} e recebeu "
                f"{source.version_id}: o nome do dataset deixaria de dizer de onde ele "
                "veio",
                context={"declared": versao.source_version_id, "given": source.version_id},
            )
        if source.corpus_fingerprint != versao.source_corpus_fingerprint:
            raise ValidationError(
                "a impressão do corpus mudou entre a criação e a construção: alguém "
                "republicou conteúdo diferente sob o mesmo número, e construir agora "
                "produziria features de fatos que não são os declarados",
                context={
                    "declared": versao.source_corpus_fingerprint.value,
                    "given": source.corpus_fingerprint.value,
                },
            )

    async def _materializar(
        self,
        versao: HistoricalFeatureDatasetVersion,
        source: CorpusSource,
        *,
        dataset_name: str,
    ) -> _ResultadoDaMaterializacao:
        grade = _grade_de(versao)
        divisao = _divisao_de(versao)
        construtor = HistoricalMatchStateBuilder(policy=self.policy)
        extrator = ExtendedMatchStateFeatureExtractor()
        impressao = OrderedRowFingerprint(
            space_name=versao.spec.space_name,
            space_version=versao.spec.space_version,
            grid_fingerprint=versao.spec.grid_fingerprint,
            split_fingerprint=versao.spec.split_fingerprint,
        )
        escritor = _EscritorDeParticoes(
            materializer=self.materializer,
            dataset_name=dataset_name,
            version=str(versao.version),
            part_rows=self.part_rows,
            max_pending_rows=self.max_pending_rows,
        )

        contagens = SplitCounts()
        disponibilidade: dict[str, int] = {}
        partidas = valores = puladas = 0
        ignoradas: list[str] = []
        cursor: str | None = None

        while True:
            ids = await self.state_source.match_ids(
                source.version_id, limit=self.batch_size, after=cursor
            )
            if not ids:
                break
            cursor = str(ids[-1])
            insumos = await self.state_source.load(source.version_id, ids)
            contextos = await self.context_source.load(
                source.version_id, ids, policy=self.context_policy
            )
            for partida in ids:
                entrada = insumos.get(partida)
                if entrada is None:
                    # A PARTIDA ESTÁ NA PERTINÊNCIA E NÃO TEM INSUMO. Ela é
                    # CONTADA sempre e NOMEADA até um teto: um dataset menor sem
                    # explicação é o defeito que ninguém procura porque nada o
                    # denuncia — e uma lista truncada sem a contagem esconderia
                    # cinco mil ausências atrás de vinte nomes.
                    puladas += 1
                    if len(ignoradas) < MAX_VALIDATION_EXAMPLES:
                        ignoradas.append(str(partida))
                    continue
                kickoff = canonical_kickoff(entrada.match)
                metade = divisao.assign(kickoff=kickoff)
                pontos = grade.points_for(
                    partida,
                    kickoff=kickoff,
                    extra_time=extra_time_evidence(
                        events=entrada.candidate_events, result=entrada.result
                    ),
                )
                linhas: list[MaterializedFeatureRow] = []
                contexto = contextos.get(partida)
                for ponto in pontos:
                    build = construtor.build(entrada, as_of=ponto.as_of, source=source)
                    snapshot = extrator.extract(
                        ExtendedFeatureExtractionContext.of(
                            build,
                            space=self.space,
                            catalog=self.catalog,
                            source=source,
                            policy=self.policy,
                            v1_space=self.v1_space,
                            context_policy=self.context_policy,
                            market_policy=self.market_policy,
                            context=contexto,
                        )
                    )
                    linha = MaterializedFeatureRow(
                        key=HistoricalFeatureSnapshotKey.of(partida, grid_index=ponto.index),
                        snapshot=snapshot,
                        split=metade,
                        competition_code=entrada.competition_code,
                        season_label=entrada.season_label,
                        kickoff=kickoff,
                        grid_label=ponto.label,
                        state_issue_count=len(build.issues),
                    )
                    impressao.update(linha.key, linha.digest)
                    _contar(disponibilidade, snapshot)
                    valores += len(snapshot.features)
                    linhas.append(linha)
                partidas += 1
                contagens = contagens.with_match(metade, rows=len(linhas))
                await escritor.acrescentar(
                    metade, entrada.competition_code, entrada.season_label, linhas
                )

        await escritor.finalizar()
        return _ResultadoDaMaterializacao(
            matches=partidas,
            rows=impressao.rows,
            objects=tuple(escritor.objetos),
            bytes=sum(o.size_bytes for o in escritor.objetos),
            counts=contagens,
            fingerprint=ContentHash(impressao.finalize()),
            availability=AvailabilitySummary(
                total_values=valores, by_state=dict(sorted(disponibilidade.items()))
            ),
            rows_by_partition=dict(sorted(escritor.linhas_por_particao.items())),
            skipped=tuple(ignoradas),
            skipped_count=puladas,
            peak_pending_rows=escritor.pico_em_espera,
            peak_open_partitions=escritor.pico_de_particoes,
            largest_atomic_match_rows=escritor.maior_admissao,
        )


@final
@dataclass(frozen=True, slots=True)
class _ResultadoDaMaterializacao:
    matches: int
    rows: int
    objects: tuple[FeatureObjectRef, ...]
    bytes: int
    counts: SplitCounts
    fingerprint: ContentHash
    availability: AvailabilitySummary
    rows_by_partition: dict[str, int]
    skipped: tuple[str, ...] = ()
    skipped_count: int = 0
    peak_pending_rows: int = 0
    peak_open_partitions: int = 0
    largest_atomic_match_rows: int = 0


@final
class _EscritorDeParticoes:
    """Acumula linhas por partição e descarrega quando o pedaço enche.

    A MEMÓRIA É O MOTIVO DE ELE EXISTIR. Uma temporada de liga grande em
    noventa e um cortes é meio milhão de linhas, e cada linha em espera carrega
    cento e cinco `ComputedFeature` — cerca de 27 KB, medidos.

    DOIS TETOS, E O SEGUNDO É O QUE DE FATO LIMITA. O teto por PEDAÇO fecha um
    `part-*.parquet` quando ele enche; o teto GLOBAL existe porque há um buffer
    por partição ABERTA, e uma varredura que atravessa vinte competições mantém
    vinte buffers vivos ao mesmo tempo. Sem o global, o pico deixa de seguir o
    lote e passa a seguir quantas partições o corpus tem.

    ELE NÃO REORDENA NADA. As linhas chegam na ordem da varredura — que é a
    ordem da chave — e saem assim.
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
        "maior_admissao",
        "objetos",
        "pendentes",
        "pico_de_particoes",
        "pico_em_espera",
    )

    def __init__(
        self,
        *,
        materializer: FeatureDatasetMaterializerPort,
        dataset_name: str,
        version: str,
        part_rows: int,
        max_pending_rows: int = DEFAULT_MAX_PENDING_ROWS,
    ) -> None:
        if part_rows < 1:
            raise ValidationError(f"pedaço de {part_rows} linhas: ele nunca fecharia")
        if max_pending_rows < part_rows:
            raise ValidationError(
                f"teto global de {max_pending_rows} linhas menor que o pedaço de "
                f"{part_rows}: o escritor descarregaria antes de um pedaço encher e "
                "produziria um arquivo por partida"
            )
        self._materializer = materializer
        self._dataset_name = dataset_name
        self._version = version
        self._part_rows = part_rows
        self._max_pending_rows = max_pending_rows
        self._em_espera = 0
        self.pendentes: dict[tuple[DatasetSplit, str, str], list[MaterializedFeatureRow]] = {}
        self._pedacos: dict[tuple[DatasetSplit, str, str], int] = {}
        self.objetos: list[FeatureObjectRef] = []
        self.linhas_por_particao: dict[str, int] = {}
        # A INSTRUMENTAÇÃO É PÚBLICA, e não de teste. «A memória é limitada» é
        # uma afirmação sobre execução, e sem estes dois números ela só pode ser
        # conferida por um profiler acoplado — que ninguém acopla em produção.
        self.pico_em_espera = 0
        self.pico_de_particoes = 0
        #: A MAIOR ADMISSÃO ATÔMICA vista — as linhas de UMA partida, que
        #: entram juntas. Ela é o PISO do orçamento: se uma grade inteira for
        #: maior que o teto, o pico será do tamanho da grade, e isso não é
        #: transbordo — é a unidade indivisível.
        self.maior_admissao = 0

    async def acrescentar(
        self,
        split: DatasetSplit,
        competition: str,
        season: str,
        rows: Sequence[MaterializedFeatureRow],
    ) -> None:
        chave = (split, competition, season)
        # O TETO GLOBAL É CONFERIDO ANTES DE ACRESCENTAR, e a ordem é o que
        # torna o limite EXATO. Conferir depois deixaria o pico ser
        # `teto + linhas desta partida` — um transbordo pequeno, real, e que
        # precisaria virar uma nota de tolerância no relatório. Abrir espaço
        # primeiro dispensa a nota.
        #
        # ELE DESCARREGA A MAIOR PARTIÇÃO ABERTA, e não a mais antiga: a maior
        # é a que libera mais memória por arquivo escrito. Descarregar a menor
        # aliviaria o mesmo pico produzindo uma enxurrada de arquivos miúdos.
        while self._em_espera + len(rows) > self._max_pending_rows:
            maior = max(self.pendentes, key=lambda c: len(self.pendentes[c]), default=None)
            if maior is None or not self.pendentes[maior]:
                # NÃO HÁ MAIS O QUE DESCARREGAR, e as linhas desta partida
                # sozinhas já passam do teto. Elas entram assim mesmo: uma
                # partida é ATÔMICA — os noventa e um cortes dela precisam
                # estar juntos para ir ao mesmo arquivo —, e o piso do
                # orçamento é, portanto, uma grade inteira.
                break
            await self._descarregar(maior)

        buffer = self.pendentes.setdefault(chave, [])
        buffer.extend(rows)
        self._em_espera += len(rows)
        self.maior_admissao = max(self.maior_admissao, len(rows))
        self._marcar_pico()
        # A DESCARGA POR PEDAÇO É POR PARTIDA COMPLETA, e não por linha: cortar
        # no meio de uma partida deixaria os noventa e um cortes dela em dois
        # arquivos, e a leitura «esta partida inteira» exigiria os dois.
        if len(buffer) >= self._part_rows:
            await self._descarregar(chave)

    def _marcar_pico(self) -> None:
        self.pico_em_espera = max(self.pico_em_espera, self._em_espera)
        abertas = sum(1 for buffer in self.pendentes.values() if buffer)
        self.pico_de_particoes = max(self.pico_de_particoes, abertas)

    @property
    def em_espera(self) -> int:
        """Quantas linhas estão em buffer AGORA, somando todas as partições."""
        return self._em_espera

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
class _ReconstrucaoSemantica:
    """O que a reconstrução conferiu, e o que ela achou de diferente.

    TRÊS NÚMEROS E NÃO UM BOOLEANO. «Passou» esconde a diferença entre
    reconstruir cinco partidas e reconstruir nenhuma — e as duas produzem zero
    divergência.
    """

    divergences: tuple[str, ...] = ()
    matches: int = 0
    rows: int = 0


@final
@dataclass(frozen=True, slots=True)
class FeatureDatasetValidationReport:
    """O veredito, com os problemas nomeados.

    `passed` É UMA CONJUNÇÃO EXPLÍCITA, e não uma ausência de exceção. Cada
    conferência tem um campo, e o relatório sobrevive à decisão: seis meses
    depois, «a 1.0 passou na validação» tem detalhe.
    """

    version_id: str
    objects_verified: int = 0
    rows_verified: int = 0
    matches_rebuilt: int = 0
    rows_rebuilt: int = 0
    checksum_mismatches: tuple[str, ...] = ()
    missing_objects: tuple[str, ...] = ()
    unexpected_objects: tuple[str, ...] = ()
    row_count_mismatch: str = ""
    duplicate_keys: tuple[str, ...] = ()
    out_of_order_objects: tuple[str, ...] = ()
    fingerprint_mismatch: str = ""
    digest_mismatches: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not (
            self.checksum_mismatches
            or self.missing_objects
            or self.unexpected_objects
            or self.row_count_mismatch
            or self.duplicate_keys
            or self.out_of_order_objects
            or self.fingerprint_mismatch
            or self.digest_mismatches
        )

    def failures(self) -> tuple[str, ...]:
        problemas: list[str] = []
        if self.checksum_mismatches:
            problemas.append(f"hash divergente em {len(self.checksum_mismatches)} objeto(s)")
        if self.missing_objects:
            problemas.append(f"{len(self.missing_objects)} objeto(s) do manifesto ausentes")
        if self.unexpected_objects:
            problemas.append(f"{len(self.unexpected_objects)} objeto(s) fora do manifesto")
        if self.row_count_mismatch:
            problemas.append(self.row_count_mismatch)
        if self.duplicate_keys:
            problemas.append(f"{len(self.duplicate_keys)} chave(s) repetida(s)")
        if self.out_of_order_objects:
            problemas.append(f"{len(self.out_of_order_objects)} objeto(s) fora de ordem")
        if self.fingerprint_mismatch:
            problemas.append(self.fingerprint_mismatch)
        if self.digest_mismatches:
            problemas.append(
                f"{len(self.digest_mismatches)} linha(s) reconstruída(s) com digesto diferente"
            )
        return tuple(problemas)


@final
@dataclass(frozen=True, slots=True)
class ValidateHistoricalFeatureDatasetVersion:
    """Relê o que foi escrito e confere contra o que se pretendia escrever.

    SEIS CONFERÊNCIAS, E CADA UMA PEGA UM DEFEITO DIFERENTE:

        hash dos objetos       o arquivo chegou inteiro ao bucket
        reconciliação          manifesto, registro e bucket falam do mesmo
        contagem de linhas     nada se perdeu no caminho
        chave repetida         nenhuma partida foi materializada duas vezes
        ordem dentro do arquivo  a leitura em fluxo pode confiar na ordem
        impressão reconstruída o conteúdo é o que a construção calculou
        rebuild semântico      o cálculo é reproduzível a partir do corpus

    A ÚLTIMA É A CARA E A MAIS IMPORTANTE. As outras provam que os bytes
    sobreviveram; ela prova que o NÚMERO sai igual de novo — que é a
    propriedade da qual toda a reprodutibilidade depende.
    """

    datasets: HistoricalFeatureDatasetRepositoryPort
    builds: FeatureDatasetBuildRepositoryPort
    manifests: FeatureDatasetManifestRepositoryPort
    materializer: FeatureDatasetMaterializerPort
    state_source: HistoricalMatchStateSourcePort
    context_source: HistoricalContextSourcePort
    clock: ClockPort
    audit: AuditPort
    policy: TemporalAvailabilityPolicy = field(default_factory=TemporalAvailabilityPolicy.default)
    context_policy: HistoricalContextPolicy = DEFAULT_CONTEXT_POLICY
    market_policy: MarketConsensusPolicy = field(default_factory=MarketConsensusPolicy)
    catalog: ExtendedFeatureCatalog = field(default_factory=extended_feature_catalog)
    space: FeatureSpaceDefinition = field(default_factory=match_state_raw_space_v2)
    v1_space: FeatureSpaceDefinition = field(default_factory=match_state_raw_space_v1)
    rebuild_sample: int = DEFAULT_REBUILD_SAMPLE

    async def execute(
        self,
        *,
        version_id: str,
        source: CorpusSource,
        actor: Actor,
        correlation_id: str | None = None,
    ) -> FeatureDatasetValidationReport:
        versao = await self.datasets.version_by_id(version_id)
        if versao is None:
            raise NotFoundError(
                f"a versão de features {version_id} não existe",
                context={"version_id": version_id},
            )
        if versao.status is not DatasetVersionStatus.VALIDATING:
            raise ValidationError(
                f"a versão está em {versao.status} e a validação só corre sobre "
                "VALIDATING: conferir um DRAFT não teria o que ler, e conferir um "
                "READY chegaria depois de a decisão ter sido tomada",
                context={"status": versao.status.value},
            )
        manifesto = await self.manifests.by_version(version_id)
        if manifesto is None:
            raise ValidationError(
                "a versão está em VALIDATING sem manifesto: não há contra o que conferir"
            )

        relatorio = await self._conferir(versao, manifesto, source)
        agora = self.clock.now()
        if not relatorio.passed:
            motivo = "; ".join(relatorio.failures())[:500]
            await self.datasets.transition(
                version_id,
                target=DatasetVersionStatus.FAILED,
                at=agora,
                failure_reason=motivo,
            )
            await _auditar(
                self.audit,
                self.clock,
                AuditAction.FEATURE_DATASET_VERSION_FAILED,
                actor=actor,
                correlation_id=correlation_id,
                version_id=version_id,
                phase="VALIDATION",
                error=motivo[:200],
            )
            return relatorio

        await _auditar(
            self.audit,
            self.clock,
            AuditAction.FEATURE_DATASET_VERSION_VALIDATED,
            actor=actor,
            correlation_id=correlation_id,
            version_id=version_id,
            objects=relatorio.objects_verified,
            rows=relatorio.rows_verified,
            matches_rebuilt=relatorio.matches_rebuilt,
        )
        return relatorio

    async def _conferir(
        self,
        versao: HistoricalFeatureDatasetVersion,
        manifesto: HistoricalFeatureDatasetManifest,
        source: CorpusSource,
    ) -> FeatureDatasetValidationReport:
        registrados = {o.object_key: o for o in await self.builds.objects_of(versao.id)}
        no_manifesto = {
            o.object_key: o for o in manifesto.objects if o.content_type != "application/json"
        }
        faltando = tuple(sorted(set(no_manifesto) - set(registrados))[:MAX_VALIDATION_EXAMPLES])
        sobrando = tuple(sorted(set(registrados) - set(no_manifesto))[:MAX_VALIDATION_EXAMPLES])

        divergentes: list[str] = []
        desordenados: list[str] = []
        pares: list[tuple[HistoricalFeatureSnapshotKey, str]] = []
        lidos = 0
        for chave in sorted(set(no_manifesto) & set(registrados)):
            esperado = no_manifesto[chave]
            conteudo = await self.materializer.verify_object(object_key=chave)
            curto = len(divergentes) < MAX_VALIDATION_EXAMPLES
            if conteudo.sha256 != esperado.sha256.value and curto:
                divergentes.append(chave)
            if conteudo.row_count != esperado.row_count and curto:
                divergentes.append(f"{chave}#linhas")
            if conteudo.out_of_order() and len(desordenados) < MAX_VALIDATION_EXAMPLES:
                desordenados.append(chave)
            pares.extend(conteudo.rows)
            lidos += conteudo.row_count

        contagem = ""
        if lidos != versao.row_count:
            contagem = f"a versão declara {versao.row_count} linhas e os arquivos têm {lidos}"

        # A ORDEM GLOBAL É A DA CHAVE, e a cadeia é reconstruída sobre ela. Os
        # arquivos são por partição e se intercalam por partida; ordenar aqui é
        # o que reproduz a ordem da varredura sem consultar o banco.
        pares.sort(key=lambda par: par[0])
        repetidas: list[str] = []
        anterior: HistoricalFeatureSnapshotKey | None = None
        for chave_linha, _ in pares:
            if (
                anterior is not None
                and chave_linha == anterior
                and len(repetidas) < MAX_VALIDATION_EXAMPLES
            ):
                repetidas.append(chave_linha.text)
            anterior = chave_linha

        impressao = ""
        if not repetidas:
            recalculada = rebuild_content_fingerprint(
                pares,
                space_name=versao.spec.space_name,
                space_version=versao.spec.space_version,
                grid_fingerprint=versao.spec.grid_fingerprint,
                split_fingerprint=versao.spec.split_fingerprint,
            )
            declarada = (
                ""
                if versao.raw_content_fingerprint is None
                else versao.raw_content_fingerprint.value
            )
            if recalculada != declarada:
                impressao = (
                    f"a impressão reconstruída ({recalculada[:16]}…) não é a declarada "
                    f"({declarada[:16]}…)"
                )

        gravados = dict(pares)
        refeito = await self._reconstruir(versao, source, gravados)

        return FeatureDatasetValidationReport(
            version_id=versao.id,
            objects_verified=len(set(no_manifesto) & set(registrados)),
            rows_verified=lidos,
            matches_rebuilt=refeito.matches,
            rows_rebuilt=refeito.rows,
            checksum_mismatches=tuple(divergentes),
            missing_objects=faltando,
            unexpected_objects=sobrando,
            row_count_mismatch=contagem,
            duplicate_keys=tuple(repetidas),
            out_of_order_objects=tuple(desordenados),
            fingerprint_mismatch=impressao,
            digest_mismatches=refeito.divergences,
        )

    async def _reconstruir(
        self,
        versao: HistoricalFeatureDatasetVersion,
        source: CorpusSource,
        gravados: dict[HistoricalFeatureSnapshotKey, str],
    ) -> _ReconstrucaoSemantica:
        """Recalcula uma AMOSTRA de partidas e compara os digestos.

        A AMOSTRA É AS PRIMEIRAS N NA ORDEM DA CHAVE, e não sorteada: uma
        validação que sorteasse produziria vereditos diferentes sobre o mesmo
        dataset, e «a 1.0 passou» deixaria de ser uma afirmação reproduzível.
        """
        if self.rebuild_sample < 1 or not gravados:
            return _ReconstrucaoSemantica()
        alvos = _primeiras_partidas(gravados, self.rebuild_sample)
        if not alvos:
            return _ReconstrucaoSemantica()

        grade = _grade_de(versao)
        divisao = _divisao_de(versao)
        construtor = HistoricalMatchStateBuilder(policy=self.policy)
        extrator = ExtendedMatchStateFeatureExtractor()
        ids = [MatchId.parse(alvo) for alvo in alvos]
        insumos = await self.state_source.load(source.version_id, ids)
        contextos = await self.context_source.load(
            source.version_id, ids, policy=self.context_policy
        )
        divergencias: list[str] = []
        conferidas = 0
        refeitas = 0
        for partida in ids:
            entrada = insumos.get(partida)
            if entrada is None:
                continue
            refeitas += 1
            kickoff = canonical_kickoff(entrada.match)
            metade = divisao.assign(kickoff=kickoff)
            contexto = contextos.get(partida)
            for ponto in grade.points_for(
                partida,
                kickoff=kickoff,
                extra_time=extra_time_evidence(
                    events=entrada.candidate_events, result=entrada.result
                ),
            ):
                build = construtor.build(entrada, as_of=ponto.as_of, source=source)
                snapshot = extrator.extract(
                    ExtendedFeatureExtractionContext.of(
                        build,
                        space=self.space,
                        catalog=self.catalog,
                        source=source,
                        policy=self.policy,
                        v1_space=self.v1_space,
                        context_policy=self.context_policy,
                        market_policy=self.market_policy,
                        context=contexto,
                    )
                )
                linha = MaterializedFeatureRow(
                    key=HistoricalFeatureSnapshotKey.of(partida, grid_index=ponto.index),
                    snapshot=snapshot,
                    split=metade,
                    competition_code=entrada.competition_code,
                    season_label=entrada.season_label,
                    kickoff=kickoff,
                    grid_label=ponto.label,
                    state_issue_count=len(build.issues),
                )
                gravado = gravados.get(linha.key)
                conferidas += 1
                curto = len(divergencias) < MAX_VALIDATION_EXAMPLES
                if gravado is None and curto:
                    divergencias.append(f"{linha.key.text}#ausente")
                elif gravado is not None and gravado != linha.digest and curto:
                    divergencias.append(linha.key.text)
        return _ReconstrucaoSemantica(
            divergences=tuple(divergencias), matches=refeitas, rows=conferidas
        )


# ============================================================= publicação ==


@final
@dataclass(frozen=True, slots=True)
class PublishHistoricalFeatureDatasetVersion:
    """`VALIDATING → READY`, com o manifesto gravado ao lado dos dados.

    PUBLICAR É UMA DECISÃO, e a trilha exige motivo: a partir daqui esta
    população é a base de comparação, e «por que esta e não a anterior» tem de
    ter resposta depois.
    """

    datasets: HistoricalFeatureDatasetRepositoryPort
    manifests: FeatureDatasetManifestRepositoryPort
    materializer: FeatureDatasetMaterializerPort
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
    ) -> HistoricalFeatureDatasetVersion:
        versao = await self.datasets.version_by_id(version_id)
        if versao is None:
            raise NotFoundError(
                f"a versão de features {version_id} não existe",
                context={"version_id": version_id},
            )
        versao.require_transition(DatasetVersionStatus.READY)
        manifesto = await self.manifests.by_version(version_id)
        if manifesto is None:
            raise ValidationError(
                "publicar uma versão sem manifesto: o dataset chegaria ao consumidor "
                "sem políticas, sem contagem e sem impressão"
            )
        if versao.row_count <= 0:
            raise ValidationError(
                "publicar uma versão com zero linhas: quem a consultasse receberia "
                "«sem vizinhos» em vez de um erro"
            )

        # O MANIFESTO VAI PARA O BUCKET AGORA, e não na construção: um
        # `manifest.json` ao lado de dados ainda não conferidos afirmaria que
        # eles estão publicados.
        await self.materializer.write_manifest(
            dataset_name=dataset_name,
            version=str(versao.version),
            document=manifesto.to_json(),
        )

        anterior = await self.datasets.latest_ready(versao.dataset_id)
        agora = self.clock.now()
        publicada = await self.datasets.transition(
            version_id, target=DatasetVersionStatus.READY, at=agora
        )
        await _auditar(
            self.audit,
            self.clock,
            AuditAction.FEATURE_DATASET_VERSION_PUBLISHED,
            actor=actor,
            correlation_id=correlation_id,
            reason=reason,
            version_id=version_id,
            version=str(versao.version),
            rows=versao.row_count,
            matches=versao.match_count,
            raw_content_fingerprint=manifesto.raw_content_fingerprint.value,
        )

        if supersede_previous and anterior is not None and anterior.id != version_id:
            await self.datasets.transition(
                anterior.id,
                target=DatasetVersionStatus.SUPERSEDED,
                at=agora,
                superseded_by=version_id,
            )
            await _auditar(
                self.audit,
                self.clock,
                AuditAction.FEATURE_DATASET_VERSION_SUPERSEDED,
                actor=actor,
                correlation_id=correlation_id,
                reason=reason,
                version_id=anterior.id,
                superseded_by=version_id,
            )
        return publicada


# ================================================================ apoio ==


def _grade_de(versao: HistoricalFeatureDatasetVersion) -> SnapshotGridPolicy:
    """A grade que a versão declarou, com os parâmetros dela.

    ELA VEM DA ESPECIFICAÇÃO, e não é reconstruída por nome: a `spec` carrega a
    política INTEIRA justamente porque nome e versão não bastam — uma grade de
    cinco cortes reconstruída deles voltaria com noventa e um.

    A CONFERÊNCIA DE IMPRESSÃO CONTINUA AQUI, e é defesa em profundidade: o
    adaptador já a fez ao ler do banco, e refazê-la custa um hash e cobre o
    caminho em que a versão veio de outro lugar — um duplo, um teste, um
    processo que a montou à mão.
    """
    grade = versao.spec.grid
    if grade.fingerprint != versao.spec.grid_fingerprint:
        raise ValidationError(
            "a grade da especificação não bate com a impressão declarada: construir "
            "sob ela mudaria o conteúdo de uma versão sem mudar o nome dela",
            context={
                "declared": versao.spec.grid_fingerprint,
                "current": grade.fingerprint,
            },
        )
    return grade


def _divisao_de(versao: HistoricalFeatureDatasetVersion) -> FeatureDatasetSplitPolicy:
    """A divisão declarada, conferida pela impressão — mesma razão da grade."""
    divisao = versao.spec.split
    if divisao.fingerprint != versao.spec.split_fingerprint:
        raise ValidationError(
            "a divisão da especificação não bate com a impressão declarada",
            context={
                "declared": versao.spec.split_fingerprint,
                "current": divisao.fingerprint,
            },
        )
    return divisao


def _contar(acumulador: dict[str, int], snapshot: FeatureSnapshot) -> None:
    for computada in snapshot.features:
        estado = computada.availability.value
        acumulador[estado] = acumulador.get(estado, 0) + 1


def _primeiras_partidas(
    gravados: dict[HistoricalFeatureSnapshotKey, str], quantas: int
) -> tuple[str, ...]:
    vistas: list[str] = []
    for chave in sorted(gravados):
        if chave.match_key not in vistas:
            vistas.append(chave.match_key)
            if len(vistas) >= quantas:
                break
    return tuple(vistas)


def _montar_manifesto(
    *,
    versao: HistoricalFeatureDatasetVersion,
    dataset_name: str,
    resultado: _ResultadoDaMaterializacao,
    at: Instant,
) -> HistoricalFeatureDatasetManifest:
    import uuid

    return HistoricalFeatureDatasetManifest(
        id=str(uuid.uuid4()),
        schema_version=FEATURE_MANIFEST_SCHEMA_VERSION,
        dataset_id=versao.dataset_id,
        dataset_name=dataset_name,
        dataset_version=versao.version,
        dataset_version_id=versao.id,
        source_version_id=versao.source_version_id,
        source_version=versao.source_version,
        source_corpus_fingerprint=versao.source_corpus_fingerprint,
        spec=versao.spec,
        counts=resultado.counts,
        match_count=resultado.matches,
        row_count=resultado.rows,
        availability=resultado.availability,
        raw_content_fingerprint=resultado.fingerprint,
        created_at=at,
        objects=resultado.objects,
        rows_by_partition=resultado.rows_by_partition,
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
