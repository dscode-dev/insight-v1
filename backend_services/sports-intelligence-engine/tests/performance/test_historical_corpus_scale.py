"""O BENCHMARK OFICIAL DO PR-04: 10.000 partidas do bruto ao corpus publicado.

O QUE ELE MEDE, e por que cada número está aqui (§90, §91):

    tempo por etapa        composição, materialização, publicação
    consultas por lote     o N+1 não aparece no perfil, aparece no total
    pico de memória        a prova de que o corpus não é materializado inteiro
    tamanho dos objetos    quanto o Parquet de fato custa em disco

O CRITÉRIO É O CRESCIMENTO E NÃO UM NÚMERO ABSOLUTO. Uma máquina mais lenta
muda os segundos e não muda a forma da curva; o que reprovaria é a composição
consultar por PARTIDA em vez de por LOTE, e essa diferença é grande demais
para ser ruído.

O PICO DE MEMÓRIA É A AFIRMAÇÃO MAIS FORTE DAQUI. O acumulador guarda
contadores e uma impressão de 32 bytes; os fatos de cada lote são gravados e
descartados. Se o pico crescesse com o número de partidas, `page_facts` estaria
sendo consumido para dentro de uma lista, que é o defeito que o PR-03.2 já
corrigiu uma vez pela mesma porta.

ELE NÃO PUBLICA UM CORPUS «DE MENTIRA». Passa pelo intake, pela resolução, pela
fusão, pela qualidade, pelo build e pela publicação — com PostgreSQL e object
store reais. Um benchmark que atalha o caminho mede o atalho.
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
from apps.corpus_composition import build_corpus_container
from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.build.policy import (
    CANONICAL_BUILDER,
    DEFAULT_RESEARCH_BUILD_POLICY,
)
from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.corpus.scope import CorpusScope, ScopeEntry
from sports_intelligence.domain.corpus.versions import (
    CORPUS_PUBLISHER,
    DatasetVersionStatus,
    VersionInputs,
)
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.quality.runs import QUALITY_ASSESSOR
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.identity import ProviderId
from sports_intelligence.domain.shared.versioning import DatasetVersion
from tests.performance.test_resolution_100k import CAMPOS, _relatar
from tests.support.corpus import Corpus, csv_bytes
from tests.support.instrumentation import contando_consultas, medindo
from tests.support.pipeline import Pipeline

pytestmark = [pytest.mark.performance, pytest.mark.integration]

#: Registros lidos da fonte. O número de PARTIDAS é CONSEQUÊNCIA da resolução,
#: e não um parâmetro: o corpus sintético distribui os registros entre caminhos
#: de casamento diferentes, e os que não resolvem não chegam ao corpus. A razão
#: medida é de 0,8 partida por registro, então 12.500 registros são o que
#: entrega as DEZ MIL partidas que o §90 exige — e o teste afirma o piso em vez
#: de confiar na razão.
REGISTROS = 12_500

#: O piso do §90. Ele é afirmado: um benchmark que medisse 6.000 partidas e
#: dissesse «dez mil» seria pior que nenhum.
PARTIDAS_MINIMAS = 10_000

#: O lote da composição. É o eixo: as consultas crescem com o número de LOTES.
LOTE = 500

AVALIADOR = Actor.service(QUALITY_ASSESSOR)
CONSTRUTOR = Actor.service(CANONICAL_BUILDER)
PUBLICADOR = Actor.service(CORPUS_PUBLISHER)


async def _ate_o_build(
    banco: Database, object_store: Any, corpus: Corpus, *, registros: int
) -> dict[str, Any]:
    """Todo o caminho anterior a este PR, com adapters reais."""
    if hasattr(object_store, "ensure_bucket"):
        await object_store.ensure_bucket()
    pipeline = Pipeline(banco, object_store, batch_size=1_000)
    provedor = ProviderId(f"pr043_perf_{registros}")
    dataset = await pipeline.stage(
        name=f"pr043-perf-{registros}",
        content=csv_bytes(corpus, total=registros),
        provider=provedor,
    )
    await pipeline.map_source(dataset, provider=provedor, fields=CAMPOS)
    resolucao = await pipeline.resolve(dataset.id)
    fusao = await pipeline.fuse([resolucao.run.id])

    contêiner = build_build_container(
        database=banco,
        resolution=pipeline.resolution,
        clock=pipeline.clock,
        audit=pipeline.audit,
    )
    grupos, candidatos = await rebuild_fusion_output(
        resolution=pipeline.resolution,
        datasets=pipeline.datasets,
        archive=pipeline.archive,
        resolution_run_ids=[resolucao.run.id],
        fusion_run_id=fusao.run.id,
    )
    qualidade = await contêiner.run_quality.execute(
        actor=AVALIADOR,
        fusion_run_ids=[fusao.run.id],
        batches=evidence_batches(
            resolution=pipeline.resolution,
            groups=grupos,
            candidates=candidatos,
            resolution_run_ids=[resolucao.run.id],
            batch_size=LOTE,
        ),
    )
    build = await contêiner.build_for(DEFAULT_RESEARCH_BUILD_POLICY).execute(
        actor=CONSTRUTOR,
        quality_run_id=qualidade.run.id,
        batches=candidate_batches(candidates=candidatos, batch_size=LOTE),
    )
    return {
        "pipeline": pipeline,
        "quality_run": qualidade.run,
        "build_run": build.run,
        "resolution_run_ids": [resolucao.run.id],
        "fusion_run_id": fusao.run.id,
    }


def _escopo(corpus: Corpus) -> CorpusScope:
    """O escopo REAL do corpus sintético — todas as (competição, temporada).

    ELE É DECLARADO E NÃO DESCOBERTO (§65), inclusive aqui: o benchmark lista
    o que espera publicar, e a composição recusa qualquer partida fora disso.
    Um escopo derivado do que voltou do banco não provaria nada — ele
    concordaria com o resultado por construção.
    """
    entradas = tuple(
        ScopeEntry(
            competition=CompetitionCode(temporada_competicao(corpus, temporada.id)),
            season_label=temporada.label,
            competition_id=temporada.competition_id,
            season_id=temporada.id,
        )
        for temporada in corpus.seasons
    )
    return CorpusScope.of(*entradas, usage=UsageScope.RESEARCH)


def temporada_competicao(corpus: Corpus, season_id: Any) -> str:
    temporada = next(s for s in corpus.seasons if s.id == season_id)
    return next(c.code.value for c in corpus.competitions if c.id == temporada.competition_id)


class TestCorpusEmVolume:
    async def test_dez_mil_partidas_do_bruto_ao_corpus_publicado(
        self, banco_semeado: Database, object_store: Any, corpus: Corpus
    ) -> None:
        anterior = await _ate_o_build(banco_semeado, object_store, corpus, registros=REGISTROS)
        pipeline: Pipeline = anterior["pipeline"]
        contêiner = build_corpus_container(
            database=banco_semeado,
            clock=pipeline.clock,
            audit=pipeline.audit,
            store=object_store,
            batch_size=LOTE,
        )
        dataset = await contêiner.create_dataset.execute(
            actor=PUBLICADOR, name=f"perf-corpus-{REGISTROS}"
        )
        entradas = VersionInputs(
            build_run_ids=(anterior["build_run"].id,),
            quality_run_ids=(anterior["quality_run"].id,),
            build_output_fingerprints=(
                ()
                if anterior["build_run"].output_fingerprint is None
                else (anterior["build_run"].output_fingerprint,)
            ),
            fusion_run_ids=(anterior["fusion_run_id"],),
            resolution_run_ids=tuple(anterior["resolution_run_ids"]),
        )

        async with contando_consultas(banco_semeado) as consultas_da_composicao:
            with medindo("composição do corpus") as composicao:
                saida = await contêiner.build_version.execute(
                    actor=PUBLICADOR,
                    dataset_id=dataset.id,
                    version=DatasetVersion(major=1, minor=0),
                    scope=_escopo(corpus),
                    inputs=entradas,
                    quality_run_id=anterior["quality_run"].id,
                )

        async with contando_consultas(banco_semeado) as consultas_da_publicacao:
            with medindo("publicação") as publicacao:
                versao = await contêiner.publish_version.execute(
                    actor=PUBLICADOR,
                    version_id=saida.version.id,
                    reason=f"benchmark PR-04.3 · {REGISTROS} registros",
                )

        partidas = saida.members_written
        lotes = max(1, -(-partidas // LOTE))
        bytes_escritos = sum(o.size_bytes for o in saida.manifest.objects)
        linhas_escritas = sum(o.row_count for o in saida.manifest.objects)

        _relatar(
            f"PR-04.3 · {REGISTROS:_} registros → {partidas:_} partidas no corpus",
            [
                f"composição       {composicao.segundos:.1f}s · "
                f"{composicao.por_segundo(max(partidas, 1)):.0f} partidas/s · "
                f"pico {composicao.pico_mb:.0f} MB",
                f"publicação       {publicacao.segundos:.1f}s · pico {publicacao.pico_mb:.0f} MB",
                "",
                f"partidas         {partidas:_} em {lotes} lote(s) de {LOTE}",
                f"objetos          {len(saida.manifest.objects):_} arquivo(s)",
                f"linhas           {linhas_escritas:_}",
                f"bytes            {bytes_escritos / 1_048_576:.1f} MB "
                f"({bytes_escritos / max(partidas, 1):.0f} B/partida)",
                "",
                f"consultas comp.  {consultas_da_composicao.total:_} "
                f"({consultas_da_composicao.total / lotes:.1f} por lote) · "
                f"{consultas_da_composicao.mais_frequentes}",
                f"consultas publ.  {consultas_da_publicacao.total:_}",
                "",
                f"impressão        {versao.corpus_fingerprint}",
                f"manifesto        {saida.manifest.manifest_sha256}",
                f"estado           {versao.status.value}",
            ],
        )

        assert partidas >= PARTIDAS_MINIMAS, (
            f"o benchmark compôs {partidas} partidas, abaixo das "
            f"{PARTIDAS_MINIMAS} que o §90 exige — o número medido descreveria "
            "um corpus menor que o declarado"
        )
        assert versao.status is DatasetVersionStatus.READY

        # O CRITÉRIO DO §68, aplicado à leitura: as consultas por PARTIDA
        # precisam ser uma fração pequena. Com N+1 seriam >= 1 por partida.
        por_partida = consultas_da_composicao.total / partidas
        assert por_partida < 0.5, (
            f"{consultas_da_composicao.total} consultas para {partidas} partidas "
            f"({por_partida:.2f} por partida): a composição está lendo por "
            "registro, não por lote (§86)"
        )

        # A PUBLICAÇÃO É BARATA E TEM DE CONTINUAR SENDO. Ela confere contagem
        # e impressão e grava a transição — um número que cresça com o corpus
        # significaria que o gate passou a varrê-lo.
        assert consultas_da_publicacao.total < 20, (
            f"{consultas_da_publicacao.total} consultas para publicar: o gate "
            "está varrendo o corpus em vez de conferi-lo por agregação (§67)"
        )

    async def test_a_memoria_nao_cresce_com_o_tamanho_do_corpus(
        self, banco_semeado: Database, object_store: Any, corpus: Corpus
    ) -> None:
        """§86 medido: dobrar as partidas não pode dobrar o pico.

        É A AFIRMAÇÃO MAIS FORTE DESTE ARQUIVO, e a mais fácil de perder: um
        `list(page_facts(...))` em qualquer ponto satisfaz todos os testes
        funcionais e transforma o pico em função do corpus.
        """
        picos: dict[int, float] = {}
        impressoes: dict[int, str] = {}
        for registros in (2_000, 8_000):
            anterior = await _ate_o_build(banco_semeado, object_store, corpus, registros=registros)
            pipeline: Pipeline = anterior["pipeline"]
            contêiner = build_corpus_container(
                database=banco_semeado,
                clock=pipeline.clock,
                audit=pipeline.audit,
                store=None,  # sem Parquet: o que se mede aqui é a composição
                batch_size=LOTE,
            )
            dataset = await contêiner.create_dataset.execute(
                actor=PUBLICADOR, name=f"perf-memoria-{registros}"
            )
            with medindo(f"composição de {registros}") as medida:
                saida = await contêiner.build_version.execute(
                    actor=PUBLICADOR,
                    dataset_id=dataset.id,
                    version=DatasetVersion(major=1, minor=0),
                    scope=_escopo(corpus),
                    inputs=VersionInputs(
                        build_run_ids=(anterior["build_run"].id,),
                        quality_run_ids=(anterior["quality_run"].id,),
                    ),
                    quality_run_id=anterior["quality_run"].id,
                )
            picos[registros] = medida.pico_mb
            impressoes[registros] = str(saida.manifest.corpus_fingerprint)

        _relatar(
            "PR-04.3 · memória contra tamanho",
            [f"{n:_} registros → pico {p:.1f} MB" for n, p in picos.items()],
        )

        pequeno, grande = picos[2_000], picos[8_000]
        assert grande < pequeno * 2.5, (
            f"pico de {grande:.1f} MB para 8.000 registros contra {pequeno:.1f} MB "
            "para 2.000: quadruplicar o volume mais que dobrou a memória, o que "
            "significa que a composição está acumulando os fatos em vez de "
            "descartá-los por lote (§86)"
        )

    async def test_a_impressao_e_a_mesma_em_duas_composicoes(
        self, banco_semeado: Database, object_store: Any, corpus: Corpus
    ) -> None:
        """§89 em volume: duas publicações independentes dos MESMOS fatos.

        Em escala isto é mais forte que no teste de unidade: aqui os lotes
        vêm do banco, em ordem de chave, e a impressão comutativa é o que
        garante que a partição em lotes não vaze para o resultado.
        """
        anterior = await _ate_o_build(banco_semeado, object_store, corpus, registros=4_000)
        pipeline: Pipeline = anterior["pipeline"]
        entradas = VersionInputs(
            build_run_ids=(anterior["build_run"].id,),
            quality_run_ids=(anterior["quality_run"].id,),
        )
        impressoes: list[str] = []
        for lote in (250, 2_000):
            contêiner = build_corpus_container(
                database=banco_semeado,
                clock=pipeline.clock,
                audit=pipeline.audit,
                store=None,
                batch_size=lote,
            )
            dataset = await contêiner.create_dataset.execute(
                actor=PUBLICADOR, name="perf-determinismo"
            )
            saida = await contêiner.build_version.execute(
                actor=PUBLICADOR,
                dataset_id=dataset.id,
                version=DatasetVersion(major=1, minor=0),
                scope=_escopo(corpus),
                inputs=entradas,
                quality_run_id=anterior["quality_run"].id,
            )
            impressoes.append(saida.manifest.corpus_fingerprint.value)
            # A MESMA IDENTIDADE nas duas composições: nome e versão entram na
            # impressão (§30), então reusar `1.0` é o que torna a comparação
            # sobre o LOTE e não sobre o nome.
            async with banco_semeado.acquire() as conexao:
                import uuid as _uuid

                await conexao.execute(
                    "DELETE FROM historical_canonical_dataset_versions WHERE id = $1",
                    _uuid.UUID(saida.version.id),
                )

        _relatar(
            "PR-04.3 · determinismo em volume",
            [
                f"lote 250    {impressoes[0]}",
                f"lote 2.000  {impressoes[1]}",
                f"iguais      {impressoes[0] == impressoes[1]}",
            ],
        )
        assert impressoes[0] == impressoes[1], (
            "o tamanho do lote mudou a impressão do corpus: ela deixou de "
            "provar reprodutibilidade (§88)"
        )
