"""O caso de uso do snapshot ESTENDIDO — corpus, estado, contexto e mercado.

    corpus publicado
        ↓  5 consultas por lote (estado) + 2 por lote (contexto)
    insumos de estado + contexto pré-jogo
        ↓  EffectiveEventProjection            UMA vez
    HistoricalMatchState + ProjectionOutcome
        ↓  ExtendedMatchStateFeatureExtractor
    FeatureSnapshot MATCH_STATE_RAW_V2

O CONTEXTO ACRESCENTA DUAS CONSULTAS POR LOTE (§178), e não uma por partida: a
janela e a última anterior, as duas orientadas a conjunto. O MERCADO acrescenta
ZERO (§179) — ele sai do `OddsState` que a reconstrução de estado já produziu.

A COBERTURA É LIDA UMA VEZ POR EXECUÇÃO (§32). Ela é propriedade da versão, e
repeti-la por lote seria pagar vinte vezes por uma resposta que não muda.

O CONTEXTO É O MESMO PARA TODOS OS CORTES DA MESMA PARTIDA (§22, §159). Ele é
carregado uma vez por partida e reaproveitado nos cinco cortes — recarregá-lo
por corte multiplicaria as consultas sem trazer fato novo.
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
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.shared.errors import NotFoundError
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.ports.repositories.feature_context import (
    HistoricalContextSourcePort,
)
from sports_intelligence.ports.repositories.feature_state import (
    HistoricalMatchStateSourcePort,
)

#: Quantos snapshots a saída em lote carrega de volta. O mesmo padrão da V1.
SNAPSHOT_SAMPLE_LIMIT_V2: Final[int] = 50


@final
@dataclass(frozen=True, slots=True)
class ExtendedSnapshotOutcome:
    """O resultado de muitos snapshots V2 — contagem exata, amostra limitada."""

    built: int = 0
    complete: int = 0
    feature_values: int = 0
    available_values: int = 0
    snapshots: tuple[FeatureSnapshot, ...] = ()
    sample_truncated: bool = False
    unavailable_by_reason: dict[str, int] = field(default_factory=dict)

    @property
    def partial(self) -> int:
        return self.built - self.complete


@final
@dataclass(frozen=True, slots=True)
class BuildExtendedFeatureSnapshot:
    """O snapshot V2 de UMA partida num corte (§155)."""

    state_source: HistoricalMatchStateSourcePort
    context_source: HistoricalContextSourcePort
    policy: TemporalAvailabilityPolicy
    context_policy: HistoricalContextPolicy = DEFAULT_CONTEXT_POLICY
    market_policy: MarketConsensusPolicy = field(default_factory=MarketConsensusPolicy)
    space: FeatureSpaceDefinition = field(default_factory=match_state_raw_space_v2)
    catalog: ExtendedFeatureCatalog = field(default_factory=extended_feature_catalog)
    v1_space: FeatureSpaceDefinition = field(default_factory=match_state_raw_space_v1)

    async def execute(self, *, source_corpus: CorpusSource, as_of: FeatureAsOf) -> FeatureSnapshot:
        insumos = await self.state_source.load(source_corpus.version_id, [as_of.match_id])
        entrada = insumos.get(as_of.match_id)
        if entrada is None:
            raise NotFoundError(
                f"a partida {as_of.match_id} não pertence à versão publicada "
                f"{source_corpus.version}",
                context={"match_id": str(as_of.match_id)},
            )
        contextos = await self.context_source.load(
            source_corpus.version_id, [as_of.match_id], policy=self.context_policy
        )
        build = HistoricalMatchStateBuilder(policy=self.policy).build(
            entrada, as_of=as_of, source=source_corpus
        )
        return ExtendedMatchStateFeatureExtractor().extract(
            ExtendedFeatureExtractionContext.of(
                build,
                space=self.space,
                catalog=self.catalog,
                source=source_corpus,
                policy=self.policy,
                v1_space=self.v1_space,
                context_policy=self.context_policy,
                market_policy=self.market_policy,
                context=contextos.get(as_of.match_id),
            )
        )


@final
@dataclass(frozen=True, slots=True)
class BuildExtendedFeatureSnapshots:
    """Snapshots V2 de MUITAS partidas e MUITOS cortes, em lotes (§155).

    O CONTEXTO É CARREGADO POR PARTIDA E REUSADO POR CORTE (§159). Ele não
    depende do `FeatureAsOf`: descreve o que havia antes do apito.
    """

    state_source: HistoricalMatchStateSourcePort
    context_source: HistoricalContextSourcePort
    policy: TemporalAvailabilityPolicy
    context_policy: HistoricalContextPolicy = DEFAULT_CONTEXT_POLICY
    market_policy: MarketConsensusPolicy = field(default_factory=MarketConsensusPolicy)
    space: FeatureSpaceDefinition = field(default_factory=match_state_raw_space_v2)
    catalog: ExtendedFeatureCatalog = field(default_factory=extended_feature_catalog)
    v1_space: FeatureSpaceDefinition = field(default_factory=match_state_raw_space_v1)
    batch_size: int = DEFAULT_STATE_BATCH
    sample_limit: int = SNAPSHOT_SAMPLE_LIMIT_V2

    async def execute(
        self,
        *,
        source_corpus: CorpusSource,
        match_ids: Sequence[MatchId],
        as_of_of: AsOfFactory,
    ) -> ExtendedSnapshotOutcome:
        construtor = HistoricalMatchStateBuilder(policy=self.policy)
        extrator = ExtendedMatchStateFeatureExtractor()
        construidos = completos = valores = disponiveis = 0
        amostra: list[FeatureSnapshot] = []
        motivos: dict[str, int] = {}

        for inicio in range(0, len(match_ids), self.batch_size):
            lote = list(match_ids[inicio : inicio + self.batch_size])
            insumos = await self.state_source.load(source_corpus.version_id, lote)
            contextos = await self.context_source.load(
                source_corpus.version_id, lote, policy=self.context_policy
            )
            for partida in lote:
                entrada = insumos.get(partida)
                if entrada is None:
                    continue
                contexto_da_partida = contextos.get(partida)
                for corte in as_of_of(partida):
                    build = construtor.build(entrada, as_of=corte, source=source_corpus)
                    snapshot = extrator.extract(
                        ExtendedFeatureExtractionContext.of(
                            build,
                            space=self.space,
                            catalog=self.catalog,
                            source=source_corpus,
                            policy=self.policy,
                            v1_space=self.v1_space,
                            context_policy=self.context_policy,
                            market_policy=self.market_policy,
                            context=contexto_da_partida,
                        )
                    )
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

        return ExtendedSnapshotOutcome(
            built=construidos,
            complete=completos,
            feature_values=valores,
            available_values=disponiveis,
            snapshots=tuple(amostra),
            sample_truncated=construidos > len(amostra),
            unavailable_by_reason=dict(sorted(motivos.items())),
        )
