"""O contrato de entrada da extração — e as quatro conferências que ele faz.

O DEFEITO QUE ELE EXISTE PARA IMPEDIR (§6, §7). A extração combina três
artefatos: o estado, a projeção efetiva e o espaço de features. Os três vêm de
lugares diferentes, e nada na assinatura de uma função impediria alguém de
passar o estado dos 63 minutos junto com a projeção dos 70 — os dois são
objetos válidos, o cálculo terminaria, e o snapshot descreveria um jogo que
nunca existiu.

A conferência é boba de fazer e cara de não fazer:

    mesma partida            estado e projeção da mesma `match_id`
    mesmo corte              o mesmo `FeatureAsOf`, incluindo modo e
                             conhecimento
    mesmo corpus             a mesma versão publicada, com a mesma impressão
    mesma política temporal  a mesma causalidade sob a qual tudo foi decidido

UMA PROJEÇÃO SÓ (§5, §91). A projeção não é recalculada aqui: ela CHEGA
pronta, vinda do mesmo `MatchStateBuildResult` que produziu o estado. Um
contexto que aceitasse eventos canônicos e projetasse por conta própria criaria
a segunda projeção que o §5 proíbe — e as duas concordariam em tudo menos no
caso difícil.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self, final

from sports_intelligence.domain.features.availability import TemporalAvailabilityPolicy
from sports_intelligence.domain.features.context import CorpusSource
from sports_intelligence.domain.features.extraction.catalog import (
    ProductionFeatureCatalog,
)
from sports_intelligence.domain.features.projection import ProjectionOutcome
from sports_intelligence.domain.features.space import FeatureSpaceDefinition
from sports_intelligence.domain.features.state.builder import MatchStateBuildResult
from sports_intelligence.domain.features.state.match_state import HistoricalMatchState
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.shared.errors import ValidationError


@final
@dataclass(frozen=True, slots=True)
class MatchFeatureExtractionContext:
    """Tudo que a extração precisa, com as identidades já conferidas (§6).

    `as_of`, `source` E `policy` NÃO SÃO REDUNDANTES com o estado. Eles são a
    afirmação de sob que condições ESTA extração acontece, e o construtor
    confere que o estado concorda. Sem a afirmação explícita, a conferência não
    teria contra o que conferir.
    """

    state: HistoricalMatchState
    #: A projeção EFETIVA — a mesma que produziu o estado (§5, §91).
    effective_events: ProjectionOutcome
    space: FeatureSpaceDefinition
    catalog: ProductionFeatureCatalog
    as_of: FeatureAsOf
    source: CorpusSource
    policy: TemporalAvailabilityPolicy

    def __post_init__(self) -> None:
        if self.state.identity.match_id != self.as_of.match_id:
            raise ValidationError(
                f"o estado é da partida {self.state.identity.match_id} e o corte é de "
                f"{self.as_of.match_id}",
                context={"state": str(self.state.identity.match_id)},
            )
        if self.state.as_of != self.as_of:
            # OS DOIS CORTES PRECISAM SER O MESMO OBJETO SEMÂNTICO (§7).
            # Posição, modo e corte de conhecimento: um estado `AS_KNOWN` com
            # uma extração `CANONICAL_FINAL` combinaria duas causalidades.
            raise ValidationError(
                f"o estado foi reconstruído em {self.state.as_of} e a extração "
                f"declara {self.as_of} — são cortes semanticamente diferentes",
                context={"state_as_of": str(self.state.as_of)},
            )
        if self.state.source != self.source:
            raise ValidationError(
                f"o estado veio do corpus {self.state.source} e a extração declara "
                f"{self.source}: combinar os dois produziria um snapshot que nenhuma "
                "versão publicada sustenta",
                context={"state_source": str(self.state.source)},
            )
        if self.state.policy_fingerprint != self.policy.fingerprint:
            raise ValidationError(
                f"o estado foi reconstruído sob a política "
                f"{self.state.policy_fingerprint[:12]} e a extração declara "
                f"{self.policy.fingerprint[:12]}",
                context={"state_policy": self.state.policy_fingerprint},
            )
        for projetado in self.effective_events.events:
            if projetado.event.match_id != self.as_of.match_id:
                raise ValidationError(
                    f"a projeção traz o evento {projetado.id} da partida "
                    f"{projetado.event.match_id}, e a extração é de "
                    f"{self.as_of.match_id}"
                )
        if self.space.keys != tuple(s.definition.key for s in self.catalog.specs):
            raise ValidationError(
                f"o espaço {self.space.name} e o catálogo declaram conjuntos ou "
                "ordens diferentes de features — o extrator usa o catálogo para "
                "saber O QUE calcular e o espaço para saber EM QUE ORDEM, e os dois "
                "precisam descrever a mesma coisa"
            )

    @classmethod
    def of(
        cls,
        build: MatchStateBuildResult,
        *,
        space: FeatureSpaceDefinition,
        catalog: ProductionFeatureCatalog,
        source: CorpusSource,
        policy: TemporalAvailabilityPolicy,
    ) -> Self:
        """O contexto a partir do resultado da reconstrução (§5, §90, §91).

        ESTA É A PORTA CERTA, e ela é a única que garante a projeção única: o
        `MatchStateBuildResult` carrega o estado E a projeção que o produziu,
        e por isso não há como montar um contexto com uma projeção diferente
        da que o estado usou.
        """
        return cls(
            state=build.state,
            effective_events=build.projection,
            space=space,
            catalog=catalog,
            as_of=build.state.as_of,
            source=source,
            policy=policy,
        )

    @property
    def publishes_events(self) -> bool:
        from sports_intelligence.domain.quality.coverage import CoverageFamily

        return CoverageFamily.EVENT in self.source.published_families

    def __str__(self) -> str:
        return (
            f"extração {self.as_of} · {self.effective_events.size} evento(s) "
            f"efetivo(s) · {self.space.identity}"
        )
