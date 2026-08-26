"""As três propriedades do gate do PR-05.5.1 — escala, reprodutibilidade, isolamento.

O QUE ESTE ARQUIVO PROVA, e nenhum outro prova:

    REPRODUTIBILIDADE
      o tamanho do LOTE não muda a impressão
      o teto do ESCRITOR não muda a impressão
      a ORDEM DE INSERÇÃO dos fatos não muda a impressão
      a FRONTEIRA DE DESCARGA não muda a impressão

    ESCALA
      noventa e um cortes de uma partida custam UMA carga dela
      as consultas seguem os LOTES, e não os snapshots
      o pico de linhas em espera respeita o orçamento GLOBAL
      ele respeita mesmo com muitas partições abertas ao mesmo tempo

    ISOLAMENTO
      uma partida absurda na AVALIAÇÃO não toca uma linha da REFERÊNCIA
      um fato que não pertence à versão não entra no dataset

A FORMA DAS PROVAS DE REPRODUTIBILIDADE É SEMPRE A MESMA: construir duas vezes
mudando UMA coisa que não é conteúdo, e exigir a MESMA impressão. É a única
forma que pega o acoplamento acidental — uma impressão que dependesse da ordem
de descarga passaria em qualquer teste de valor.
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from sports_intelligence.application.use_cases.feature_dataset import (
    BuildHistoricalFeatureDatasetVersion,
    CreateHistoricalFeatureDatasetVersion,
)
from sports_intelligence.domain.corpus.versions import DatasetVersionStatus
from sports_intelligence.domain.features.dataset.grid import (
    DEFAULT_SNAPSHOT_GRID,
    REGULATION_GRID_SIZE,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.dataset.versions import (
    DEFAULT_FEATURE_DATASET_NAME,
)
from sports_intelligence.domain.shared.actor import Actor
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
    PARTIDAS_DO_CENARIO,
    corpus_do_cenario,
    divisao,
    id_de_partida,
    origem_do_cenario,
)
from tests.support.registry_fakes import FakeAuditLog
from tests.unit.test_feature_dataset_use_cases import FakeCorpusRepo, _versao_de_corpus

AGORA = instant(datetime(2026, 5, 1, 12, 0, tzinfo=UTC))
ATOR = Actor.service("pr0551")
NOME = DEFAULT_FEATURE_DATASET_NAME
LINHAS_ESPERADAS = PARTIDAS_DO_CENARIO * REGULATION_GRID_SIZE


class Execucao:
    """Uma construção completa em memória, com os parâmetros abertos."""

    def __init__(
        self,
        *,
        corpus: dict[Any, Any] | None = None,
        batch_size: int = 500,
        part_rows: int = 5_000,
        max_pending_rows: int = 10_000,
    ) -> None:
        self.corpus = corpus if corpus is not None else corpus_do_cenario()
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
        self.batch_size = batch_size
        self.part_rows = part_rows
        self.max_pending_rows = max_pending_rows

    async def executar(self) -> Any:
        criar = CreateHistoricalFeatureDatasetVersion(
            datasets=self.repo,
            corpus=self.corpus_repo,  # type: ignore[arg-type]
            clock=self.clock,
            audit=self.audit,
        )
        versao = await criar.execute(
            dataset_name=NOME,
            version=DatasetVersion(major=1, minor=0),
            source_version_id=self.origem.version_id,
            split=divisao(),
            grid=DEFAULT_SNAPSHOT_GRID,
            actor=ATOR,
            published_families=self.origem.published_families,
        )
        construir = BuildHistoricalFeatureDatasetVersion(
            datasets=self.repo,
            builds=self.builds,
            manifests=self.manifests,
            state_source=self.estado,
            context_source=self.contexto,
            materializer=self.materializer,
            clock=self.clock,
            audit=self.audit,
            batch_size=self.batch_size,
            part_rows=self.part_rows,
            max_pending_rows=self.max_pending_rows,
        )
        return await construir.execute(
            version_id=versao.id,
            source=self.origem,
            dataset_name=NOME,
            actor=ATOR,
        )


async def _impressao(**kwargs: Any) -> str:
    saida = await Execucao(**kwargs).executar()
    assert saida.rows_written > 0
    return str(saida.raw_content_fingerprint.value)


# ==================================================== reprodutibilidade ==


class TestOLoteNaoMudaAImpressao:
    """§24. Lotes diferentes, mesmo conteúdo."""

    @pytest.mark.parametrize("lote", [1, 2, 3, 5, 500])
    async def test_qualquer_lote_produz_a_mesma_impressao(self, lote: int) -> None:
        referencia = await _impressao(batch_size=500)
        assert await _impressao(batch_size=lote) == referencia

    async def test_o_lote_muda_as_CONSULTAS_e_nao_o_conteudo(self) -> None:
        """A prova de que o lote é decisão de EXECUÇÃO, e não de conteúdo."""
        pequeno, grande = Execucao(batch_size=1), Execucao(batch_size=500)
        a, b = await pequeno.executar(), await grande.executar()
        assert a.raw_content_fingerprint == b.raw_content_fingerprint
        assert pequeno.estado.cargas > grande.estado.cargas


class TestOTetoDoEscritorNaoMudaAImpressao:
    """§25, §23. A fronteira de descarga é física, e não semântica."""

    @pytest.mark.parametrize(
        ("pedaco", "teto"),
        [(91, 91), (100, 200), (5_000, 10_000), (200, 5_000)],
    )
    async def test_qualquer_orcamento_produz_a_mesma_impressao(
        self, pedaco: int, teto: int
    ) -> None:
        referencia = await _impressao()
        assert await _impressao(part_rows=pedaco, max_pending_rows=teto) == referencia

    async def test_o_orcamento_muda_o_NUMERO_DE_OBJETOS_e_nao_o_conteudo(self) -> None:
        """§26 — a identidade oficial é a impressão, e nunca os bytes do Parquet."""
        miudo, graudo = Execucao(part_rows=91, max_pending_rows=91), Execucao()
        a, b = await miudo.executar(), await graudo.executar()
        assert a.raw_content_fingerprint == b.raw_content_fingerprint
        assert a.objects_written > b.objects_written


class TestAOrdemDeInsercaoNaoMudaAImpressao:
    """§27, §28. A varredura é ordenada pela chave, e não pela inserção."""

    async def test_embaralhar_o_corpus_nao_muda_a_impressao(self) -> None:
        original = corpus_do_cenario()
        chaves = list(original)
        random.Random(20260825).shuffle(chaves)
        embaralhado = {chave: original[chave] for chave in chaves}
        assert list(embaralhado) != list(original)
        assert await _impressao(corpus=embaralhado) == await _impressao(corpus=original)

    async def test_cada_objeto_sai_em_ordem_de_chave(self) -> None:
        """DENTRO do arquivo, e não entre arquivos: as partições se intercalam
        por partida, e é a validação que reordena globalmente para reconstruir
        a cadeia."""
        execucao = Execucao()
        await execucao.executar()
        for linhas in execucao.materializer.objects.values():
            chaves = [linha.key for linha in linhas]
            assert chaves == sorted(chaves)

    async def test_o_conjunto_de_chaves_nao_tem_repeticao(self) -> None:
        """§46 — `(metade, partida, corte)` é única na versão."""
        execucao = Execucao()
        await execucao.executar()
        chaves = [linha.key for linha in execucao.materializer.linhas]
        assert len(set(chaves)) == len(chaves)


# ================================================================ escala ==


class TestOReusoDoInsumoDaPartida:
    """§12, §15. Noventa e um cortes de uma partida custam UMA carga dela."""

    async def test_noventa_e_um_cortes_nao_recarregam_a_partida(self) -> None:
        execucao = Execucao(batch_size=500)
        saida = await execucao.executar()
        assert saida.rows_written == LINHAS_ESPERADAS
        # UMA carga por LOTE, e um lote só neste cenário.
        assert execucao.estado.cargas == 1
        assert execucao.estado.partidas_carregadas == PARTIDAS_DO_CENARIO
        assert execucao.contexto.consultas == 1

    async def test_as_cargas_seguem_os_LOTES_e_nao_os_snapshots(self) -> None:
        """§8, §11 — `Queries = O(matchBatches)`, e nunca `O(snapshots)`."""
        for lote in (1, 2, 3, 6):
            execucao = Execucao(batch_size=lote)
            saida = await execucao.executar()
            lotes = -(-PARTIDAS_DO_CENARIO // lote)
            assert execucao.estado.cargas == lotes, lote
            assert execucao.contexto.consultas == lotes, lote
            # E a razão por snapshot cai à medida que o lote cresce.
            assert execucao.estado.cargas <= saida.rows_written / REGULATION_GRID_SIZE

    async def test_a_carga_por_snapshot_e_muito_menor_que_um(self) -> None:
        execucao = Execucao(batch_size=500)
        saida = await execucao.executar()
        por_snapshot = execucao.estado.consultas / saida.rows_written
        assert por_snapshot < 0.01, por_snapshot


class TestOOrcamentoGlobalEObservado:
    """§17, §18, §19, §21. A memória segue o orçamento, e não o dataset."""

    async def test_o_pico_em_espera_respeita_o_teto(self) -> None:
        execucao = Execucao(part_rows=91, max_pending_rows=200)
        saida = await execucao.executar()
        assert saida.peak_pending_rows <= 200, saida.peak_pending_rows
        assert saida.rows_written > 200

    @pytest.mark.parametrize("partidas", [3, 6])
    async def test_o_pico_nao_cresce_com_o_dataset(self, partidas: int) -> None:
        """§19, §20 — dobrar as partidas não dobra o pico."""
        execucao = Execucao(
            corpus=corpus_do_cenario(partidas=partidas),
            part_rows=91,
            max_pending_rows=200,
        )
        saida = await execucao.executar()
        assert saida.peak_pending_rows <= 200
        assert saida.rows_written == partidas * REGULATION_GRID_SIZE

    async def test_o_LIMITE_EXATO_e_o_maximo_entre_teto_e_grade(self) -> None:
        """§5, §7, §48. A INVARIANTE FORMAL, e ela não tem tolerância:

            peak_pending_rows <= max(max_pending_rows, largest_atomic_match)

        UMA PARTIDA É INDIVISÍVEL. Os noventa e um cortes dela precisam ir ao
        mesmo arquivo, então entram numa admissão só. Com um teto MENOR que a
        grade, o escritor esvazia tudo que pode e admite a partida assim mesmo
        — e o pico fica do tamanho da grade.

        ISSO NÃO É TRANSBORDO, é o PISO do orçamento. A diferença importa: um
        transbordo seria `teto + alguma coisa` e cresceria com o uso; o piso é
        uma constante do domínio, e o número que o nomeia está na saída.
        """
        for teto in (50, 91, 200, 10_000):
            execucao = Execucao(part_rows=50, max_pending_rows=teto)
            saida = await execucao.executar()
            piso = saida.largest_atomic_match_rows
            assert piso == REGULATION_GRID_SIZE, piso
            assert saida.peak_pending_rows <= max(teto, piso), (
                f"teto={teto} piso={piso} pico={saida.peak_pending_rows}"
            )

    async def test_com_teto_MENOR_que_a_grade_o_pico_e_a_grade(self) -> None:
        """O caso extremo do piso, isolado: teto de 50 e grade de 91."""
        execucao = Execucao(part_rows=50, max_pending_rows=50)
        saida = await execucao.executar()
        assert saida.largest_atomic_match_rows == REGULATION_GRID_SIZE
        assert saida.peak_pending_rows == REGULATION_GRID_SIZE

    async def test_com_teto_MAIOR_que_a_grade_o_pico_respeita_o_teto(self) -> None:
        """E o caso normal: o teto manda, e o piso não aparece."""
        execucao = Execucao(part_rows=91, max_pending_rows=300)
        saida = await execucao.executar()
        assert saida.peak_pending_rows <= 300
        assert saida.rows_written > 300

    async def test_o_pico_de_particoes_abertas_e_reportado(self) -> None:
        """§18 — «limitada» não pode significar «o corpus tinha uma partição»."""
        saida = await Execucao().executar()
        assert saida.peak_open_partitions >= 1


# ============================================================ isolamento ==


class TestOIsolamentoEntreAsMetades:
    """§40, §41, §42."""

    async def test_nenhuma_partida_aparece_nas_duas_metades(self) -> None:
        execucao = Execucao()
        await execucao.executar()
        por_metade: dict[str, set[str]] = {}
        for linha in execucao.materializer.linhas:
            por_metade.setdefault(linha.split.value, set()).add(linha.key.match_key)
        referencia = por_metade.get(DatasetSplit.REFERENCE.value, set())
        avaliacao = por_metade.get(DatasetSplit.EVALUATION.value, set())
        assert referencia
        assert avaliacao
        assert not (referencia & avaliacao)

    async def test_uma_partida_ABSURDA_na_avaliacao_nao_toca_a_referencia(
        self,
    ) -> None:
        """§42. O sentinela: se um fato da avaliação alcançasse a referência, a
        divisão inteira não valeria nada — e o número que sairia da avaliação
        pareceria excelente."""
        original = corpus_do_cenario()
        normal = Execucao(corpus=original)
        saida_normal = await normal.executar()

        # A ÚLTIMA PARTIDA é a mais tardia, e cai na avaliação. Ela recebe uma
        # história grotesca: cem gols, e o placar final trocado.
        from sports_intelligence.domain.events.taxonomy import EventType
        from sports_intelligence.domain.matches.result import MatchResult, Score
        from tests.support.snapshot_fixtures import evento

        alvo = id_de_partida(PARTIDAS_DO_CENARIO - 1)
        absurda = replace(
            original[alvo],
            candidate_events=(
                *original[alvo].candidate_events,
                *(
                    evento(
                        f"absurdo-{n}",
                        tipo=EventType.GOAL,
                        minuto=10 + n,
                        match_id=alvo,
                    )
                    for n in range(25)
                ),
            ),
            # O TETO DO `Score` É 30, e é uma guarda do PR-01 contra coluna
            # trocada. O sentinela usa o valor mais extremo que o domínio
            # aceita: se ele alcançasse a referência, alcançaria com folga.
            result=MatchResult(regular_time=Score(home=30, away=0)),
        )
        adulterado = {**original, alvo: absurda}
        sentinela = Execucao(corpus=adulterado)
        saida_sentinela = await sentinela.executar()

        assert saida_normal.raw_content_fingerprint != (saida_sentinela.raw_content_fingerprint)
        antes = {
            linha.key.text: linha.digest
            for linha in normal.materializer.linhas
            if linha.split is DatasetSplit.REFERENCE
        }
        depois = {
            linha.key.text: linha.digest
            for linha in sentinela.materializer.linhas
            if linha.split is DatasetSplit.REFERENCE
        }
        assert antes
        assert antes == depois
        assert saida_normal.counts.reference_rows == (saida_sentinela.counts.reference_rows)


class TestOIsolamentoEntreVersoes:
    """§71. Um fato global que a versão não publica não entra no dataset."""

    async def test_partida_ausente_da_versao_nao_vira_linha(self) -> None:
        original = corpus_do_cenario()
        fora = id_de_partida(0)
        parcial = {k: v for k, v in original.items() if k != fora}
        execucao = Execucao(corpus=parcial)
        saida = await execucao.executar()
        assert saida.matches_processed == PARTIDAS_DO_CENARIO - 1
        assert fora is not None
        assert str(fora) not in {linha.key.match_key for linha in execucao.materializer.linhas}

    async def test_a_impressao_muda_quando_a_pertinencia_muda(self) -> None:
        """Duas versões com partidas diferentes NÃO são o mesmo dataset."""
        completa = await _impressao()
        parcial = await _impressao(corpus=corpus_do_cenario(partidas=PARTIDAS_DO_CENARIO - 1))
        assert completa != parcial


class TestOEstadoFinalDaConstrucao:
    async def test_a_versao_fica_conferivel_e_nao_publicada(self) -> None:
        saida = await Execucao().executar()
        assert saida.version.status is DatasetVersionStatus.VALIDATING
        assert not saida.version.is_readable
