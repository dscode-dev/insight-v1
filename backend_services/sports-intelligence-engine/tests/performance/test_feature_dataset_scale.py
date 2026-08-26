"""OS BENCHMARKS DO PR-05.5.1: materializar o dataset histórico em volume.

DOIS CENÁRIOS, E ELES MEDEM COISAS DIFERENTES (§137 ao §145):

    A GRADE INTEIRA      1.000 partidas em 91 cortes ≈ 91.000 linhas. Mede o
                         custo REAL de produção: 9,5 milhões de valores de
                         feature escritos em Parquet, com build, validação e
                         publicação cronometrados SEPARADAMENTE.

    O VOLUME DE PARTIDAS 10.000 partidas em 5 cortes. Mede a curva do número de
                         PARTIDAS com a grade reduzida — se o custo por partida
                         é constante, os dois números conversam.

POR QUE DOIS E NÃO UM. Dez mil partidas na grade inteira são 910 mil linhas e
95 milhões de valores; é o dataset de produção, e ele não cabe numa suíte.

POR QUE CADA CENÁRIO É UM TESTE SÓ, E LONGO. A fixture que constrói o corpus de
dez mil partidas custa minutos, e ela é por FUNÇÃO: quebrar cada medição num
teste próprio pagaria o pipeline inteiro de novo a cada uma. As medições que
compartilham cenário moram juntas, e cada bloco diz o que mede.

O NÚMERO QUE MAIS IMPORTA É O DE CONSULTAS DE FATO. Noventa e um cortes por
partida NÃO podem virar noventa e uma leituras: o estado e o contexto são
carregados uma vez por lote e reusados em todos os cortes. As consultas de
METADADO — ciclo de vida, objetos, manifesto, trilha — são contadas à parte e
não estão sob essa regra: elas seguem a EXECUÇÃO, e não o conteúdo.

O SEGUNDO NÚMERO É O PICO DE MEMÓRIA. Cada linha em espera carrega o
`FeatureSnapshot` inteiro — cerca de 27 KB medidos. O escritor tem dois tetos, e
o que de fato limita é o GLOBAL: sem ele, o pico seguiria quantas partições o
corpus tem em vez do lote.

O CRITÉRIO É A FORMA DA CURVA, e nunca o segundo absoluto.
"""

from __future__ import annotations

import uuid as _uuid
from collections.abc import Mapping, Sequence
from typing import Any, Final, final

import pytest

from apps.corpus_composition import build_corpus_container
from sports_intelligence.adapters.postgres.audit import PostgresAuditLog
from sports_intelligence.adapters.postgres.corpus import (
    PostgresHistoricalCorpusRepository,
)
from sports_intelligence.adapters.postgres.feature_context import (
    PostgresHistoricalContextSource,
)
from sports_intelligence.adapters.postgres.feature_dataset import (
    PostgresFeatureDatasetBuildRepository,
    PostgresFeatureDatasetManifestRepository,
    PostgresHistoricalFeatureDatasetRepository,
)
from sports_intelligence.adapters.postgres.feature_state import (
    PostgresHistoricalMatchStateSource,
)
from sports_intelligence.application.use_cases.feature_dataset import (
    DEFAULT_MAX_PENDING_ROWS,
    DEFAULT_PART_ROWS,
    BuildHistoricalFeatureDatasetVersion,
    CreateHistoricalFeatureDatasetVersion,
    PublishHistoricalFeatureDatasetVersion,
    ValidateHistoricalFeatureDatasetVersion,
)
from sports_intelligence.domain.corpus.versions import (
    CORPUS_PUBLISHER,
    DatasetVersionStatus,
)
from sports_intelligence.domain.features.context import CorpusSource
from sports_intelligence.domain.features.dataset.grid import (
    DEFAULT_SNAPSHOT_GRID,
    REGULATION_GRID_SIZE,
    SnapshotGridPolicy,
)
from sports_intelligence.domain.features.dataset.split import FeatureDatasetSplitPolicy
from sports_intelligence.domain.features.extraction.catalog_v2 import (
    extended_feature_catalog,
)
from sports_intelligence.domain.quality.coverage import CoverageFamily, CoverageState
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.temporal import instant
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.historical.features.materializer import (
    ParquetFeatureDatasetMaterializer,
)
from sports_intelligence.ports.clock import SystemClock
from tests.performance.test_event_corpus_scale import (  # noqa: F401 — fixture
    _compor,
    cenario,
)
from tests.performance.test_resolution_100k import _relatar
from tests.support.instrumentation import (
    ContagemDeConsultas,
    contando_consultas,
    medindo,
)

pytestmark = pytest.mark.performance

PUBLICADOR = Actor.service(CORPUS_PUBLISHER)
CONSTRUTOR = Actor.service("feature-dataset-builder")

LOTE: Final[int] = 500
FEATURES: Final[int] = 105

#: A conta de consultas de FATO, aberta em parcelas nomeadas.
#:
#:     estado      5 por lote   (partida, escalação, evento, odds, resultado)
#:     contexto    2 por lote   (a janela e a última anterior)
#:     varredura   1 por PÁGINA de `match_ids`
#:     cobertura   1 por EXECUÇÃO, memoizada por versão
#:
#: NENHUMA DELAS DEPENDE DO NÚMERO DE CORTES, e é isso que os dois cenários
#: existem para provar: noventa e um cortes e cinco cortes custam a MESMA
#: leitura.
CONSULTAS_DE_ESTADO: Final[int] = 5
CONSULTAS_DE_CONTEXTO: Final[int] = 2
CONSULTAS_POR_LOTE: Final[int] = CONSULTAS_DE_ESTADO + CONSULTAS_DE_CONTEXTO
CONSULTA_DE_VARREDURA: Final[int] = 1
CONSULTAS_DE_COBERTURA: Final[int] = 1

#: As tabelas de FATO — o que a regra `O(lotes)` governa.
ALVOS_DE_FATO: Final[frozenset[str]] = frozenset(
    {
        "historical_canonical_members",
        "historical_canonical_event_members",
        "lineups",
        "canonical_odds_observations",
        "match_results",
    }
)

#: As tabelas de METADADO e CICLO DE VIDA. Elas seguem a EXECUÇÃO — quantas
#: transições, quantos objetos, quantas linhas de trilha — e NÃO o conteúdo.
#: Contá-las junto com as de fato esconderia a única regra que importa.
ALVOS_DE_METADADO: Final[frozenset[str]] = frozenset(
    {
        "historical_feature_datasets",
        "historical_feature_dataset_versions",
        "historical_feature_dataset_build_runs",
        "historical_feature_dataset_manifests",
        "historical_feature_objects",
        "dataset_audit_log",
    }
)

#: Quantas partidas cada medição da grade inteira materializa.
PARTIDAS_DA_GRADE: Final[int] = 1_000
PARTIDAS_DA_ESCALA_MENOR: Final[int] = 100

#: A grade REDUZIDA: pré-jogo + 2 do primeiro tempo + 2 do segundo = 5 cortes.
#: Ela é uma política legítima e impressa — e não um atalho no código: reduzir a
#: grade por parâmetro em vez de por `if` de benchmark é o que garante que o
#: caminho medido é o caminho de produção.
GRADE_REDUZIDA: Final[SnapshotGridPolicy] = SnapshotGridPolicy(
    name="BENCHMARK_FIVE_CUT_GRID_V1",
    first_half_last_minute=2,
    second_half_last_minute=4,
)
CORTES_REDUZIDOS: Final[int] = 5


def _fatos(contagem: ContagemDeConsultas) -> int:
    return sum(v for k, v in contagem.por_alvo.items() if k in ALVOS_DE_FATO)


def _metadados(contagem: ContagemDeConsultas) -> int:
    return sum(v for k, v in contagem.por_alvo.items() if k in ALVOS_DE_METADADO)


def _fora_da_conta(contagem: ContagemDeConsultas) -> dict[str, int]:
    """As consultas que não caíram em nenhum dos dois grupos.

    ELAS SÃO REPORTADAS, e não ignoradas: um alvo novo que aparecesse sem
    classificação sairia da regra sem que ninguém notasse.
    """
    conhecidos = ALVOS_DE_FATO | ALVOS_DE_METADADO
    return {k: v for k, v in contagem.por_alvo.items() if k not in conhecidos}


async def _publicar(cenario: dict[str, Any]) -> tuple[Any, Any]:  # noqa: F811
    saida, _medida, _consultas = await _compor(
        cenario,
        nome=f"perf-ds-{_uuid.uuid4().hex[:6]}",
        event_runs=(cenario["eventos_grandes"].id,),
    )
    pipeline = cenario["anterior"]["pipeline"]
    contêiner = build_corpus_container(
        database=cenario["banco"],
        clock=pipeline.clock,
        audit=pipeline.audit,
        store=cenario["store"],
    )
    versao = await contêiner.publish_version.execute(actor=PUBLICADOR, version_id=saida.version.id)
    assert versao.status is DatasetVersionStatus.READY
    return versao, saida.manifest


def _origem(versao: Any, manifesto: Any) -> CorpusSource:
    return CorpusSource.of(
        versao,
        published_families=frozenset(
            CoverageFamily(f.family)
            for f in manifesto.coverage
            if f.state != CoverageState.NOT_DECLARED.value
        ),
    )


async def _divisao(banco: Any, version_id: str) -> FeatureDatasetSplitPolicy:
    """A fronteira na MEDIANA dos apitos: metade em cada lado.

    ELA VEM DO BANCO. Uma data escrita à mão passaria a estar fora do intervalo
    no dia em que o gerador do cenário mudasse de ano, e o benchmark mediria um
    dataset de uma metade só sem que ninguém notasse.
    """
    async with banco.acquire() as conexao:
        mediana = await conexao.fetchval(
            """
            SELECT percentile_disc(0.5) WITHIN GROUP (ORDER BY m.scheduled_kickoff)
            FROM historical_canonical_members hcm
            JOIN matches m ON m.id = hcm.match_id
            WHERE hcm.version_id = $1
            """,
            _uuid.UUID(version_id),
        )
    assert mediana is not None
    return FeatureDatasetSplitPolicy(reference_end_exclusive=instant(mediana))


async def _contar_membros(banco: Any, version_id: str) -> int:
    async with banco.acquire() as conexao:
        return int(
            await conexao.fetchval(
                "SELECT count(*) FROM historical_canonical_members WHERE version_id = $1",
                _uuid.UUID(version_id),
            )
        )


@final
class _PrimeirasPartidas:
    """A fonte de estado REAL, com a varredura recortada nas primeiras `n`.

    POR QUE UM ENVOLTÓRIO E NÃO UM PARÂMETRO NO CASO DE USO. «Construir o
    dataset sobre um pedaço do corpus» não é uma operação que a produção deva
    ter: uma versão que contivesse metade das partidas da versão de corpus
    mentiria sobre a própria origem. O recorte é do BENCHMARK, e por isso mora
    aqui — visível, nomeado, e sem existir no caminho de produção.

    ELE RECORTA A VARREDURA, e não a leitura: `load` continua sendo o adaptador
    de verdade, então o custo medido por partida é o real.
    """

    __slots__ = ("_fonte", "_teto", "_vistas")

    def __init__(self, fonte: PostgresHistoricalMatchStateSource, *, teto: int) -> None:
        self._fonte = fonte
        self._teto = teto
        self._vistas = 0

    async def match_ids(
        self, version_id: str, *, limit: int = 500, after: str | None = None
    ) -> Sequence[MatchId]:
        if self._vistas >= self._teto:
            return []
        restam = self._teto - self._vistas
        pagina = list(
            await self._fonte.match_ids(version_id, limit=min(limit, restam), after=after)
        )
        self._vistas += len(pagina)
        return pagina

    async def load(self, version_id: str, match_ids: Sequence[MatchId]) -> Mapping[MatchId, Any]:
        return await self._fonte.load(version_id, match_ids)


class _Montagem:
    def __init__(self, banco: Any, store: Any) -> None:
        self.banco = banco
        self.repo = PostgresHistoricalFeatureDatasetRepository(banco)
        self.builds = PostgresFeatureDatasetBuildRepository(banco)
        self.manifests = PostgresFeatureDatasetManifestRepository(banco)
        self.corpus = PostgresHistoricalCorpusRepository(banco)
        self.estado = PostgresHistoricalMatchStateSource(banco)
        self.contexto = PostgresHistoricalContextSource(banco)
        self.materializer = ParquetFeatureDatasetMaterializer(
            store, definitions=extended_feature_catalog().definitions
        )
        self.clock = SystemClock()
        self.audit = PostgresAuditLog(banco)

    def construir(
        self,
        *,
        teto: int | None = None,
        batch_size: int = LOTE,
        part_rows: int = DEFAULT_PART_ROWS,
        max_pending_rows: int = DEFAULT_MAX_PENDING_ROWS,
    ) -> BuildHistoricalFeatureDatasetVersion:
        fonte: Any = self.estado if teto is None else _PrimeirasPartidas(self.estado, teto=teto)
        return BuildHistoricalFeatureDatasetVersion(
            datasets=self.repo,
            builds=self.builds,
            manifests=self.manifests,
            state_source=fonte,
            context_source=self.contexto,
            materializer=self.materializer,
            clock=self.clock,
            audit=self.audit,
            batch_size=batch_size,
            part_rows=part_rows,
            max_pending_rows=max_pending_rows,
        )

    @property
    def criar(self) -> CreateHistoricalFeatureDatasetVersion:
        return CreateHistoricalFeatureDatasetVersion(
            datasets=self.repo, corpus=self.corpus, clock=self.clock, audit=self.audit
        )

    def validar(self, *, amostra: int) -> ValidateHistoricalFeatureDatasetVersion:
        return ValidateHistoricalFeatureDatasetVersion(
            datasets=self.repo,
            builds=self.builds,
            manifests=self.manifests,
            materializer=self.materializer,
            state_source=self.estado,
            context_source=self.contexto,
            clock=self.clock,
            audit=self.audit,
            rebuild_sample=amostra,
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

    async def nova_versao(
        self,
        *,
        versao_do_corpus: Any,
        grade: SnapshotGridPolicy,
        version: DatasetVersion,
        nome: str,
    ) -> Any:
        return await self.criar.execute(
            dataset_name=nome,
            version=version,
            source_version_id=versao_do_corpus.id,
            split=await _divisao(self.banco, versao_do_corpus.id),
            grid=grade,
            actor=CONSTRUTOR,
        )


def _estatisticas(objetos: Sequence[Any]) -> dict[str, Any]:
    tamanhos = sorted(o.size_bytes for o in objetos)
    linhas = sorted(o.row_count for o in objetos)
    meio = len(tamanhos) // 2
    return {
        "objetos": len(objetos),
        "bytes_min": tamanhos[0],
        "bytes_mediana": tamanhos[meio],
        "bytes_max": tamanhos[-1],
        "bytes_total": sum(tamanhos),
        "linhas_min": linhas[0],
        "linhas_mediana": linhas[meio],
        "linhas_max": linhas[-1],
    }


def _coeficiente(n1: int, m1: int, n2: int, m2: int) -> float:
    """O `a` de `Memoria ~ a*N + b`, por dois pontos medidos.

    ELE NÃO É UM MODELO ESTATÍSTICO, e o nome não pretende que seja: dois
    pontos e uma reta. Serve para EXTRAPOLAR ordem de grandeza — «a que escala
    isto vira problema?» —, e o baseline marca as extrapolações como
    estimativas.
    """
    return 0.0 if n2 == n1 else (m2 - m1) / (n2 - n1)


def _parquets(saida: Any) -> list[Any]:
    return [o for o in saida.manifest.objects if o.object_key.endswith(".parquet")]


class TestAGradeInteira:
    """§137 ao §142, §17 ao §21. Mil partidas na grade de noventa e um cortes."""

    async def test_materializar_conferir_e_publicar_a_grade_de_producao(
        self,
        cenario: dict[str, Any],  # noqa: F811
    ) -> None:
        versao, manifesto = await _publicar(cenario)
        banco, store = cenario["banco"], cenario["store"]
        montagem = _Montagem(banco, store)
        origem = _origem(versao, manifesto)
        membros = await _contar_membros(banco, versao.id)
        assert membros >= PARTIDAS_DA_GRADE
        nome = f"perf-grade-{_uuid.uuid4().hex[:6]}"

        # ---- a escala MENOR, para a curva de memória e de consultas -------
        menor = await montagem.nova_versao(
            versao_do_corpus=versao,
            grade=DEFAULT_SNAPSHOT_GRID,
            version=DatasetVersion(major=1, minor=0),
            nome=nome,
        )
        async with contando_consultas(banco) as consultas_menor:
            with medindo("grade inteira · 100 partidas") as medida_menor:
                saida_menor = await montagem.construir(teto=PARTIDAS_DA_ESCALA_MENOR).execute(
                    version_id=menor.id,
                    source=origem,
                    dataset_name=nome,
                    actor=CONSTRUTOR,
                )

        # ---- a escala de PRODUÇÃO ----------------------------------------
        maior = await montagem.nova_versao(
            versao_do_corpus=versao,
            grade=DEFAULT_SNAPSHOT_GRID,
            version=DatasetVersion(major=1, minor=1),
            nome=nome,
        )
        async with contando_consultas(banco) as consultas:
            with medindo("grade inteira · construção") as construcao:
                saida = await montagem.construir(teto=PARTIDAS_DA_GRADE).execute(
                    version_id=maior.id,
                    source=origem,
                    dataset_name=nome,
                    actor=CONSTRUTOR,
                )

        # ---- A CURVA DE MEMÓRIA DA VALIDAÇÃO, em DUAS escalas -------------
        #
        # ELA NÃO TEM A MESMA COMPLEXIDADE DA CONSTRUÇÃO, e reportar «o
        # pipeline é limitado» seria impreciso. A construção mantém um
        # orçamento; a validação REÚNE os pares `(chave, digesto)` de partições
        # que se intercalam e os ordena — `O(linhas)` em tuplas compactas. O
        # que se mede aqui é o coeficiente disso.
        with medindo("validação · escala menor") as validacao_menor:
            relatorio_menor = await montagem.validar(amostra=5).execute(
                version_id=menor.id, source=origem, actor=CONSTRUTOR
            )
        with medindo("grade inteira · validação") as validacao:
            relatorio = await montagem.validar(amostra=5).execute(
                version_id=maior.id, source=origem, actor=CONSTRUTOR
            )
        with medindo("grade inteira · publicação") as publicacao:
            publicada = await montagem.publicar.execute(
                version_id=maior.id,
                dataset_name=nome,
                actor=CONSTRUTOR,
                reason="baseline do PR-05.5.1",
            )

        lotes = -(-PARTIDAS_DA_GRADE // LOTE)
        lotes_menor = -(-PARTIDAS_DA_ESCALA_MENOR // LOTE)
        valores = saida.rows_written * FEATURES
        fatos, metadados = _fatos(consultas), _metadados(consultas)
        fatos_menor = _fatos(consultas_menor)
        estatisticas = _estatisticas(_parquets(saida))
        total = construcao.segundos + validacao.segundos + publicacao.segundos
        coeficiente = _coeficiente(
            relatorio_menor.rows_verified,
            validacao_menor.pico_bytes,
            relatorio.rows_verified,
            validacao.pico_bytes,
        )
        # O TAMANHO LÓGICO É UMA ESTIMATIVA DECLARADA, e não uma medida: valor
        # (8 B) + rótulo de disponibilidade (~16 B) por feature, mais as
        # colunas de identidade. O Arrow não expõe um «descomprimido» de
        # largura fixa, então a razão abaixo é uma convenção — e está dita.
        logico = saida.rows_written * (FEATURES * 8 + FEATURES * 16 + 200)

        _relatar(
            f"PR-05.5.1 · grade inteira · {saida.rows_written:_} linhas",
            [
                "-- forma --",
                f"partidas na versão      {membros:_}",
                f"partidas materializadas {saida.matches_processed:_}",
                f"partidas ignoradas      {saida.skipped_count:_}",
                f"cortes por partida      {REGULATION_GRID_SIZE}",
                f"linhas                  {saida.rows_written:_}",
                f"definições              {FEATURES}",
                f"valores de feature      {valores:_}",
                "",
                "-- tempo, por FASE --",
                f"build                   {construcao.segundos:.2f}s",
                f"validate                {validacao.segundos:.2f}s",
                f"publish                 {publicacao.segundos:.2f}s",
                f"total                   {total:.2f}s",
                f"snapshots/sec           {construcao.por_segundo(saida.rows_written):.0f}",
                f"valores/sec             {construcao.por_segundo(valores):.0f}",
                f"validação linhas/sec    {validacao.por_segundo(relatorio.rows_verified):.0f}",
                f"validação objetos/sec   {validacao.por_segundo(relatorio.objects_verified):.1f}",
                "",
                "-- memória (tracemalloc) --",
                f"pico build              {construcao.pico_mb:.0f} MB",
                f"pico validação          {validacao.pico_mb:.0f} MB",
                f"teto de linhas          {DEFAULT_MAX_PENDING_ROWS:_}",
                f"piso atômico (1 grade)  {saida.largest_atomic_match_rows}",
                f"pico em espera          {saida.peak_pending_rows:_} "
                f"(limite exato "
                f"{max(DEFAULT_MAX_PENDING_ROWS, saida.largest_atomic_match_rows):_})",
                f"partições abertas       pico {saida.peak_open_partitions}",
                f"bytes/linha em espera   ~"
                f"{construcao.pico_bytes / max(saida.peak_pending_rows, 1):.0f}",
                "",
                "-- memória, DUAS escalas --",
                f"{PARTIDAS_DA_ESCALA_MENOR:_} partidas  "
                f"{saida_menor.rows_written:_} linhas · {medida_menor.pico_mb:.0f} MB",
                f"{PARTIDAS_DA_GRADE:_} partidas  "
                f"{saida.rows_written:_} linhas · {construcao.pico_mb:.0f} MB",
                f"linhas x{saida.rows_written / saida_menor.rows_written:.0f} · "
                f"memória x{construcao.pico_mb / max(medida_menor.pico_mb, 0.01):.2f}",
                "",
                "-- consultas --",
                f"total                   {consultas.total:_}",
                f"de FATO                 {fatos:_} "
                f"({lotes} lotes de {CONSULTAS_POR_LOTE} + varredura)",
                f"de METADADO             {metadados:_} (ciclo de vida, objetos, trilha)",
                f"não classificadas       {_fora_da_conta(consultas)}",
                f"fato/linha              {fatos / saida.rows_written:.5f}",
                f"fato/partida            {fatos / saida.matches_processed:.3f}",
                f"fato/lote               {fatos / lotes:.1f}",
                f"por alvo                {consultas.por_alvo}",
                "",
                "-- validação, DUAS escalas (memória O(linhas)) --",
                f"{relatorio_menor.rows_verified:_} linhas  "
                f"{validacao_menor.pico_mb:.1f} MB · {validacao_menor.segundos:.2f}s · "
                f"{validacao_menor.pico_bytes / max(relatorio_menor.rows_verified, 1):.0f} B/linha",
                f"{relatorio.rows_verified:_} linhas  "
                f"{validacao.pico_mb:.1f} MB · {validacao.segundos:.2f}s · "
                f"{validacao.pico_bytes / max(relatorio.rows_verified, 1):.0f} B/linha",
                f"modelo ~ a*N + b  a={coeficiente:.0f} B/linha",
                "",
                "-- consultas, DUAS escalas --",
                f"{PARTIDAS_DA_ESCALA_MENOR:_} partidas  {fatos_menor} de fato "
                f"({lotes_menor} lote de {CONSULTAS_POR_LOTE} + varredura + cobertura)",
                f"{PARTIDAS_DA_GRADE:_} partidas  {fatos} de fato "
                f"({lotes} lotes de {CONSULTAS_POR_LOTE} + varredura; a cobertura "
                f"já estava memoizada na fonte)",
                "",
                "-- objetos --",
                f"objetos                 {estatisticas['objetos']:_}",
                f"linhas min/med/max      {estatisticas['linhas_min']:_}/"
                f"{estatisticas['linhas_mediana']:_}/{estatisticas['linhas_max']:_}",
                f"bytes min/med/max       {estatisticas['bytes_min']:_}/"
                f"{estatisticas['bytes_mediana']:_}/{estatisticas['bytes_max']:_}",
                f"bytes totais            {estatisticas['bytes_total'] / 1_048_576:.1f} MB",
                f"bytes/linha             {estatisticas['bytes_total'] / saida.rows_written:.0f}",
                f"razão vs lógico~        {logico / estatisticas['bytes_total']:.1f}x",
                f"pedaço configurado      {DEFAULT_PART_ROWS:_} linhas",
                "",
                "-- metades --",
                f"referência              {saida.counts.reference_matches:_} partidas · "
                f"{saida.counts.reference_rows:_} linhas",
                f"avaliação               {saida.counts.evaluation_matches:_} partidas · "
                f"{saida.counts.evaluation_rows:_} linhas",
            ],
        )

        # §137 — a grade é 91 por partida, e nenhuma partida escapou.
        assert saida.matches_processed == PARTIDAS_DA_GRADE
        assert saida.rows_written == PARTIDAS_DA_GRADE * REGULATION_GRID_SIZE
        assert saida.skipped_count == 0, saida.skipped_matches

        # §8, §138 — NOVENTA E UM CORTES NÃO VIRAM NOVENTA E UMA LEITURAS.
        # As consultas de FATO seguem os LOTES DE PARTIDA.
        #
        # A COBERTURA DE CONTEXTO É PAGA UMA VEZ POR FONTE, e não por execução:
        # `PostgresHistoricalContextSource` a memoiza por versão do corpus, e as
        # duas construções aqui compartilham a mesma instância. A PRIMEIRA paga;
        # a segunda não. Isso não é uma exceção à regra — é a regra sendo mais
        # forte que o enunciado, e o benchmark afirma as duas contas separadas
        # em vez de somar uma cobertura que não aconteceu.
        esperadas_menor = (
            lotes_menor * (CONSULTAS_POR_LOTE + CONSULTA_DE_VARREDURA) + CONSULTAS_DE_COBERTURA
        )
        assert fatos_menor == esperadas_menor, consultas_menor.por_alvo
        esperadas = lotes * (CONSULTAS_POR_LOTE + CONSULTA_DE_VARREDURA)
        assert fatos == esperadas, consultas.por_alvo

        # §14 — a razão por snapshot é quase zero, e CAI com o volume.
        assert fatos / saida.rows_written < 0.001
        assert fatos / saida.rows_written < fatos_menor / saida_menor.rows_written

        # §139 — a divisão é atômica: as duas metades somam o total exato.
        assert saida.counts.reference_rows + saida.counts.evaluation_rows == saida.rows_written
        assert saida.counts.reference_matches + saida.counts.evaluation_matches == PARTIDAS_DA_GRADE

        # §17, §34 — O ORÇAMENTO GLOBAL É RESPEITADO, e o limite é EXATO: o
        # escritor abre espaço ANTES de acrescentar, então não há transbordo
        # transitório para tolerar. É o gate de memória.
        assert saida.peak_pending_rows <= DEFAULT_MAX_PENDING_ROWS, saida.peak_pending_rows
        assert saida_menor.peak_pending_rows <= DEFAULT_MAX_PENDING_ROWS
        # §18 — e ele foi exercitado com VÁRIAS partições abertas ao mesmo
        # tempo: «limitada» não pode significar «o corpus tinha uma partição».
        assert saida.peak_open_partitions >= 2, saida.peak_open_partitions

        # §19, §20 — dez vezes mais linhas NÃO custam dez vezes mais memória.
        assert saida.rows_written >= saida_menor.rows_written * 9
        assert construcao.pico_mb < medida_menor.pico_mb * 3, (
            f"{medida_menor.pico_mb:.0f} MB para {saida_menor.rows_written:_} linhas "
            f"contra {construcao.pico_mb:.0f} MB para {saida.rows_written:_}"
        )

        # §79, §80 — a validação não é O(N²), e é mais barata que a construção.
        assert relatorio.passed, relatorio.failures()
        assert relatorio.rows_verified == saida.rows_written
        assert relatorio_menor.passed, relatorio_menor.failures()
        assert relatorio_menor.rows_verified == saida_menor.rows_written
        assert validacao.segundos < construcao.segundos

        # §8, §23 — A VALIDAÇÃO É `O(linhas)` EM MEMÓRIA, e isto NÃO é uma
        # falha: é a complexidade da implementação atual, medida. O que se
        # afirma é o coeficiente, e o baseline extrapola a partir dele.
        assert validacao.pico_bytes > validacao_menor.pico_bytes
        por_linha = validacao.pico_bytes / relatorio.rows_verified
        assert por_linha < 2_000, f"{por_linha:.0f} B por linha validada"

        # §86 — nada de «uma partida, um objeto».
        assert estatisticas["linhas_min"] >= REGULATION_GRID_SIZE
        assert estatisticas["objetos"] < saida.matches_processed

        # §72 — o ciclo de vida chegou ao fim.
        assert publicada.status is DatasetVersionStatus.READY


class TestOVolumeDePartidas:
    """§143 ao §145, §24, §25. Dez mil partidas na grade reduzida."""

    async def test_dez_mil_partidas_e_a_reprodutibilidade_do_conteudo(
        self,
        cenario: dict[str, Any],  # noqa: F811
    ) -> None:
        versao, manifesto = await _publicar(cenario)
        banco, store = cenario["banco"], cenario["store"]
        montagem = _Montagem(banco, store)
        origem = _origem(versao, manifesto)
        partidas = await _contar_membros(banco, versao.id)
        nome = f"perf-volume-{_uuid.uuid4().hex[:6]}"

        completa = await montagem.nova_versao(
            versao_do_corpus=versao,
            grade=GRADE_REDUZIDA,
            version=DatasetVersion(major=1, minor=0),
            nome=nome,
        )
        async with contando_consultas(banco) as consultas:
            with medindo("volume · construção") as medida:
                saida = await montagem.construir().execute(
                    version_id=completa.id,
                    source=origem,
                    dataset_name=nome,
                    actor=CONSTRUTOR,
                )

        with medindo("volume · validação") as validacao:
            relatorio = await montagem.validar(amostra=5).execute(
                version_id=completa.id, source=origem, actor=CONSTRUTOR
            )

        # ---- §24, §25: o LOTE e o TETO não mudam o conteúdo ---------------
        #
        # SOBRE UM RECORTE DE MIL PARTIDAS, e não sobre as dez mil: o que se
        # prova é uma IGUALDADE, e ela não fica mais verdadeira custando quatro
        # travessias completas do corpus.
        impressoes: dict[str, str] = {}
        for indice, (lote, pedaco, teto) in enumerate(
            [
                (250, DEFAULT_PART_ROWS, DEFAULT_MAX_PENDING_ROWS),
                (500, DEFAULT_PART_ROWS, DEFAULT_MAX_PENDING_ROWS),
                (1_000, DEFAULT_PART_ROWS, DEFAULT_MAX_PENDING_ROWS),
                (500, 200, 400),
            ],
            start=1,
        ):
            variante = await montagem.nova_versao(
                versao_do_corpus=versao,
                grade=GRADE_REDUZIDA,
                version=DatasetVersion(major=2, minor=indice),
                nome=nome,
            )
            resultado = await montagem.construir(
                teto=PARTIDAS_DA_GRADE,
                batch_size=lote,
                part_rows=pedaco,
                max_pending_rows=teto,
            ).execute(
                version_id=variante.id,
                source=origem,
                dataset_name=nome,
                actor=CONSTRUTOR,
            )
            impressoes[f"lote={lote} pedaco={pedaco} teto={teto}"] = (
                resultado.raw_content_fingerprint.value
            )
            assert resultado.peak_pending_rows <= teto

        lotes = -(-partidas // LOTE)
        fatos, metadados = _fatos(consultas), _metadados(consultas)
        estatisticas = _estatisticas(_parquets(saida))

        _relatar(
            f"PR-05.5.1 · volume · {partidas:_} partidas em {CORTES_REDUZIDOS} cortes",
            [
                "-- forma --",
                f"partidas                {saida.matches_processed:_}",
                f"cortes por partida      {CORTES_REDUZIDOS}",
                f"linhas                  {saida.rows_written:_}",
                f"valores de feature      {saida.rows_written * FEATURES:_}",
                "",
                "-- tempo --",
                f"build                   {medida.segundos:.2f}s",
                f"linhas/sec              {medida.por_segundo(saida.rows_written):.0f}",
                f"partidas/sec            {medida.por_segundo(saida.matches_processed):.0f}",
                f"valores/sec             {medida.por_segundo(saida.rows_written * FEATURES):.0f}",
                "",
                "-- memória --",
                f"pico build              {medida.pico_mb:.0f} MB",
                f"pico validação          {validacao.pico_mb:.1f} MB · "
                f"{validacao.pico_bytes / max(relatorio.rows_verified, 1):.0f} B/linha",
                f"validação               {validacao.segundos:.2f}s · "
                f"{validacao.por_segundo(relatorio.rows_verified):.0f} linhas/s · "
                f"{validacao.por_segundo(relatorio.objects_verified):.1f} objetos/s",
                f"teto de linhas          {DEFAULT_MAX_PENDING_ROWS:_}",
                f"piso atômico (1 grade)  {saida.largest_atomic_match_rows}",
                f"pico em espera          {saida.peak_pending_rows:_}",
                f"partições abertas       pico {saida.peak_open_partitions}",
                "",
                "-- consultas --",
                f"total                   {consultas.total:_}",
                f"de FATO                 {fatos:_} ({lotes} lotes)",
                f"de METADADO             {metadados:_}",
                f"não classificadas       {_fora_da_conta(consultas)}",
                f"fato/partida            {fatos / partidas:.4f}",
                f"fato/linha              {fatos / saida.rows_written:.5f}",
                f"por alvo                {consultas.por_alvo}",
                "",
                "-- objetos --",
                f"objetos                 {estatisticas['objetos']:_}",
                f"linhas min/med/max      {estatisticas['linhas_min']:_}/"
                f"{estatisticas['linhas_mediana']:_}/{estatisticas['linhas_max']:_}",
                f"bytes totais            {estatisticas['bytes_total'] / 1_048_576:.1f} MB",
                f"bytes/linha             {estatisticas['bytes_total'] / saida.rows_written:.0f}",
                "",
                "-- determinismo (mil partidas, grade reduzida) --",
                *(f"{rotulo:34} {impressao[:16]}..." for rotulo, impressao in impressoes.items()),
            ],
        )

        # §143 — nenhuma partida escapou, e a grade reduzida é a declarada.
        assert saida.matches_processed == partidas
        assert saida.rows_written == partidas * CORTES_REDUZIDOS
        assert saida.skipped_count == 0

        # §144 — O CUSTO DE CONSULTA DE FATO É O MESMO da grade inteira: ele é
        # do LOTE de partidas, e não dos cortes. A página vazia do fim entra na
        # conta aqui e não lá — lá a varredura é recortada e para sem consultar.
        esperadas = (
            lotes * (CONSULTAS_POR_LOTE + CONSULTA_DE_VARREDURA)
            + CONSULTA_DE_VARREDURA
            + CONSULTAS_DE_COBERTURA
        )
        assert fatos == esperadas, consultas.por_alvo

        # §145 — o pico continua sendo do orçamento, e não do dataset.
        assert saida.peak_pending_rows <= DEFAULT_MAX_PENDING_ROWS
        assert saida.peak_open_partitions >= 2

        # §79, §80 — a validação passa, e o custo dela por linha é o mesmo da
        # grade inteira: ela depende de LINHAS, e não de cortes por partida.
        assert relatorio.passed, relatorio.failures()
        assert relatorio.rows_verified == saida.rows_written

        # §24, §25, §102 — lote, pedaço e teto NÃO mudam a impressão.
        assert len(set(impressoes.values())) == 1, impressoes
