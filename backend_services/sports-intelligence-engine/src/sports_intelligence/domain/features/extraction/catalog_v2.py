"""O catálogo V2 — as 75 da V1, mais contexto e mercado, SEM tocar na V1.

A REGRA ABSOLUTA DESTE ARQUIVO (§3, §5, §90). `MATCH_STATE_RAW_V1` na versão
1.0 não muda. Nem uma feature a mais, nem uma ordem diferente, nem uma
descrição reescrita. Um espaço que ganhasse trinta dimensões mantendo o número
da versão faria todo snapshot histórico comparar com um espaço que não é o dele
— e a comparação não falharia, ela mentiria.

    V2[0:75] == V1        semanticamente, e testado (§8, §157)

O acréscimo é APPEND. As setenta e cinco primeiras posições da V2 são as mesmas
definições da V1, na mesma ordem, com as mesmas impressões — os objetos são
literalmente os mesmos, vindos de `production_feature_catalog()`. Isso torna a
comparação entre as duas versões trivial em vez de uma conferência de trinta
linhas, e torna impossível uma delas divergir por edição.

O QUE A V2 ACRESCENTA:

    contexto pré-jogo   9 features — intervalo desde a partida anterior da
                        MESMA competição, e contagem em 14 e 30 dias
    mercado canônico    21 features — nível, dispersão e suporte de sete
                        mercados declarados

A V2 CONTINUA CRUA (§152). `normalization = NONE`: nenhuma definição declara
normalizador. O runtime de ajuste existe neste PR e não é aplicado a espaço
nenhum — a população científica de ajuste é o PR-05.5.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.features.availability import FactKind
from sports_intelligence.domain.features.definitions import (
    FeatureDefinition,
    FeatureOutputType,
    FeatureScope,
    FeatureTemporalClass,
)
from sports_intelligence.domain.features.extraction.catalog import (
    V1,
    FeatureSide,
    FeatureSpec,
    ProductionFeatureCatalog,
    production_feature_catalog,
)
from sports_intelligence.domain.features.market.specs import (
    MARKET_SPECS_V1,
    CanonicalMarketSpec,
)
from sports_intelligence.domain.features.prematch.policy import (
    DEFAULT_CONTEXT_POLICY,
    HistoricalContextPolicy,
)
from sports_intelligence.domain.features.registry import FeatureDefinitionRegistry
from sports_intelligence.domain.features.space import (
    CorpusRequirement,
    FeatureSpaceDefinition,
)
from sports_intelligence.domain.features.temporal import TemporalMode
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.versioning import FeatureSpaceVersion

#: O nome do espaço estendido (§4).
MATCH_STATE_RAW_V2_NAME: Final[str] = "MATCH_STATE_RAW_V2"

#: Quantas definições a V1 tem. Ela é constante e é conferida: se a V1 mudar de
#: tamanho, a construção da V2 falha em vez de herdar a mudança em silêncio.
V1_SIZE: Final[int] = 75


# ============================================== features de contexto ==


@final
class ContextFeatureKind(StrEnum):
    """O que extrair do contexto pré-jogo (§23, §27).

    O NOME DIZ O QUE ELE MEDE (§16). `SAME_COMP_PREV_KICKOFF_GAP` e nunca
    `REST_DAYS`: o que se mede é o intervalo até a partida anterior DA MESMA
    COMPETIÇÃO, medido de apito a apito. Um time que jogou a Champions na
    quarta aparece aqui como se tivesse descansado a semana inteira, e o nome
    da feature precisa admitir isso.
    """

    PREV_KICKOFF_GAP_HOURS = "PREV_KICKOFF_GAP_HOURS"
    MATCHES_IN_WINDOW = "MATCHES_IN_WINDOW"


@final
@dataclass(frozen=True, slots=True)
class ContextFeatureSpec:
    """Uma feature de contexto, com o que extrair declarado por tipo."""

    definition: FeatureDefinition
    kind: ContextFeatureKind
    side: FeatureSide
    #: A janela em dias, para `MATCHES_IN_WINDOW`. `None` para o intervalo.
    lookback_days: int | None = None


def context_definition(
    *,
    kind: ContextFeatureKind,
    side: FeatureSide,
    policy: HistoricalContextPolicy,
    lookback_days: int | None = None,
) -> FeatureDefinition:
    """A definição de UMA feature de contexto — gerada e estável (§84, §85).

    A POLÍTICA ENTRA NOS PARÂMETROS, e portanto na impressão. Trocar o escopo
    de `SAME_COMPETITION` para outro, ou a prova de conclusão, muda o que a
    feature mede — e a identidade precisa mudar junto.
    """
    if kind is ContextFeatureKind.PREV_KICKOFF_GAP_HOURS:
        chave = f"ctx_same_comp_prev_gap_hours_{side.suffix}"
        unidade = "hours"
        tipo = FeatureOutputType.FLOAT
        descricao = (
            "Horas entre o apito inicial desta partida e o da anterior do "
            f"{_lado(side)} na MESMA competição — calendário, e não descanso real"
        )
        parametros: dict[str, str | int | float | bool | None] = {}
    else:
        assert lookback_days is not None
        chave = f"ctx_same_comp_matches_{lookback_days}d_{side.suffix}"
        unidade = "count"
        tipo = FeatureOutputType.INTEGER
        descricao = (
            f"Partidas do {_lado(side)} na MESMA competição em [T-{lookback_days}d, T), "
            "com T sendo o apito inicial desta partida"
        )
        parametros = {"lookback_days": lookback_days}

    if side is FeatureSide.DIFFERENCE:
        dependencias = tuple(
            (
                f"ctx_same_comp_prev_gap_hours_{lado.suffix}"
                if kind is ContextFeatureKind.PREV_KICKOFF_GAP_HOURS
                else f"ctx_same_comp_matches_{lookback_days}d_{lado.suffix}"
            )
            for lado in (FeatureSide.HOME, FeatureSide.AWAY)
        )
    else:
        dependencias = ()

    return FeatureDefinition(
        key=chave,
        version=V1,
        description=descricao,
        output_type=tipo,
        scope=side.scope,
        # PRÉ-JOGO, e não intra-jogo (§22). O contexto é o mesmo aos 10, aos 30
        # e aos 63 minutos: ele descreve o que havia ANTES do apito.
        temporal_class=FeatureTemporalClass.PRE_MATCH,
        required_families=(CoverageFamily.MATCH,),
        required_fact_kinds=(FactKind.MATCH_IDENTITY,),
        parameters={
            **parametros,
            "context_boundary": policy.boundary.value,
            "context_eligibility": policy.eligibility.value,
            "context_policy_fingerprint": policy.fingerprint,
            "context_scope": policy.scope.value,
            "kind": kind.value,
            "side": side.value,
        },
        unit=unidade,
        depends_on_features=dependencias,
    )


def _lado(side: FeatureSide) -> str:
    return "mandante" if side is FeatureSide.HOME else "visitante"


def _specs_de_contexto(policy: HistoricalContextPolicy) -> tuple[ContextFeatureSpec, ...]:
    """As nove features de contexto, na ordem do espaço.

    A ORDEM É `família → lado`, e as janelas seguem a ordem declarada na
    política — que já é crescente por construção.
    """
    specs: list[ContextFeatureSpec] = []
    for lado in (FeatureSide.HOME, FeatureSide.AWAY, FeatureSide.DIFFERENCE):
        specs.append(
            ContextFeatureSpec(
                definition=context_definition(
                    kind=ContextFeatureKind.PREV_KICKOFF_GAP_HOURS,
                    side=lado,
                    policy=policy,
                ),
                kind=ContextFeatureKind.PREV_KICKOFF_GAP_HOURS,
                side=lado,
            )
        )
    for dias in policy.lookback_days:
        for lado in (FeatureSide.HOME, FeatureSide.AWAY, FeatureSide.DIFFERENCE):
            specs.append(
                ContextFeatureSpec(
                    definition=context_definition(
                        kind=ContextFeatureKind.MATCHES_IN_WINDOW,
                        side=lado,
                        policy=policy,
                        lookback_days=dias,
                    ),
                    kind=ContextFeatureKind.MATCHES_IN_WINDOW,
                    side=lado,
                    lookback_days=dias,
                )
            )
    return tuple(specs)


# =============================================== features de mercado ==


@final
class MarketFeatureKind(StrEnum):
    """As três dimensões de cada mercado canônico (§50)."""

    MEDIAN = "MEDIAN"
    IQR = "IQR"
    SUPPORT = "SUPPORT"

    @property
    def suffix(self) -> str:
        return self.value.lower()

    @property
    def output_type(self) -> FeatureOutputType:
        return (
            FeatureOutputType.INTEGER
            if self is MarketFeatureKind.SUPPORT
            else FeatureOutputType.FLOAT
        )

    @property
    def unit(self) -> str:
        return "bookmakers" if self is MarketFeatureKind.SUPPORT else "decimal_odds"


#: A ordem das três dimensões dentro de cada mercado. Declarada, e não
#: alfabética: `iqr` viria antes de `median` no alfabeto, e a leitura natural é
#: nível, dispersão, suporte.
MARKET_KINDS: Final[tuple[MarketFeatureKind, ...]] = (
    MarketFeatureKind.MEDIAN,
    MarketFeatureKind.IQR,
    MarketFeatureKind.SUPPORT,
)


@final
@dataclass(frozen=True, slots=True)
class MarketFeatureSpec:
    """Uma feature de mercado, com especificação e dimensão declaradas."""

    definition: FeatureDefinition
    market: CanonicalMarketSpec
    kind: MarketFeatureKind


def market_definition(
    *, market: CanonicalMarketSpec, kind: MarketFeatureKind, policy_fingerprint: str
) -> FeatureDefinition:
    """A definição de UMA feature de mercado (§86, §87).

    A LINHA ENTRA NA CHAVE E NA IMPRESSÃO (§87). `totals_over_25` diz qual
    linha; sem ela, «mais de 2,5» e «mais de 3,5» seriam a mesma feature.

    A CASA DE APOSTA NÃO ENTRA EM LUGAR NENHUM (§72, §84). Ela é entrada e
    procedência: uma dimensão por casa faria o tamanho do espaço depender de
    quantas casas o corpus publicou.
    """
    descricoes = {
        MarketFeatureKind.MEDIAN: "Mediana das cotações decimais elegíveis",
        MarketFeatureKind.IQR: "Intervalo interquartil das cotações decimais elegíveis",
        MarketFeatureKind.SUPPORT: "Casas de aposta distintas com cotação elegível",
    }
    return FeatureDefinition(
        key=f"market_{market.key_fragment}_{kind.suffix}",
        version=V1,
        description=f"{descricoes[kind]} para {market}",
        output_type=kind.output_type,
        scope=FeatureScope.MATCH,
        temporal_class=FeatureTemporalClass.INTRA_MATCH_CAUSAL,
        required_families=(CoverageFamily.ODDS,),
        required_fact_kinds=(FactKind.ODDS_OBSERVATION,),
        parameters={
            "consensus_policy_fingerprint": policy_fingerprint,
            "kind": kind.value,
            "market": market.market.value,
            "market_line": market.line_text,
            "selection": market.selection.value,
        },
        unit=kind.unit,
    )


def _specs_de_mercado(policy_fingerprint: str) -> tuple[MarketFeatureSpec, ...]:
    """As vinte e uma features de mercado, na ordem do espaço."""
    return tuple(
        MarketFeatureSpec(
            definition=market_definition(
                market=mercado, kind=dimensao, policy_fingerprint=policy_fingerprint
            ),
            market=mercado,
            kind=dimensao,
        )
        for mercado in MARKET_SPECS_V1
        for dimensao in MARKET_KINDS
    )


# ==================================================== o catálogo V2 ==


ExtendedFeatureSpec = FeatureSpec | ContextFeatureSpec | MarketFeatureSpec


@final
@dataclass(frozen=True, slots=True)
class ExtendedFeatureCatalog:
    """As definições da V2 — as da V1 na frente, intocadas (§8, §157)."""

    specs: tuple[ExtendedFeatureSpec, ...]
    inherited: int = V1_SIZE

    def __post_init__(self) -> None:
        chaves = [s.definition.key for s in self.specs]
        if len(set(chaves)) != len(chaves):
            repetidas = sorted({k for k in chaves if chaves.count(k) > 1})
            raise ValidationError(f"catálogo V2 com chave repetida: {repetidas}")
        herdadas = production_feature_catalog().definitions
        if len(herdadas) != self.inherited:
            raise ValidationError(
                f"a V1 tem {len(herdadas)} definições e a V2 declara herdar "
                f"{self.inherited}: a V1 mudou de tamanho, e a V2 herdaria a mudança "
                "sem que ninguém decidisse (PR-05.4 §3, §5)"
            )
        prefixo = tuple(s.definition for s in self.specs[: self.inherited])
        if prefixo != herdadas:
            raise ValidationError(
                "as primeiras 75 definições da V2 não são as da V1 — o acréscimo é "
                "APPEND, e reescrever uma delas quebraria a comparação entre as duas "
                "versões (§8)"
            )

    @property
    def definitions(self) -> tuple[FeatureDefinition, ...]:
        return tuple(s.definition for s in self.specs)

    @property
    def size(self) -> int:
        return len(self.specs)

    def spec_of(self, key: str) -> ExtendedFeatureSpec:
        for spec in self.specs:
            if spec.definition.key == key:
                return spec
        raise ValidationError(f"o catálogo V2 não contém a feature {key!r}")


def extended_feature_catalog(
    *,
    context_policy: HistoricalContextPolicy = DEFAULT_CONTEXT_POLICY,
    consensus_policy_fingerprint: str | None = None,
) -> ExtendedFeatureCatalog:
    """O catálogo de produção da V2 (§7).

    A ORDEM: as 75 da V1, depois contexto, depois mercado. Ela é declarada, e o
    prefixo é conferido no construtor.
    """
    from sports_intelligence.domain.features.market.consensus import (
        MarketConsensusPolicy,
    )

    impressao = (
        consensus_policy_fingerprint
        if consensus_policy_fingerprint is not None
        else MarketConsensusPolicy().fingerprint
    )
    return ExtendedFeatureCatalog(
        specs=(
            *production_feature_catalog().specs,
            *_specs_de_contexto(context_policy),
            *_specs_de_mercado(impressao),
        )
    )


def extended_feature_registry(
    *, context_policy: HistoricalContextPolicy = DEFAULT_CONTEXT_POLICY
) -> FeatureDefinitionRegistry:
    """O registro com as definições da V1 E da V2 (§89).

    ELE NÃO É DOIS REGISTROS. As 75 da V1 estão dentro da V2 — os mesmos
    objetos —, então registrar a V2 registra as duas. O `FeatureDefinitionRegistry`
    recusaria a repetição se elas fossem cópias com o mesmo nome; o fato de
    passar é a prova de que são as MESMAS.
    """
    return FeatureDefinitionRegistry.of(
        extended_feature_catalog(context_policy=context_policy).definitions
    )


def match_state_raw_space_v2(
    *,
    context_policy: HistoricalContextPolicy = DEFAULT_CONTEXT_POLICY,
) -> FeatureSpaceDefinition:
    """O espaço de produção ESTENDIDO (§4, §6).

    `requirement` CONTINUA EXIGINDO `EVENT` E `LINEUP`, e NÃO exige `ODDS` nem
    contexto (§80, §81, §82). A exigência do espaço é o que impede compor sobre
    um corpus incompatível; torná-la mais estrita faria um corpus sem mercado
    ser recusado inteiro, quando o certo é ele produzir snapshot com as
    dimensões de mercado indisponíveis. A ausência é da MÁSCARA, e não do
    espaço.
    """
    catalogo = extended_feature_catalog(context_policy=context_policy)
    return FeatureSpaceDefinition(
        name=MATCH_STATE_RAW_V2_NAME,
        version=FeatureSpaceVersion(major=2, minor=0),
        features=catalogo.definitions,
        temporal_mode=TemporalMode.AS_KNOWN,
        live_comparable=True,
        requirement=CorpusRequirement.of(
            CoverageFamily.EVENT,
            CoverageFamily.LINEUP,
            CoverageFamily.MATCH,
            # §80 — `ODDS` é OPCIONAL: um corpus sem mercado continua produzindo
            # snapshot, com as vinte e uma dimensões de mercado indisponíveis
            # na máscara. Torná-la obrigatória recusaria o corpus inteiro.
            optional=(CoverageFamily.ODDS,),
        ),
        description=(
            "As 75 features cruas da V1, mais contexto pré-jogo de calendário e "
            "consenso de mercado. Sem normalização, sem composição."
        ),
    )


def v1_prefix_of(catalog: ExtendedFeatureCatalog) -> tuple[FeatureSpec, ...]:
    """As especificações herdadas da V1 — para quem reusa o extrator (§156)."""
    prefixo = catalog.specs[: catalog.inherited]
    return tuple(s for s in prefixo if not isinstance(s, ContextFeatureSpec | MarketFeatureSpec))


def v1_catalog_view(catalog: ExtendedFeatureCatalog) -> ProductionFeatureCatalog:
    """A visão V1 do catálogo estendido, para o extrator da V1 (§156).

    ELE NÃO COPIA AS 75 FEATURES. Devolve o catálogo de produção da V1 — os
    mesmos objetos —, e o construtor da V2 já provou que o prefixo é ele.
    """
    return ProductionFeatureCatalog(specs=v1_prefix_of(catalog))
