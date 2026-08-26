"""Os casos de uso do snapshot — corpus, estado e features numa travessia só.

    corpus publicado
        ↓  (5 consultas por lote — as MESMAS do PR-05.2)
    CanonicalMatchStateInput
        ↓  EffectiveEventProjection            UMA vez
    HistoricalMatchState + ProjectionOutcome
        ↓  MatchStateFeatureExtractor
    FeatureSnapshot

A EXTRAÇÃO NÃO ACRESCENTA CONSULTA NENHUMA (§94, §179). Ela consome o que a
reconstrução de estado já carregou: os mesmos eventos, as mesmas escalações, o
mesmo resultado. Uma consulta por feature — setenta e cinco por corte, setecentas
e cinquenta mil num lote de dez mil — seria o bloqueio do §95, e o benchmark
afirma o número exato justamente para que ele não apareça por acidente.

UMA PROJEÇÃO SÓ (§5, §91). O construtor de estado devolve a projeção que usou, e
é ela que alimenta o extrator. Projetar de novo aqui criaria duas verdades
temporais sobre os mesmos eventos.

A SAÍDA EM LOTE É LIMITADA (§181). Dez mil snapshots de setenta e cinco features
cada, todos vivos numa lista, fariam o pico de memória seguir o corpus. O que
volta é contagem exata, disponibilidade agregada e uma AMOSTRA — com o aviso de
que ela é amostra.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final, final

from sports_intelligence.application.use_cases.feature_state import (
    DEFAULT_STATE_BATCH,
    AsOfFactory,
)
from sports_intelligence.domain.features.availability import (
    FeatureAvailability,
    TemporalAvailabilityPolicy,
)
from sports_intelligence.domain.features.context import CorpusSource
from sports_intelligence.domain.features.extraction.catalog import (
    ProductionFeatureCatalog,
    match_state_raw_space_v1,
    production_feature_catalog,
)
from sports_intelligence.domain.features.extraction.context import (
    MatchFeatureExtractionContext,
)
from sports_intelligence.domain.features.extraction.extractor import (
    MatchStateFeatureExtractor,
)
from sports_intelligence.domain.features.snapshot import FeatureSnapshot
from sports_intelligence.domain.features.space import FeatureSpaceDefinition
from sports_intelligence.domain.features.state.builder import (
    CanonicalMatchStateInput,
    HistoricalMatchStateBuilder,
    MatchStateBuildResult,
)
from sports_intelligence.domain.features.state.issues import StateIssue
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.shared.errors import NotFoundError
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.ports.repositories.feature_state import (
    HistoricalMatchStateSourcePort,
)

#: Quantos snapshots a saída em lote carrega de volta (§181). O mesmo padrão da
#: amostra de estado e da linhagem do corpus: o total é exato, a amostra tem
#: teto, e `sample_truncated` diz quando ela não é o conjunto.
SNAPSHOT_SAMPLE_LIMIT: Final[int] = 50


def _extrair(
    build: MatchStateBuildResult,
    *,
    space: FeatureSpaceDefinition,
    catalog: ProductionFeatureCatalog,
    source: CorpusSource,
    policy: TemporalAvailabilityPolicy,
) -> FeatureSnapshot:
    """O NÚCLEO COMPARTILHADO pelos dois casos de uso (§92, §93).

    Ele é uma função e não um método porque não guarda nada: recebe o resultado
    da reconstrução e devolve o snapshot. Duplicá-lo nos dois casos de uso
    permitiria que um deles ganhasse um passo e o outro não — e a divergência
    apareceria como «pelo lote dá outro snapshot».
    """
    contexto = MatchFeatureExtractionContext.of(
        build, space=space, catalog=catalog, source=source, policy=policy
    )
    return MatchStateFeatureExtractor().extract(contexto)


@final
@dataclass(frozen=True, slots=True)
class SnapshotBuildResult:
    """O snapshot mais o que a reconstrução do estado achou pelo caminho.

    OS PROBLEMAS DE ESTADO VIAJAM JUNTO. Um snapshot cujas features de campo
    estão indisponíveis porque a escalação não foi publicada precisa carregar
    o `LINEUP_UNAVAILABLE` — senão quem lê a máscara vê o buraco e não a causa.
    """

    snapshot: FeatureSnapshot
    state_issues: tuple[StateIssue, ...] = ()

    @property
    def is_complete(self) -> bool:
        return self.snapshot.is_complete


@final
@dataclass(frozen=True, slots=True)
class BuildHistoricalFeatureSnapshot:
    """O snapshot de UMA partida num corte (§92)."""

    source: HistoricalMatchStateSourcePort
    policy: TemporalAvailabilityPolicy
    space: FeatureSpaceDefinition = field(default_factory=match_state_raw_space_v1)
    catalog: ProductionFeatureCatalog = field(default_factory=production_feature_catalog)

    async def execute(
        self, *, source_corpus: CorpusSource, as_of: FeatureAsOf
    ) -> SnapshotBuildResult:
        insumos = await self.source.load(source_corpus.version_id, [as_of.match_id])
        entrada = insumos.get(as_of.match_id)
        if entrada is None:
            raise NotFoundError(
                f"a partida {as_of.match_id} não pertence à versão publicada "
                f"{source_corpus.version}",
                context={
                    "match_id": str(as_of.match_id),
                    "version_id": source_corpus.version_id,
                },
            )
        return self._de(entrada, as_of=as_of, source_corpus=source_corpus)

    def _de(
        self,
        entrada: CanonicalMatchStateInput,
        *,
        as_of: FeatureAsOf,
        source_corpus: CorpusSource,
    ) -> SnapshotBuildResult:
        build = HistoricalMatchStateBuilder(policy=self.policy).build(
            entrada, as_of=as_of, source=source_corpus
        )
        return SnapshotBuildResult(
            snapshot=_extrair(
                build,
                space=self.space,
                catalog=self.catalog,
                source=source_corpus,
                policy=self.policy,
            ),
            state_issues=build.issues,
        )


@final
@dataclass(frozen=True, slots=True)
class BatchSnapshotOutcome:
    """O resultado de muitos snapshots (§181).

    `snapshots` É AMOSTRA. `built` é o número exato. Apresentar a amostra como
    o conjunto seria a mentira mais fácil de cometer aqui, e a mais cara: quem
    contasse a amostra concluiria que o lote é pequeno.
    """

    built: int = 0
    complete: int = 0
    feature_values: int = 0
    available_values: int = 0
    snapshots: tuple[FeatureSnapshot, ...] = ()
    sample_truncated: bool = False
    #: Quantos VALORES ficaram indisponíveis, por motivo. É o diagnóstico que
    #: diz se o corpus não publica a família ou se o detalhe veio incompleto.
    unavailable_by_reason: dict[str, int] = field(default_factory=dict)

    @property
    def partial(self) -> int:
        return self.built - self.complete


@final
@dataclass(frozen=True, slots=True)
class BuildHistoricalFeatureSnapshots:
    """Snapshots de MUITAS partidas e MUITOS cortes, em lotes (§93, §112, §113).

    UMA LEITURA POR PARTIDA, N CORTES (§113). O corpus é carregado por partida;
    cinco cortes da mesma partida reaproveitam o MESMO insumo dentro do lote.
    Recarregar por corte multiplicaria as consultas por cinco sem trazer fato
    novo nenhum.

    O REAPROVEITAMENTO É DENTRO DA EXECUÇÃO, e não um cache (§114). Nada
    sobrevive ao fim do lote: um cache persistente precisaria de invalidação
    quando o corpus fosse republicado, e essa decisão não foi tomada.
    """

    source: HistoricalMatchStateSourcePort
    policy: TemporalAvailabilityPolicy
    space: FeatureSpaceDefinition = field(default_factory=match_state_raw_space_v1)
    catalog: ProductionFeatureCatalog = field(default_factory=production_feature_catalog)
    batch_size: int = DEFAULT_STATE_BATCH
    sample_limit: int = SNAPSHOT_SAMPLE_LIMIT

    async def execute(
        self,
        *,
        source_corpus: CorpusSource,
        match_ids: Sequence[MatchId],
        as_of_of: AsOfFactory,
    ) -> BatchSnapshotOutcome:
        construtor = HistoricalMatchStateBuilder(policy=self.policy)
        extrator = MatchStateFeatureExtractor()
        construidos = completos = valores = disponiveis = 0
        amostra: list[FeatureSnapshot] = []
        motivos: dict[str, int] = {}

        for inicio in range(0, len(match_ids), self.batch_size):
            lote = list(match_ids[inicio : inicio + self.batch_size])
            insumos = await self.source.load(source_corpus.version_id, lote)
            for partida in lote:
                entrada = insumos.get(partida)
                if entrada is None:
                    continue
                for corte in as_of_of(partida):
                    build = construtor.build(entrada, as_of=corte, source=source_corpus)
                    contexto = MatchFeatureExtractionContext.of(
                        build,
                        space=self.space,
                        catalog=self.catalog,
                        source=source_corpus,
                        policy=self.policy,
                    )
                    snapshot = extrator.extract(contexto)
                    construidos += 1
                    valores += len(snapshot.features)
                    mascara = snapshot.mask
                    disponiveis += mascara.available_count
                    if mascara.is_complete:
                        completos += 1
                    for estado in mascara.states:
                        if estado is not FeatureAvailability.AVAILABLE:
                            motivos[estado.value] = motivos.get(estado.value, 0) + 1
                    if len(amostra) < self.sample_limit:
                        amostra.append(snapshot)

        return BatchSnapshotOutcome(
            built=construidos,
            complete=completos,
            feature_values=valores,
            available_values=disponiveis,
            snapshots=tuple(amostra),
            sample_truncated=construidos > len(amostra),
            unavailable_by_reason=dict(sorted(motivos.items())),
        )
