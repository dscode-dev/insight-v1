"""O extrator estendido — as 75 da V1 reusadas, mais contexto e mercado.

    FeatureSnapshot_V2 = V1(estado, fatos efetivos) ‖ Contexto(passado) ‖ Mercado(odds)

AS SETENTA E CINCO PRIMEIRAS SÃO CALCULADAS PELO EXTRATOR DA V1 (§156, §157).
Não há cópia: este módulo monta um contexto de extração da V1 — mesmo estado,
mesma projeção, mesmo catálogo — e chama `compute_values`. Duas implementações
concordariam hoje e divergiriam no primeiro ajuste feito num lado só, e a
divergência apareceria como «pela V2 dá outro número».

O CONTEXTO É PRÉ-JOGO E NÃO MUDA COM O CORTE (§22, §159). Ele descreve o que
havia ANTES do apito: aos 10, aos 30 e aos 63 minutos as nove features de
contexto são idênticas. O mercado, ao contrário, MUDA com o corte (§160) — uma
cotação publicada aos 20 minutos entra num snapshot de 30 e não num de 10.

TUDO PURO (§43, §79, §179). Nem contexto nem mercado vão ao banco: o contexto
chega pronto pela camada de aplicação, e o mercado sai do `OddsState` que o
PR-05.2 já reconstruiu.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Final, Self, final

from sports_intelligence.domain.features.availability import (
    FeatureAvailability,
    TemporalAvailabilityPolicy,
)
from sports_intelligence.domain.features.context import CorpusSource
from sports_intelligence.domain.features.definitions import FeatureDefinition
from sports_intelligence.domain.features.extraction.catalog import FeatureSide
from sports_intelligence.domain.features.extraction.catalog_v2 import (
    ContextFeatureKind,
    ContextFeatureSpec,
    ExtendedFeatureCatalog,
    MarketFeatureKind,
    MarketFeatureSpec,
    v1_catalog_view,
)
from sports_intelligence.domain.features.extraction.context import (
    MatchFeatureExtractionContext,
)
from sports_intelligence.domain.features.extraction.extractor import (
    MatchStateFeatureExtractor,
)
from sports_intelligence.domain.features.leakage import LeakageReason
from sports_intelligence.domain.features.market.consensus import (
    MarketConsensus,
    MarketConsensusPolicy,
    compute_consensus,
)
from sports_intelligence.domain.features.prematch.models import MatchContextInput
from sports_intelligence.domain.features.prematch.policy import (
    SECONDS_PER_HOUR,
    HistoricalContextPolicy,
)
from sports_intelligence.domain.features.provenance import (
    FeatureContribution,
    FeatureProvenance,
    FeatureProvenanceClass,
)
from sports_intelligence.domain.features.snapshot import FeatureSnapshot
from sports_intelligence.domain.features.space import FeatureSpaceDefinition
from sports_intelligence.domain.features.state.builder import MatchStateBuildResult
from sports_intelligence.domain.features.state.components import OddsQuoteState
from sports_intelligence.domain.features.values import ComputedFeature
from sports_intelligence.domain.shared.errors import ValidationError

#: Quantas casas o intervalo em horas mantém. Fixo pelo mesmo motivo de sempre:
#: sem quantização, `segundos / 3600` produziria dízima e duas execuções com
#: contextos decimais diferentes dariam textos diferentes para o mesmo número.
GAP_DECIMAL_PLACES: Final[int] = 6

_QUANTUM: Final[Decimal] = Decimal(1).scaleb(-GAP_DECIMAL_PLACES)


@final
@dataclass(frozen=True, slots=True)
class ExtendedFeatureExtractionContext:
    """Tudo que a extração V2 precisa, com as identidades conferidas.

    `context` PODE SER `None` (§82). Um corpus cuja leitura de contexto não
    trouxe a partida — porque ela não está na versão, ou porque a competição
    não tem histórico — produz snapshot com as nove dimensões de contexto
    indisponíveis. O espaço não é inviabilizado por isso.
    """

    base: MatchFeatureExtractionContext
    space: FeatureSpaceDefinition
    catalog: ExtendedFeatureCatalog
    context_policy: HistoricalContextPolicy
    market_policy: MarketConsensusPolicy
    context: MatchContextInput | None = None

    def __post_init__(self) -> None:
        if self.space.keys != tuple(s.definition.key for s in self.catalog.specs):
            raise ValidationError(
                f"o espaço {self.space.name} e o catálogo estendido declaram "
                "conjuntos ou ordens diferentes de features"
            )
        if self.context is not None and self.context.match_id != self.base.as_of.match_id:
            raise ValidationError(
                f"o contexto é da partida {self.context.match_id} e a extração é de "
                f"{self.base.as_of.match_id}"
            )

    @classmethod
    def of(
        cls,
        build: MatchStateBuildResult,
        *,
        space: FeatureSpaceDefinition,
        catalog: ExtendedFeatureCatalog,
        source: CorpusSource,
        policy: TemporalAvailabilityPolicy,
        v1_space: FeatureSpaceDefinition,
        context_policy: HistoricalContextPolicy,
        market_policy: MarketConsensusPolicy,
        context: MatchContextInput | None = None,
    ) -> Self:
        """A porta certa: o contexto da V1 sai do MESMO resultado de estado.

        `v1_space` ENTRA porque o contexto da V1 confere espaço contra
        catálogo. Ele é o espaço da V1 de verdade — o mesmo objeto que o
        PR-05.3 publica —, e não uma fatia reconstruída da V2.
        """
        return cls(
            base=MatchFeatureExtractionContext.of(
                build,
                space=v1_space,
                catalog=v1_catalog_view(catalog),
                source=source,
                policy=policy,
            ),
            space=space,
            catalog=catalog,
            context_policy=context_policy,
            market_policy=market_policy,
            context=context,
        )

    def __str__(self) -> str:
        contexto = "com contexto" if self.context is not None else "sem contexto"
        return f"extração V2 {self.base.as_of} · {contexto} · {self.space.identity}"


@final
@dataclass(frozen=True, slots=True)
class ExtendedMatchStateFeatureExtractor:
    """Produz o `FeatureSnapshot` da V2 (§155)."""

    def extract(self, context: ExtendedFeatureExtractionContext) -> FeatureSnapshot:
        herdadas = MatchStateFeatureExtractor().compute_values(context.base)
        if len(herdadas) != context.catalog.inherited:  # pragma: no cover
            raise ValidationError(
                f"o extrator da V1 produziu {len(herdadas)} valores e a V2 herda "
                f"{context.catalog.inherited}"
            )
        valores: list[ComputedFeature] = list(herdadas)
        por_chave = {c.definition_key: c for c in herdadas}

        consensos = _consensos(context)
        for spec in context.catalog.specs[context.catalog.inherited :]:
            if isinstance(spec, ContextFeatureSpec):
                computada = _do_contexto(spec, context, por_chave)
            elif isinstance(spec, MarketFeatureSpec):
                computada = _do_mercado(spec, context, consensos)
            else:  # pragma: no cover - o construtor já garante o prefixo
                raise ValidationError(
                    f"especificação inesperada depois do prefixo da V1: {spec}"
                )
            por_chave[spec.definition.key] = computada
            valores.append(computada)

        return FeatureSnapshot.of(
            as_of=context.base.as_of,
            space=context.space,
            source=context.base.source,
            policy=context.base.policy,
            features=tuple(valores),
        )


# ================================================ features de contexto ==


def _do_contexto(
    spec: ContextFeatureSpec,
    context: ExtendedFeatureExtractionContext,
    calculadas: dict[str, ComputedFeature],
) -> ComputedFeature:
    """O valor de uma feature de contexto (§23, §27, §31 ao §34)."""
    if spec.side is FeatureSide.DIFFERENCE:
        return _diferenca(spec.definition, context, calculadas)

    entrada = context.context
    if entrada is None:
        # §82 — a leitura não trouxe contexto para esta partida. Não é zero.
        return _indisponivel(
            spec.definition,
            context,
            FeatureAvailability.SOURCE_UNAVAILABLE,
            "a versão publicada não forneceu contexto histórico para esta partida",
        )
    lado = entrada.home if spec.side is FeatureSide.HOME else entrada.away

    if spec.kind is ContextFeatureKind.PREV_KICKOFF_GAP_HOURS:
        anterior = lado.latest
        if anterior is None:
            # §26, §33 — «não há partida anterior» tem duas causas, e elas
            # pedem ações diferentes. Se o corpus daquela competição começa
            # nesta partida ou depois, a ausência é do ARQUIVO; se ele alcança
            # o passado e mesmo assim não há jogo deste time, a ausência é do
            # CALENDÁRIO.
            if not entrada.coverage.covers(start=entrada.kickoff):
                return _indisponivel(
                    spec.definition,
                    context,
                    FeatureAvailability.INSUFFICIENT_COVERAGE,
                    "o corpus desta competição não alcança nenhum instante anterior "
                    "ao apito desta partida",
                )
            return _indisponivel(
                spec.definition,
                context,
                FeatureAvailability.SOURCE_UNAVAILABLE,
                "o corpus alcança o passado e não publica partida anterior deste time "
                "nesta competição",
            )
        segundos = Decimal(
            (entrada.kickoff - anterior.kickoff).total_seconds()
        ).quantize(_QUANTUM)
        horas = (segundos / Decimal(SECONDS_PER_HOUR)).quantize(_QUANTUM).normalize()
        return _disponivel(
            spec.definition,
            context,
            float(horas),
            (FeatureContribution(kind="MATCH", reference=str(anterior.match_id)),),
        )

    # ---- contagem em janela (§27, §28, §29, §30) -----------------------
    assert spec.lookback_days is not None
    inicio = entrada.kickoff - timedelta(days=spec.lookback_days)
    if not entrada.coverage.covers(start=inicio):
        # §32, §34 — sem prova de que o corpus alcança o começo da janela,
        # «zero partidas» seria uma afirmação sobre o mundo feita a partir de
        # uma limitação do arquivo.
        return _indisponivel(
            spec.definition,
            context,
            FeatureAvailability.INSUFFICIENT_COVERAGE,
            f"o corpus desta competição não alcança T-{spec.lookback_days}d",
        )
    dentro = lado.within(start=inicio, end=entrada.kickoff)
    return _disponivel(
        spec.definition,
        context,
        len(dentro),
        tuple(
            FeatureContribution(kind="MATCH", reference=str(m.match_id)) for m in dentro
        ),
    )


# ================================================= features de mercado ==


def _consensos(
    context: ExtendedFeatureExtractionContext,
) -> dict[str, MarketConsensus]:
    """O consenso de cada mercado — calculado UMA vez por snapshot.

    SEM ISTO, cada uma das vinte e uma features recalcularia a mediana do
    próprio mercado: três varreduras por mercado onde uma basta.
    """
    odds = context.base.state.odds
    if not odds.is_available:
        return {}
    return {
        spec.market.key_fragment: compute_consensus(
            odds, spec.market, policy=context.market_policy
        )
        for spec in context.catalog.specs[context.catalog.inherited :]
        if isinstance(spec, MarketFeatureSpec)
    }


def _do_mercado(
    spec: MarketFeatureSpec,
    context: ExtendedFeatureExtractionContext,
    consensos: dict[str, MarketConsensus],
) -> ComputedFeature:
    """O valor de uma feature de mercado (§50, §65, §66, §69)."""
    odds = context.base.state.odds
    if not odds.is_available:
        # §66, primeiro caso: a família não é publicada, ou nenhuma cotação é
        # elegível neste corte. A distinção vem do próprio estado.
        if odds.availability is FeatureAvailability.TEMPORALLY_UNAVAILABLE:
            razao = (
                LeakageReason.KNOWLEDGE_TIME_AFTER_CUTOFF
                if context.base.as_of.has_knowledge_cutoff
                else LeakageReason.MISSING_KNOWLEDGE_CUTOFF
            )
            return ComputedFeature.unavailable(
                definition_key=spec.definition.key,
                definition_fingerprint=spec.definition.fingerprint,
                as_of=context.base.as_of,
                availability=FeatureAvailability.TEMPORALLY_UNAVAILABLE,
                leakage_reason=razao,
                detail=odds.detail,
            )
        return _indisponivel(spec.definition, context, odds.availability, odds.detail)

    consenso = consensos.get(spec.market.key_fragment)
    if consenso is None or not consenso.has_quotes:
        # §66, segundo caso: a família É publicada e ESTE mercado não veio.
        return _indisponivel(
            spec.definition,
            context,
            FeatureAvailability.SOURCE_UNAVAILABLE,
            f"nenhuma cotação elegível de {spec.market} neste corte",
        )

    procedencia = tuple(
        FeatureContribution(kind="ODDS", reference=_referencia_da_cotacao(q))
        for q in consenso.quotes
    )
    if spec.kind is MarketFeatureKind.SUPPORT:
        # §65 — o suporte existe sempre que o mercado existe.
        return _disponivel(
            spec.definition, context, consenso.support, procedencia
        )
    if spec.kind is MarketFeatureKind.MEDIAN:
        if consenso.median is None:
            return _indisponivel(
                spec.definition,
                context,
                FeatureAvailability.INSUFFICIENT_COVERAGE,
                f"{consenso.support} casa(s), abaixo do mínimo declarado de "
                f"{context.market_policy.median_minimum_support}",
            )
        return _disponivel(
            spec.definition, context, float(consenso.median), procedencia
        )

    # ---- IQR (§69, §70) ------------------------------------------------
    if consenso.iqr is None:
        # UMA CASA NÃO PROVA DISPERSÃO ZERO. Devolver `0` afirmaria que o
        # mercado é unânime quando não há com quem concordar.
        return _indisponivel(
            spec.definition,
            context,
            FeatureAvailability.INSUFFICIENT_COVERAGE,
            f"{consenso.support} casa(s), abaixo do mínimo de "
            f"{context.market_policy.iqr_minimum_support} para afirmar dispersão",
        )
    # §70 — quatro casas com o mesmo preço têm dispersão nula OBSERVADA, e ela
    # é um valor legítimo.
    return _disponivel(spec.definition, context, float(consenso.iqr), procedencia)


def _referencia_da_cotacao(quote: OddsQuoteState) -> str:
    """A referência de UMA cotação na procedência (§71).

    ELA COMEÇA PELO FLUXO, e não pelo registro de origem. Quatro casas de um
    mesmo arquivo compartilham o `source_record_id`, e usá-lo sozinho faria as
    quatro contribuições colapsarem numa — a procedência diria «uma cotação
    sustenta esta mediana» quando são quatro. O fluxo
    `(casa, mercado, seleção, linha)` é único por cotação dentro do corte, e o
    registro de origem viaja junto para a travessia até o corpus.
    """
    fluxo = "|".join(quote.stream_key())
    return f"{fluxo}#{quote.source_reference}" if quote.source_reference else fluxo


# ==================================================== auxiliares comuns ==


def _diferenca(
    definition: FeatureDefinition,
    context: ExtendedFeatureExtractionContext,
    calculadas: dict[str, ComputedFeature],
) -> ComputedFeature:
    """`home - away`, e SÓ quando os dois lados existem (§25, §65)."""
    chaves = definition.depends_on_features
    if len(chaves) != 2:  # pragma: no cover - o catálogo sempre declara duas
        raise ValidationError(f"{definition.key} não declara duas dependências")
    casa, fora = (calculadas[c] for c in chaves)
    if not casa.is_available or not fora.is_available:
        ausente = casa if not casa.is_available else fora
        return _indisponivel(
            definition,
            context,
            ausente.availability,
            f"{ausente.definition_key} não é afirmável nesta partida",
        )
    valor_casa, valor_fora = casa.numeric, fora.numeric
    assert valor_casa is not None
    assert valor_fora is not None
    from sports_intelligence.domain.features.definitions import FeatureOutputType

    if definition.output_type is FeatureOutputType.INTEGER:
        diferenca: float = round(valor_casa - valor_fora)
    else:
        diferenca = float(
            (Decimal(str(valor_casa)) - Decimal(str(valor_fora)))
            .quantize(_QUANTUM)
            .normalize()
        )
    return _disponivel(
        definition,
        context,
        diferenca,
        (*casa.provenance.sample, *fora.provenance.sample),
    )


def _disponivel(
    definition: FeatureDefinition,
    context: ExtendedFeatureExtractionContext,
    value: float | int,
    contributions: tuple[FeatureContribution, ...],
) -> ComputedFeature:
    return ComputedFeature.available(
        definition_key=definition.key,
        definition_fingerprint=definition.fingerprint,
        as_of=context.base.as_of,
        value=value,
        provenance=FeatureProvenance.of(
            FeatureProvenanceClass.DERIVED_FROM_CANONICAL, contributions
        ),
    )


def _indisponivel(
    definition: FeatureDefinition,
    context: ExtendedFeatureExtractionContext,
    availability: FeatureAvailability,
    detail: str = "",
) -> ComputedFeature:
    return ComputedFeature.unavailable(
        definition_key=definition.key,
        definition_fingerprint=definition.fingerprint,
        as_of=context.base.as_of,
        availability=availability,
        detail=detail,
    )
