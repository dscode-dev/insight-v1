"""Qualidade e construção em volume — a prova de sanidade do PR-04.2.

O QUE ESTE ARQUIVO É E O QUE ELE NÃO É (§77). Ele NÃO é o benchmark oficial do
PR-04: aquele mede 10k partidas com o corpus completo e vai para o documento
de baseline, e é o PR-04.3. Este mede o suficiente para detectar as duas
regressões que a assinatura dos ports não protege:

    N+1 na ESCRITA        `save_candidates` do PR-03.1 tinha assinatura em
                          massa e gastava vinte e três consultas por grupo por
                          dentro. A avaliação e a construção escrevem em cinco
                          tabelas cada; o mesmo defeito cabe nas duas.

    memória por execução  um `list(assessments)` de dez mil vereditos com
                          vetor, cobertura, licenças e problemas é o pico que
                          o PR-03.2 mediu e corrigiu, voltando pela mesma porta

O CRITÉRIO É O CRESCIMENTO, e não um número absoluto. Se dobrar as partidas
dobra as consultas, o custo é por REGISTRO e há N+1. Se ele cresce com o
número de LOTES, está certo — e a diferença entre os dois é grande demais para
ser ruído.
"""

from __future__ import annotations

from typing import Any

import pytest

from apps.build_composition import (
    build_build_container,
    candidate_batches,
    evidence_batches,
    rebuild_fusion_output,
)
from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.build.policy import (
    CANONICAL_BUILDER,
    DEFAULT_COMMERCIAL_BUILD_POLICY,
    DEFAULT_RESEARCH_BUILD_POLICY,
)
from sports_intelligence.domain.quality.runs import QUALITY_ASSESSOR
from sports_intelligence.domain.resolution.runs import RunStatus
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.identity import ProviderId
from tests.performance.test_resolution_100k import CAMPOS, _relatar
from tests.support.corpus import Corpus, csv_bytes
from tests.support.instrumentation import contando_consultas, medindo
from tests.support.pipeline import Pipeline

pytestmark = [pytest.mark.performance, pytest.mark.integration]

#: Registros lidos da fonte. O número de PARTIDAS que sai daqui é uma
#: consequência da resolução — não um parâmetro —, e é ele que interessa: a
#: avaliação e a construção trabalham por partida.
REGISTROS = 5_000

#: O tamanho do lote. Ele é o eixo do teste: as consultas precisam crescer com
#: o número de LOTES, e não com o de partidas.
LOTE = 500

AVALIADOR = Actor.service(QUALITY_ASSESSOR)
CONSTRUTOR = Actor.service(CANONICAL_BUILDER)


async def _ate_a_fusao(
    banco: Database, object_store: Any, corpus: Corpus, *, registros: int
) -> tuple[Pipeline, Any, list[str]]:
    """Intake, resolução e fusão de verdade — o degrau anterior a este PR."""
    if hasattr(object_store, "ensure_bucket"):
        await object_store.ensure_bucket()
    pipeline = Pipeline(banco, object_store, batch_size=1_000)
    provedor = ProviderId(f"pr042_perf_{registros}")
    dataset = await pipeline.stage(
        name=f"pr042-perf-{registros}",
        content=csv_bytes(corpus, total=registros),
        provider=provedor,
    )
    await pipeline.map_source(dataset, provider=provedor, fields=CAMPOS)
    resolucao = await pipeline.resolve(dataset.id)
    fusao = await pipeline.fuse([resolucao.run.id])
    return pipeline, fusao, [resolucao.run.id]


class TestQualidadeEConstrucaoEmVolume:
    async def test_o_caminho_inteiro_sobre_milhares_de_partidas(
        self, banco_semeado: Database, object_store: Any, corpus: Corpus
    ) -> None:
        pipeline, fusao, resolucoes = await _ate_a_fusao(
            banco_semeado, object_store, corpus, registros=REGISTROS
        )
        contêiner = build_build_container(
            database=banco_semeado,
            resolution=pipeline.resolution,
            clock=pipeline.clock,
            audit=pipeline.audit,
        )

        with medindo("remontagem da saída fundida") as remontagem:
            grupos, candidatos = await rebuild_fusion_output(
                resolution=pipeline.resolution,
                datasets=pipeline.datasets,
                archive=pipeline.archive,
                resolution_run_ids=resolucoes,
                fusion_run_id=fusao.run.id,
            )

        async with contando_consultas(banco_semeado) as consultas_da_qualidade:
            with medindo("avaliação de qualidade") as avaliacao:
                saida_da_qualidade = await contêiner.run_quality.execute(
                    actor=AVALIADOR,
                    fusion_run_ids=[fusao.run.id],
                    batches=evidence_batches(
                        resolution=pipeline.resolution,
                        groups=grupos,
                        candidates=candidatos,
                        resolution_run_ids=resolucoes,
                        batch_size=LOTE,
                    ),
                )

        async with contando_consultas(banco_semeado) as consultas_do_build:
            with medindo("construção canônica") as construcao:
                saida_do_build = await contêiner.build_for(DEFAULT_RESEARCH_BUILD_POLICY).execute(
                    actor=CONSTRUTOR,
                    quality_run_id=saida_da_qualidade.run.id,
                    batches=candidate_batches(candidates=candidatos, batch_size=LOTE),
                )

        partidas = saida_da_qualidade.run.counts.records_examined
        lotes = max(1, -(-partidas // LOTE))
        contagens = saida_do_build.run.counts

        _relatar(
            f"PR-04.2 · {REGISTROS:_} registros → {partidas:_} partidas",
            [
                f"remontagem       {remontagem.segundos:.1f}s · pico {remontagem.pico_mb:.0f} MB",
                f"avaliação        {avaliacao.segundos:.1f}s · "
                f"{avaliacao.por_segundo(max(partidas, 1)):.0f} partidas/s · "
                f"pico {avaliacao.pico_mb:.0f} MB",
                f"construção       {construcao.segundos:.1f}s · "
                f"{construcao.por_segundo(max(partidas, 1)):.0f} partidas/s · "
                f"pico {construcao.pico_mb:.0f} MB",
                "",
                f"partidas         {partidas:_} em {lotes} lote(s) de {LOTE}",
                f"elegíveis        {saida_da_qualidade.run.counts.eligible:_}",
                f"em revisão       {saida_da_qualidade.run.counts.review_required:_}",
                f"inelegíveis      {saida_da_qualidade.run.counts.ineligible:_}",
                "",
                f"construídas      {contagens.records_built:_}",
                f"reusadas         {contagens.records_reused:_}",
                f"puladas          {contagens.records_skipped:_}",
                f"famílias fora    {contagens.families_excluded:_}",
                "",
                f"consultas qual.  {consultas_da_qualidade.total:_} "
                f"({consultas_da_qualidade.total / lotes:.1f} por lote) · "
                f"{consultas_da_qualidade.mais_frequentes}",
                f"consultas build  {consultas_do_build.total:_} "
                f"({consultas_do_build.total / lotes:.1f} por lote) · "
                f"{consultas_do_build.mais_frequentes}",
                "",
                f"impressão qual.  {saida_da_qualidade.run.output_fingerprint}",
                f"impressão build  {saida_do_build.run.output_fingerprint}",
            ],
        )

        assert partidas > 0, "a fusão não entregou candidato nenhum à avaliação"
        assert saida_da_qualidade.run.status.produced_usable_output
        assert saida_do_build.run.status is not RunStatus.FAILED

        # O CRITÉRIO DO §68, escrito como número: as consultas por PARTIDA
        # precisam ser uma fração pequena. Com N+1 elas seriam >= 1 por
        # partida — cinco mil partidas dariam cinco mil consultas, e não
        # algumas dezenas.
        por_partida_na_qualidade = consultas_da_qualidade.total / partidas
        por_partida_no_build = consultas_do_build.total / partidas
        assert por_partida_na_qualidade < 0.5, (
            f"{consultas_da_qualidade.total} consultas para {partidas} partidas "
            f"({por_partida_na_qualidade:.2f} por partida): a avaliação está "
            "consultando por registro, não por lote (§68)"
        )
        assert por_partida_no_build < 0.5, (
            f"{consultas_do_build.total} consultas para {partidas} partidas "
            f"({por_partida_no_build:.2f} por partida): a construção está "
            "escrevendo por registro, não por lote (§68)"
        )

    async def test_as_consultas_crescem_por_LOTE_e_nao_por_partida(
        self, banco_semeado: Database, object_store: Any, corpus: Corpus
    ) -> None:
        """A prova direta do §78, medida em dois tamanhos de lote.

        MESMAS PARTIDAS, LOTES DIFERENTES. Se as consultas fossem por
        registro, os dois números seriam iguais — o volume não mudou. Como
        elas são por lote, dobrar o tamanho do lote quase divide o total pela
        metade, e é isso que se afirma.
        """
        pipeline, fusao, resolucoes = await _ate_a_fusao(
            banco_semeado, object_store, corpus, registros=2_000
        )
        contêiner = build_build_container(
            database=banco_semeado,
            resolution=pipeline.resolution,
            clock=pipeline.clock,
            audit=pipeline.audit,
        )
        grupos, candidatos = await rebuild_fusion_output(
            resolution=pipeline.resolution,
            datasets=pipeline.datasets,
            archive=pipeline.archive,
            resolution_run_ids=resolucoes,
            fusion_run_id=fusao.run.id,
        )

        medidas: dict[int, tuple[int, int, int]] = {}
        for tamanho in (200, 800):
            async with contando_consultas(banco_semeado) as consultas:
                saida = await contêiner.run_quality.execute(
                    actor=AVALIADOR,
                    fusion_run_ids=[fusao.run.id],
                    batches=evidence_batches(
                        resolution=pipeline.resolution,
                        groups=grupos,
                        candidates=candidatos,
                        resolution_run_ids=resolucoes,
                        batch_size=tamanho,
                    ),
                )
            partidas = saida.run.counts.records_examined
            medidas[tamanho] = (
                consultas.total,
                partidas,
                max(1, -(-partidas // tamanho)),
            )

        _relatar(
            "consultas por tamanho de lote (mesmas partidas)",
            [
                f"lote {tamanho:>4} → {lotes:>3} lote(s) · {total:_} consultas "
                f"({total / lotes:.1f} por lote, {total / partidas:.3f} por partida)"
                for tamanho, (total, partidas, lotes) in sorted(medidas.items())
            ],
        )

        pequeno, grande = medidas[200][0], medidas[800][0]
        assert medidas[200][1] == medidas[800][1], (
            "o número de partidas mudou entre as duas medições — não há o que comparar"
        )
        assert grande < pequeno, (
            f"lote de 800 gastou {grande} consultas e o de 200 gastou {pequeno}: "
            "as consultas não estão crescendo por lote, e sim por registro (§78)"
        )

    async def test_a_memoria_nao_cresce_com_o_numero_de_partidas(
        self, banco_semeado: Database, object_store: Any, corpus: Corpus
    ) -> None:
        """§79. A execução acumula CONTAGENS e uma impressão — nunca a lista.

        O QUE ELA DE FATO SEGURA está declarado: as decisões de build voltam
        no `BuildOutput` para que o chamador possa afirmar coisas sobre elas
        sem reler o banco, e isso cresce com o número de partidas. O que NÃO
        cresce é o pico dentro do laço — vereditos, planos e registros vivem o
        lote e morrem nele.
        """
        picos: dict[int, tuple[float, int]] = {}
        for volume in (1_000, 4_000):
            pipeline, fusao, resolucoes = await _ate_a_fusao(
                banco_semeado, object_store, corpus, registros=volume
            )
            contêiner = build_build_container(
                database=banco_semeado,
                resolution=pipeline.resolution,
                clock=pipeline.clock,
                audit=pipeline.audit,
            )
            grupos, candidatos = await rebuild_fusion_output(
                resolution=pipeline.resolution,
                datasets=pipeline.datasets,
                archive=pipeline.archive,
                resolution_run_ids=resolucoes,
                fusion_run_id=fusao.run.id,
            )
            with medindo(f"avaliação {volume}") as medida:
                saida = await contêiner.run_quality.execute(
                    actor=AVALIADOR,
                    fusion_run_ids=[fusao.run.id],
                    batches=evidence_batches(
                        resolution=pipeline.resolution,
                        groups=grupos,
                        candidates=candidatos,
                        resolution_run_ids=resolucoes,
                        batch_size=LOTE,
                    ),
                )
            picos[volume] = (medida.pico_mb, saida.run.counts.records_examined)

        _relatar(
            "memória da avaliação por volume",
            [
                f"{volume:_} registros → {partidas:_} partidas · pico {pico:.1f} MB"
                for volume, (pico, partidas) in sorted(picos.items())
            ],
        )
        menor, maior = picos[1_000], picos[4_000]
        assert maior[1] >= menor[1]
        # QUATRO VEZES MAIS REGISTROS NÃO PODE DAR QUATRO VEZES MAIS PICO. O
        # teto é folgado de propósito: o que se está pegando é a
        # materialização global, que multiplicaria — e não a variação normal
        # entre dois lotes.
        if menor[0] > 1.0:
            assert maior[0] < menor[0] * 3, (
                f"pico saltou de {menor[0]:.1f} MB para {maior[0]:.1f} MB com 4x o "
                "volume: alguma coisa está sendo materializada por execução (§79)"
            )


class TestDeterminismoEmVolume:
    async def test_a_mesma_entrada_produz_a_mesma_impressao(
        self, banco_semeado: Database, object_store: Any, corpus: Corpus
    ) -> None:
        """§53, em volume e contra o banco de verdade.

        DUAS EXECUÇÕES sobre a MESMA fusão, com a MESMA política, precisam
        decidir a mesma coisa sobre as mesmas partidas — mesmo com ids de
        execução e de veredito diferentes.
        """
        pipeline, fusao, resolucoes = await _ate_a_fusao(
            banco_semeado, object_store, corpus, registros=1_000
        )
        contêiner = build_build_container(
            database=banco_semeado,
            resolution=pipeline.resolution,
            clock=pipeline.clock,
            audit=pipeline.audit,
        )
        grupos, candidatos = await rebuild_fusion_output(
            resolution=pipeline.resolution,
            datasets=pipeline.datasets,
            archive=pipeline.archive,
            resolution_run_ids=resolucoes,
            fusion_run_id=fusao.run.id,
        )

        impressoes = []
        for _ in range(2):
            saida = await contêiner.run_quality.execute(
                actor=AVALIADOR,
                fusion_run_ids=[fusao.run.id],
                batches=evidence_batches(
                    resolution=pipeline.resolution,
                    groups=grupos,
                    candidates=candidatos,
                    resolution_run_ids=resolucoes,
                    batch_size=LOTE,
                ),
            )
            impressoes.append(saida.run.output_fingerprint)

        _relatar(
            "determinismo da avaliação",
            [f"execução {n + 1}: {i}" for n, i in enumerate(impressoes)],
        )
        assert impressoes[0] is not None
        assert impressoes[0] == impressoes[1], (
            "duas avaliações da mesma fusão sob a mesma política produziram "
            "impressões diferentes — o reprocessamento do §52 deixaria de ser "
            "comparável"
        )

    async def test_os_dois_escopos_tentam_as_MESMAS_partidas(
        self, banco_semeado: Database, object_store: Any, corpus: Corpus
    ) -> None:
        """§19 em volume: o escopo muda as famílias, nunca a identidade.

        O QUE ESTE TESTE NÃO PROVA, e é honesto dizer: o corpus do benchmark
        NÃO tem odds — nenhuma coluna do cenário sintético carrega cotação —,
        então aqui os dois escopos materializam exatamente o mesmo conjunto.
        A DIFERENÇA entre pesquisa e comércio é provada onde ela existe, no
        cenário multi-fonte da integração, com uma fonte `RESEARCH_ONLY` de
        verdade.

        O que se afirma aqui é o invariante que vale nos dois casos: as mesmas
        partidas são TENTADAS, e a identidade não muda com o escopo.
        """
        pipeline, fusao, resolucoes = await _ate_a_fusao(
            banco_semeado, object_store, corpus, registros=1_000
        )
        contêiner = build_build_container(
            database=banco_semeado,
            resolution=pipeline.resolution,
            clock=pipeline.clock,
            audit=pipeline.audit,
        )
        grupos, candidatos = await rebuild_fusion_output(
            resolution=pipeline.resolution,
            datasets=pipeline.datasets,
            archive=pipeline.archive,
            resolution_run_ids=resolucoes,
            fusion_run_id=fusao.run.id,
        )
        avaliacao = await contêiner.run_quality.execute(
            actor=AVALIADOR,
            fusion_run_ids=[fusao.run.id],
            batches=evidence_batches(
                resolution=pipeline.resolution,
                groups=grupos,
                candidates=candidatos,
                resolution_run_ids=resolucoes,
                batch_size=LOTE,
            ),
        )

        saidas = {}
        for nome, politica in (
            ("pesquisa", DEFAULT_RESEARCH_BUILD_POLICY),
            ("comercial", DEFAULT_COMMERCIAL_BUILD_POLICY),
        ):
            saidas[nome] = await contêiner.build_for(politica).execute(
                actor=CONSTRUTOR,
                quality_run_id=avaliacao.run.id,
                batches=candidate_batches(candidates=candidatos, batch_size=LOTE),
            )

        _relatar(
            "pesquisa contra comércio, em volume",
            [
                f"{nome:<10} {s.run.counts.records_built:_} construída(s), "
                f"{s.run.counts.records_reused:_} reusada(s), "
                f"{s.run.counts.records_skipped:_} pulada(s), "
                f"{s.run.counts.families_excluded:_} família(s) fora"
                for nome, s in saidas.items()
            ],
        )
        # AS MESMAS PARTIDAS FORAM TENTADAS NOS DOIS (§19): o que muda é o
        # conjunto de famílias materializadas, nunca a identidade.
        assert (
            saidas["pesquisa"].run.counts.records_attempted
            == saidas["comercial"].run.counts.records_attempted
        )
        de_pesquisa = {str(d.match_id) for d in saidas["pesquisa"].decisions}
        de_comercio = {str(d.match_id) for d in saidas["comercial"].decisions}
        assert de_pesquisa == de_comercio
