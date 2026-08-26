"""OS BENCHMARKS DO PR-05.5.2: ajustar e normalizar em volume.

O QUE ELES MEDEM, e por que cada um existe:

    O AJUSTE          lê SÓ a metade de referência, com projeção nos 29 eixos
                      `ROBUST`. O que se mede é o custo por linha de
                      referência e o PICO DE MEMÓRIA da acumulação — que é o
                      número que decide se o ajuste exato cabe.

    A CONSTRUÇÃO      lê as duas metades, com os 105 eixos, e escreve o
                      Parquet normalizado. O que se mede é o custo por linha e
                      o teto do escritor.

    A VALIDAÇÃO       relê tudo e reconstrói as três impressões.

    A REPRODUTIBILIDADE  dois ajustes sobre a MESMA referência têm a MESMA
                      impressão — a invariante do PR, medida no caminho
                      completo e em volume.

O NÚMERO QUE MAIS IMPORTA É O PICO DE MEMÓRIA DO AJUSTE. Ele é exato (PR-05.4
§183): a população inteira é ordenada e indexada, sem quantil aproximado. O que
foi comprimido é o ARMAZENAMENTO — um `array('d')` por eixo, e não objetos —, e
este benchmark é onde essa compressão é conferida contra a escala de produção.

    esperado   29 eixos vezes N linhas de referencia vezes 8 bytes
    91.000 linhas / 2 metades ≈ 45.500 de referência ≈ 10,6 MB de valores

O SEGUNDO É A FORMA DA CURVA DE LEITURA. O ajuste lê 29 colunas de 233 e uma
metade de duas; a construção lê 233 de 233 e as duas metades. Se o formato
colunar entrega o que promete, a razão entre os dois tempos por linha é
visivelmente menor que 1.

O CRITÉRIO É A FORMA DA CURVA, e nunca o segundo absoluto.

ESTE ARQUIVO CONSTRÓI O DATASET CRU ANTES DE MEDIR, e o custo dele NÃO entra em
número nenhum deste PR: ele é o insumo, está medido no baseline do PR-05.5.1, e
misturá-lo aqui faria o custo da normalização parecer dez vezes maior do que é.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any, Final

import pytest

from sports_intelligence.application.use_cases.normalized_dataset import (
    BUILD_BATCH_ROWS,
    DEFAULT_MAX_PENDING_ROWS,
    DEFAULT_PART_ROWS,
    FIT_BATCH_ROWS,
)
from sports_intelligence.domain.corpus.versions import DatasetVersionStatus
from sports_intelligence.domain.features.dataset.grid import DEFAULT_SNAPSHOT_GRID
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.versioning import DatasetVersion
from tests.performance.test_event_corpus_scale import cenario  # noqa: F401 — fixture
from tests.performance.test_feature_dataset_scale import (
    CONSTRUTOR,
    PARTIDAS_DA_GRADE,
    _Montagem,
    _origem,
    _publicar,
)
from tests.performance.test_resolution_100k import _relatar
from tests.support.instrumentation import contando_consultas, medindo
from tests.support.normalized_e2e import MontagemNormalizada

pytestmark = pytest.mark.performance

AJUSTADOR: Final[Actor] = Actor.service("normalizer-fitter")

FEATURES: Final[int] = 105
EIXOS_ROBUSTOS: Final[int] = 29

#: As tabelas de METADADO deste PR. Elas seguem a EXECUÇÃO — quantas
#: transições, quantos objetos, quantas linhas de trilha — e não o conteúdo.
ALVOS_DE_METADADO: Final[frozenset[str]] = frozenset(
    {
        "normalizer_artifact_sets",
        "normalizer_artifact_bundles",
        "normalizer_fit_artifacts",
        "normalized_feature_datasets",
        "normalized_feature_dataset_versions",
        "normalized_feature_dataset_build_runs",
        "normalized_feature_dataset_manifests",
        "normalized_feature_objects",
        "dataset_audit_log",
    }
)


def _metadados(contagem: Any) -> int:
    return sum(v for k, v in contagem.por_alvo.items() if k in ALVOS_DE_METADADO)


def _fora_da_conta(contagem: Any) -> dict[str, int]:
    return {k: v for k, v in contagem.por_alvo.items() if k not in ALVOS_DE_METADADO}


class TestOAjusteEANormalizacaoEmVolume:
    """Mil partidas na grade de noventa e um cortes, divididas ao meio."""

    async def test_ajustar_normalizar_conferir_e_publicar(
        self,
        cenario: dict[str, Any],  # noqa: F811
    ) -> None:
        banco, store = cenario["banco"], cenario["store"]

        # ---- o INSUMO: o dataset cru, construído e publicado -------------
        #
        # O CUSTO DELE NÃO ENTRA EM NÚMERO NENHUM deste relatório. Ele está
        # medido no baseline do PR-05.5.1, e misturá-lo aqui faria o custo da
        # normalização parecer dez vezes maior do que é.
        versao_corpus, manifesto = await _publicar(cenario)
        crua = _Montagem(banco, store)
        origem = _origem(versao_corpus, manifesto)
        nome_cru = f"perf-cru-{_uuid.uuid4().hex[:6]}"
        versao_crua = await crua.nova_versao(
            versao_do_corpus=versao_corpus,
            grade=DEFAULT_SNAPSHOT_GRID,
            version=DatasetVersion(major=1, minor=0),
            nome=nome_cru,
        )
        saida_crua = await crua.construir(teto=PARTIDAS_DA_GRADE).execute(
            version_id=versao_crua.id,
            source=origem,
            dataset_name=nome_cru,
            actor=CONSTRUTOR,
        )
        relatorio_cru = await crua.validar(amostra=1).execute(
            version_id=versao_crua.id, source=origem, actor=CONSTRUTOR
        )
        assert relatorio_cru.passed, relatorio_cru.failures()
        publicada_crua = await crua.publicar.execute(
            version_id=versao_crua.id,
            dataset_name=nome_cru,
            actor=CONSTRUTOR,
            reason="insumo do benchmark do PR-05.5.2",
        )
        assert publicada_crua.status is DatasetVersionStatus.READY

        montagem = MontagemNormalizada(
            banco,
            store,
            reference_end_exclusive=publicada_crua.spec.reference_end_exclusive,
        )
        linhas_de_referencia = publicada_crua.counts.reference_rows

        # ---- 1. O AJUSTE -------------------------------------------------
        async with contando_consultas(banco) as consultas_ajuste:
            with medindo("ajuste · referência") as medida_ajuste:
                ajuste = await montagem.ajustar.execute(
                    source_version_id=publicada_crua.id,
                    raw_dataset_name=nome_cru,
                    actor=AJUSTADOR,
                    batch_rows=FIT_BATCH_ROWS,
                )

        with medindo("ajuste · conferência") as medida_conferencia:
            relatorio_ajuste = await montagem.conferir_ajuste.execute(
                artifact_set_id=ajuste.artifact_set.id,
                actor=AJUSTADOR,
                reason="baseline do PR-05.5.2",
            )
        assert relatorio_ajuste.passed, relatorio_ajuste.divergences

        # ---- 2. A CONSTRUÇÃO NORMALIZADA ---------------------------------
        nome = f"perf-norm-{_uuid.uuid4().hex[:6]}"
        versao = await montagem.criar.execute(
            version=DatasetVersion(major=1, minor=0),
            source_version_id=publicada_crua.id,
            artifact_set_id=ajuste.artifact_set.id,
            dataset_name=nome,
            actor=AJUSTADOR,
        )
        async with contando_consultas(banco) as consultas_build:
            with medindo("normalização · construção") as construcao:
                saida = await montagem.construir.execute(
                    version_id=versao.id,
                    dataset_name=nome,
                    raw_dataset_name=nome_cru,
                    actor=AJUSTADOR,
                    part_rows=DEFAULT_PART_ROWS,
                    max_pending_rows=DEFAULT_MAX_PENDING_ROWS,
                    batch_rows=BUILD_BATCH_ROWS,
                )

        # ---- 3. A VALIDAÇÃO ----------------------------------------------
        with medindo("normalização · validação") as validacao:
            relatorio = await montagem.validar.execute(
                version_id=versao.id, raw_dataset_name=nome_cru, actor=AJUSTADOR
            )
        assert relatorio.passed, relatorio.failures

        # ---- 4. A PUBLICAÇÃO ---------------------------------------------
        with medindo("normalização · publicação") as publicacao:
            publicada = await montagem.publicar.execute(
                version_id=versao.id,
                dataset_name=nome,
                actor=AJUSTADOR,
                reason="baseline do PR-05.5.2",
            )

        # ---- 5. A REPRODUTIBILIDADE DA IDENTIDADE ------------------------
        #
        # SEM REUSO, para que o segundo ajuste seja de fato calculado de novo:
        # reusar o primeiro provaria só que a busca por impressão funciona.
        with medindo("ajuste · reexecução") as reexecucao:
            segundo = await montagem.ajustar.execute(
                source_version_id=publicada_crua.id,
                raw_dataset_name=nome_cru,
                actor=AJUSTADOR,
                batch_rows=FIT_BATCH_ROWS,
                reuse_existing=False,
            )

        celulas = saida.rows_written * FEATURES
        ref_por_s = ajuste.reference_rows / max(medida_ajuste.segundos, 1e-9)
        bytes_por_ref = medida_ajuste.pico_bytes / max(ajuste.reference_rows, 1)
        linhas_por_s = saida.rows_written / max(construcao.segundos, 1e-9)
        celulas_por_s = celulas / max(construcao.segundos, 1e-9)
        val_por_s = relatorio.rows / max(validacao.segundos, 1e-9)
        objetos = [o for o in saida.objects if o.object_key.endswith(".parquet")]
        tamanhos = sorted(o.size_bytes for o in objetos)
        linhas_por_objeto = sorted(o.row_count for o in objetos)
        meio = len(tamanhos) // 2

        _relatar(
            "PR-05.5.2 - ajuste causal e dataset normalizado",
            [
                "-- o insumo (medido no PR-05.5.1, e fora desta conta) --",
                f"linhas cruas            {saida_crua.rows_written:_}",
                f"referencia              {linhas_de_referencia:_}",
                f"avaliacao               {publicada_crua.counts.evaluation_rows:_}",
                "",
                "-- 1. o ajuste --",
                f"linhas lidas            {ajuste.reference_rows:_}",
                f"competicoes             {ajuste.competitions}",
                f"artefatos               {ajuste.artifacts:_}",
                f"  ajustados             {ajuste.fitted:_}",
                f"  amostra insuficiente  {ajuste.insufficient:_}",
                f"  sem dispersao         {ajuste.degenerate:_}",
                f"tempo                   {medida_ajuste.segundos:.2f}s",
                f"linhas/s                {ref_por_s:,.0f}",
                f"memoria                 {medida_ajuste.pico_bytes / 1_048_576:.1f} MB",
                f"  bytes/linha ref       {bytes_por_ref:,.0f}",
                f"consultas de metadado   {_metadados(consultas_ajuste)}",
                f"conferencia             {medida_conferencia.segundos:.2f}s",
                "",
                "-- 2. a construcao normalizada --",
                f"linhas lidas            {saida.rows_read:_}",
                f"linhas escritas         {saida.rows_written:_}",
                f"celulas                 {celulas:_}",
                f"tempo                   {construcao.segundos:.2f}s",
                f"linhas/s                {linhas_por_s:,.0f}",
                f"celulas/s               {celulas_por_s:,.0f}",
                f"memoria                 {construcao.pico_bytes / 1_048_576:.1f} MB",
                f"pico em espera          {saida.peak_pending_rows:_} / "
                f"{DEFAULT_MAX_PENDING_ROWS:_}",
                f"particoes abertas       {saida.peak_open_partitions}",
                f"consultas de metadado   {_metadados(consultas_build)}",
                "",
                "-- as tres familias de disponibilidade --",
                *(
                    f"{estado:<23} {contagem:_}"
                    for estado, contagem in sorted(saida.availability.by_state.items())
                ),
                f"sem escala (ARTIFACT_*)  {saida.availability.artifact_unavailable:_}",
                "",
                "-- 3. a validacao --",
                f"tempo                   {validacao.segundos:.2f}s",
                f"linhas/s                {val_por_s:,.0f}",
                f"memoria                 {validacao.pico_bytes / 1_048_576:.1f} MB",
                f"objetos conferidos      {relatorio.objects}",
                "",
                "-- 4. a publicacao --",
                f"tempo                   {publicacao.segundos:.2f}s",
                "",
                "-- os objetos --",
                f"objetos                 {len(objetos)}",
                f"bytes total             {sum(tamanhos) / 1_048_576:.1f} MB",
                f"bytes/linha             {sum(tamanhos) / max(saida.rows_written, 1):,.0f}",
                f"linhas por objeto       min {linhas_por_objeto[0]:_} - "
                f"mediana {linhas_por_objeto[meio]:_} - max {linhas_por_objeto[-1]:_}",
                "",
                "-- 5. a identidade --",
                f"representacao           {versao.representation_fingerprint[:16]}",
                f"normalizada             {saida.fingerprint[:16]}",
                f"referencia              {saida.reference_fingerprint[:16]}",
                f"avaliacao               {saida.evaluation_fingerprint[:16]}",
                f"reexecucao do ajuste    {reexecucao.segundos:.2f}s",
                f"mesma impressao?        {segundo.fingerprint == ajuste.fingerprint}",
                "",
                "-- o que ficou fora da conta de metadado --",
                f"ajuste                  {_fora_da_conta(consultas_ajuste)}",
                f"construcao              {_fora_da_conta(consultas_build)}",
            ],
        )

        # ---- as afirmações ------------------------------------------------

        assert publicada.status is DatasetVersionStatus.READY

        # O CONTRATO 1:1, em volume.
        assert saida.rows_read == saida.rows_written
        assert saida.rows_written == saida_crua.rows_written
        assert saida.availability.total_cells == saida.rows_written * FEATURES

        # A COBERTURA DO AJUSTE: 29 eixos por competição, e nenhum a mais.
        assert ajuste.artifacts == EIXOS_ROBUSTOS * ajuste.competitions

        # A MEMÓRIA DO AJUSTE É LIMITADA PELA REFERÊNCIA, e não pelo dataset.
        # O piso teorico e `29 vezes N vezes 8` bytes de valores; o teto aceito e uma
        # ordem de grandeza acima dele — o que sobra é o interpretador, os
        # acumuladores de hash e o lote de leitura em trânsito.
        piso = EIXOS_ROBUSTOS * ajuste.reference_rows * 8
        assert medida_ajuste.pico_bytes < piso * 10, (
            f"o ajuste reteve {medida_ajuste.pico_bytes:_} bytes contra um piso de "
            f"{piso:_}: a acumulação deixou de ser por `array('d')`"
        )

        # O TETO DO ESCRITOR é respeitado.
        assert saida.peak_pending_rows <= DEFAULT_MAX_PENDING_ROWS

        # A INVARIANTE CENTRAL, em volume: reajustar dá a MESMA impressão.
        assert segundo.artifact_set.id != ajuste.artifact_set.id
        assert segundo.fingerprint == ajuste.fingerprint
        assert segundo.reference_rows == ajuste.reference_rows

        # AS TRÊS IMPRESSÕES SÃO DIFERENTES ENTRE SI — o dataset tem as duas
        # metades, e a global não pode coincidir com nenhuma delas.
        assert (
            len({saida.fingerprint, saida.reference_fingerprint, saida.evaluation_fingerprint}) == 3
        )

        # AS DUAS METADES ESTÃO NO ARQUIVO.
        metades = {o.split for o in objetos}
        assert metades == {DatasetSplit.REFERENCE, DatasetSplit.EVALUATION}
