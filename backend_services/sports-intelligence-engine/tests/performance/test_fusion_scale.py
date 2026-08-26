"""A fusão em volume, sobre o que a resolução de verdade produziu.

DERIVADA DO MESMO CENÁRIO (§13), e não de registros montados à mão. Um
benchmark de fusão que construísse `ResolvedSourceRecord` diretamente pularia
justamente a parte cara — a leitura, a resolução e o `resolved_entities_of_run`
que liga decisão a linha — e mediria o motor de fusão em isolamento, que é a
parte barata.

Aqui as três fontes atravessam resolução real contra PostgreSQL real, e o que
entra na fusão é o que sobreviveu: só registros com identidade PROVADA
(ADR-0022). O número de grupos é, portanto, uma consequência da resolução —
não um parâmetro do teste.
"""

from __future__ import annotations

from typing import Any

import pytest

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.shared.identity import ProviderId
from tests.performance.test_resolution_100k import CAMPOS, _relatar
from tests.support.corpus import Corpus, csv_bytes
from tests.support.instrumentation import contando_consultas, medindo
from tests.support.pipeline import Pipeline

pytestmark = [pytest.mark.performance, pytest.mark.integration]

#: Registros POR FONTE. Três fontes dão o triplo de registros e uma vez o
#: número de grupos — que é a proporção real de um corpus multi-fonte.
POR_FONTE = 15_000

FONTES: tuple[tuple[str, int], ...] = (
    ("fonte_a", 0),
    ("fonte_b", 2),
    ("fonte_c", 5),
)


class TestFusaoEmVolume:
    async def test_tres_fontes_sobre_o_mesmo_calendario(
        self, banco_semeado: Database, object_store: Any, corpus: Corpus
    ) -> None:
        if hasattr(object_store, "ensure_bucket"):
            await object_store.ensure_bucket()

        execucoes: list[str] = []
        pipeline = Pipeline(banco_semeado, object_store, batch_size=1_000)
        with medindo("resolução das três fontes") as resolucao:
            for nome, desvio in FONTES:
                provedor = ProviderId(nome)
                dataset = await pipeline.stage(
                    name=f"fusao-{nome}",
                    content=csv_bytes(corpus, total=POR_FONTE, shots_offset=desvio),
                    provider=provedor,
                )
                await pipeline.map_source(dataset, provider=provedor, fields=CAMPOS)
                saida = await pipeline.resolve(dataset.id)
                execucoes.append(saida.run.id)

        # A LEITURA DOS REGISTROS RESOLVIDOS É MEDIDA À PARTE. Ela relê os
        # três arquivos e cruza com as decisões; é trabalho de borda, e
        # somá-la ao motor de fusão esconderia qual dos dois domina.
        with medindo("releitura + filtro por decisão") as releitura:
            registros = await pipeline.resolved_records(execucoes)

        async with contando_consultas(banco_semeado) as consultas:
            with medindo("fusão") as fusao:
                saida_da_fusao = await pipeline.fuse(execucoes, records=registros)

        contagens = saida_da_fusao.run.counts
        candidatos = saida_da_fusao.candidates
        campos = sum(len(c.fields) for c in candidatos)
        observacoes = sum(len(o.observations) for c in candidatos for o in c.observation_sets)

        _relatar(
            f"fusão · {len(FONTES)} fontes x {POR_FONTE:_} registros",
            [
                f"resolução        {resolucao.segundos:.1f}s "
                f"({resolucao.por_segundo(POR_FONTE * len(FONTES)):.0f} reg/s)",
                f"releitura        {releitura.segundos:.1f}s · "
                f"{len(registros):_} registros com identidade provada",
                f"fusão            {fusao.segundos:.1f}s · "
                f"{fusao.por_segundo(max(contagens.groups, 1)):.0f} grupos/s · "
                f"pico {fusao.pico_mb:.0f} MB",
                "",
                f"grupos           {contagens.groups:_}",
                f"candidatos       {len(candidatos):_}",
                f"descartados      {saida_da_fusao.discarded:_} (duplicata interna de uma fonte)",
                f"campos           {campos:_} ({campos / fusao.segundos:.0f} campos/s)",
                f"observações      {observacoes:_} em {contagens.observation_sets:_} conjuntos",
                "",
                f"grupos multi     {contagens.multi_source_groups:_}",
                f"campos escolhidos {contagens.fields_selected:_}",
                f"conflitos        {contagens.conflicts:_}",
                f"não resolvidos   {contagens.unresolved_conflicts:_}",
                "",
                f"consultas        {consultas.total:_} · {consultas.mais_frequentes}",
                f"impressão        {saida_da_fusao.run.output_fingerprint}",
            ],
        )

        assert contagens.groups > 0, "nenhum grupo: a resolução não entregou nada à fusão"
        # TRÊS FONTES SOBRE O MESMO CALENDÁRIO PRODUZEM UM GRUPO POR PARTIDA,
        # não três. Se o número de grupos batesse com o de registros, o
        # agrupamento por identidade não estaria agrupando nada.
        assert contagens.groups < len(registros)
        # E o conflito precisa EXISTIR: as fontes divergem nos chutes por
        # construção. Zero conflitos significaria que a divergência sumiu —
        # que é o defeito que a fusão inteira existe para não cometer.
        assert contagens.conflicts > 0, (
            "as fontes divergem nos chutes e a fusão não viu conflito nenhum"
        )

    async def test_a_fusao_nao_cresce_em_memoria_com_o_numero_de_grupos(
        self, banco_semeado: Database, object_store: Any, corpus: Corpus
    ) -> None:
        """O que a fusão carrega junto, e o que isso custa (§37).

        A FUSÃO É A ETAPA QUE MAIS SEGURA COISA EM MEMÓRIA, e é honesto dizer:
        `RunFusion` recebe a sequência inteira de registros resolvidos e monta
        todos os grupos antes de gravar. Isso é uma escolha do PR-03 — os
        grupos precisam estar completos para que a concordância seja contada
        sobre TODAS as fontes —, e o custo cresce com o volume.

        O que este teste mede é QUANTO, para que a conta apareça no documento
        de baseline em vez de aparecer num incidente.
        """
        if hasattr(object_store, "ensure_bucket"):
            await object_store.ensure_bucket()

        picos: dict[int, tuple[float, int]] = {}
        for volume in (2_000, 10_000):
            pipeline = Pipeline(banco_semeado, object_store, batch_size=1_000)
            execucoes = []
            for nome, desvio in FONTES[:2]:
                provedor = ProviderId(f"{nome}_m{volume}")
                dataset = await pipeline.stage(
                    name=f"fusao-memoria-{nome}-{volume}",
                    content=csv_bytes(corpus, total=volume, shots_offset=desvio),
                    provider=provedor,
                )
                await pipeline.map_source(dataset, provider=provedor, fields=CAMPOS)
                execucoes.append((await pipeline.resolve(dataset.id)).run.id)

            registros = await pipeline.resolved_records(execucoes)
            with medindo(f"fusão {volume}") as medida:
                saida = await pipeline.fuse(execucoes, records=registros)
            picos[volume] = (medida.pico_mb, saida.run.counts.groups)

        _relatar(
            "memória da fusão por volume",
            [
                f"{volume:_} registros/fonte → {grupos:_} grupos · pico {pico:.1f} MB"
                for volume, (pico, grupos) in sorted(picos.items())
            ],
        )
        assert picos[10_000][1] > picos[2_000][1]
