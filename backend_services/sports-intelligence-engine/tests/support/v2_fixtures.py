"""O cenário do PR-05.4 — contexto pré-jogo, mercado e população de ajuste.

TRÊS CENÁRIOS PEQUENOS, e cada um exercita uma capacidade:

    CONTEXTO   quatro partidas da mesma competição, mais uma de OUTRA, para
               provar que o escopo é local (§14, §168)

               A  2026-03-01 12:00
               B  2026-03-08 12:00     ← 7 dias depois de A
               C  2026-03-22 12:00     ← 14 dias depois de B (a fronteira!)
               D  2026-03-29 15:00     ← a partida ATUAL
               X  2026-03-25 20:00     ← OUTRA competição, ignorada

               Para D, com T = 29/03 15:00:
                 anterior     C, em 22/03 12:00  →  gap 171 horas
                 [T-14d, T)   [15/03 15:00, 29/03 15:00)  →  só C
                 [T-30d, T)   [27/02 15:00, 29/03 15:00)  →  A, B e C

    MERCADO    quatro casas cotando 1X2, uma delas com preço diferente, mais
               um mercado com uma casa só para o suporte insuficiente

    POPULAÇÃO  valores decimais explícitos para o ajuste, com o mínimo
               rebaixado para que o cenário caiba num teste

O CENÁRIO DE CONTEXTO É CONSTRUÍDO À MÃO, e os valores esperados também: um
teste que computa o esperado com o código que testa prova apenas que ele
concorda consigo mesmo.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final

from sports_intelligence.domain.features.availability import TemporalAvailabilityPolicy
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
from sports_intelligence.domain.features.fitting.population import (
    FeatureObservation,
    FeaturePopulation,
)
from sports_intelligence.domain.features.market.consensus import MarketConsensusPolicy
from sports_intelligence.domain.features.prematch.models import (
    ContextCoverage,
    MatchContextInput,
    PriorMatchRef,
    team_prior_matches,
)
from sports_intelligence.domain.features.prematch.policy import (
    DEFAULT_CONTEXT_POLICY,
    HistoricalContextPolicy,
)
from sports_intelligence.domain.features.snapshot import FeatureSnapshot
from sports_intelligence.domain.features.state.builder import (
    CanonicalMatchStateInput,
    HistoricalMatchStateBuilder,
)
from sports_intelligence.domain.features.state.components import OddsQuoteState
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.odds.models import (
    BookmakerRef,
    CanonicalOddsObservation,
    OddsMarket,
    OddsSelection,
)
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.identity import CompetitionId, MatchId
from sports_intelligence.domain.shared.temporal import Instant, Period, instant
from tests.support.feature_fixtures import (
    PARTIDA,
    competicao,
    corte,
    origem,
    procedencia_do_cenario,
    relogio_de_parede,
)
from tests.support.snapshot_fixtures import TODAS_AS_FAMILIAS, entrada

# ------------------------------------------------------------- contexto --

COMPETICAO: Final[CompetitionId] = competicao().id

#: O apito da partida ATUAL do cenário de contexto.
KICKOFF_ATUAL: Final[Instant] = instant(datetime(2026, 3, 29, 15, 0, tzinfo=UTC))

KICKOFF_A: Final[Instant] = instant(datetime(2026, 3, 1, 12, 0, tzinfo=UTC))
KICKOFF_B: Final[Instant] = instant(datetime(2026, 3, 8, 12, 0, tzinfo=UTC))
KICKOFF_C: Final[Instant] = instant(datetime(2026, 3, 22, 12, 0, tzinfo=UTC))

MATCH_A: Final[MatchId] = MatchId.derive("pr054", "partida-a")
MATCH_B: Final[MatchId] = MatchId.derive("pr054", "partida-b")
MATCH_C: Final[MatchId] = MatchId.derive("pr054", "partida-c")

#: O intervalo esperado entre C e a atual, EM HORAS, calculado à mão:
#: de 22/03 12:00 a 29/03 15:00 são 7 dias e 3 horas = 171 horas.
GAP_ESPERADO_CASA: Final[Decimal] = Decimal("171")

#: O do visitante: só a partida B, de 08/03 12:00 → 21 dias e 3 horas.
GAP_ESPERADO_FORA: Final[Decimal] = Decimal("507")


#: Até onde o corpus do cenário alcança. Ele é ANTERIOR a `T - 30d` de
#: propósito: assim as duas janelas são afirmáveis, e a insuficiência vira um
#: caso que o teste PEDE em vez de um acidente do cenário.
COBERTURA_PADRAO: Final[Instant] = instant(datetime(2026, 2, 1, 0, 0, tzinfo=UTC))


def cobertura(*, alcanca: Instant | None = COBERTURA_PADRAO) -> ContextCoverage:
    """Até onde o corpus alcança. O padrão cobre as duas janelas."""
    return ContextCoverage(competition_id=COMPETICAO, earliest_kickoff=alcanca)


def contexto_de_partida(
    *,
    casa: tuple[tuple[Instant, MatchId], ...] = (
        (KICKOFF_A, MATCH_A),
        (KICKOFF_B, MATCH_B),
        (KICKOFF_C, MATCH_C),
    ),
    fora: tuple[tuple[Instant, MatchId], ...] = ((KICKOFF_B, MATCH_B),),
    kickoff: Instant = KICKOFF_ATUAL,
    coverage: ContextCoverage | None = None,
) -> MatchContextInput:
    """O contexto da partida atual do cenário.

    O VISITANTE JOGOU MENOS de propósito: ele é o que torna as diferenças
    diferentes de zero, e o que expõe uma diferença calculada ao contrário.
    """
    from tests.support.feature_fixtures import CASA, FORA

    return MatchContextInput(
        match_id=PARTIDA,
        competition_id=COMPETICAO,
        kickoff=kickoff,
        home=team_prior_matches(CASA, [PriorMatchRef(kickoff=k, match_id=m) for k, m in casa]),
        away=team_prior_matches(FORA, [PriorMatchRef(kickoff=k, match_id=m) for k, m in fora]),
        coverage=coverage or cobertura(),
    )


# --------------------------------------------------------------- mercado --


def cotacao(
    casa: str,
    valor: str,
    *,
    market: OddsMarket = OddsMarket.MATCH_RESULT_1X2,
    selection: OddsSelection = OddsSelection.HOME,
    line: Decimal | None = None,
    minuto: float = -60.0,
) -> CanonicalOddsObservation:
    """Uma cotação canônica do cenário, com instante relativo ao apito."""
    return CanonicalOddsObservation(
        match_id=PARTIDA,
        bookmaker=BookmakerRef(code=casa),
        market=market,
        selection=selection,
        decimal_odds=Decimal(valor),
        line=line,
        observed_at=relogio_de_parede(minuto),
        provenance=procedencia_do_cenario(relogio_de_parede(minuto)),
    )


#: QUATRO CASAS NO 1X2 HOME, com os quartis conferidos à mão pelo método
#: declarado — interpolação linear inclusiva, `h = (n-1)·p`:
#:
#:     1.80  1.90  2.00  2.10          n = 4
#:     Q1  h = 3·0,25 = 0,75  →  1,80 + 0,75·0,10 = 1,875
#:     Md  h = 3·0,50 = 1,50  →  1,90 + 0,50·0,10 = 1,95
#:     Q3  h = 3·0,75 = 2,25  →  2,00 + 0,25·0,10 = 2,025
#:     IQR = 2,025 menos 1,875 = 0,15
#:
#: A CONTA IMPORTA MAIS QUE O NÚMERO. Com a convenção EXCLUSIVA — a que o
#: `statistics.quantiles` do Python usa por padrão — os mesmos quatro preços
#: dariam Q1 = 1,85 e IQR = 0,20. É exatamente a diferença que o §61 existe
#: para impedir de aparecer sozinha depois de uma atualização de biblioteca.
MERCADO_COMPLETO: Final[tuple[str, ...]] = ("1.80", "1.90", "2.00", "2.10")

MEDIANA_ESPERADA: Final[Decimal] = Decimal("1.95")
Q1_ESPERADO: Final[Decimal] = Decimal("1.875")
Q3_ESPERADO: Final[Decimal] = Decimal("2.025")
IQR_ESPERADO: Final[Decimal] = Decimal("0.15")


def odds_do_cenario(
    *,
    casas_1x2: tuple[str, ...] = MERCADO_COMPLETO,
    com_btts: bool = True,
    minuto: float = -60.0,
) -> tuple[CanonicalOddsObservation, ...]:
    """As cotações do cenário: 1X2 com quatro casas, BTTS com uma só.

    O BTTS COM UMA CASA É O CASO DO §69: mediana afirmável, dispersão não.
    """
    cotacoes = [
        cotacao(f"CASA{n}", valor, minuto=minuto) for n, valor in enumerate(casas_1x2, start=1)
    ]
    if com_btts:
        cotacoes.append(
            cotacao(
                "CASA1",
                "1.70",
                market=OddsMarket.BOTH_TEAMS_TO_SCORE,
                selection=OddsSelection.YES,
                minuto=minuto,
            )
        )
    return tuple(cotacoes)


def quote_state(
    casa: str,
    valor: str,
    *,
    market: str = "MATCH_RESULT_1X2",
    selection: str = "HOME",
    line: str | None = None,
) -> OddsQuoteState:
    """Uma cotação já no formato do estado — para testar o consenso puro."""
    return OddsQuoteState(
        bookmaker=casa,
        market=market,
        selection=selection,
        decimal_odds=valor,
        observed_at=relogio_de_parede(-60.0),
        line=line,
        source_reference=f"{casa}-{market}-{selection}",
    )


# ------------------------------------------------------------ extração --


#: As famílias do cenário V2 — as da V1 mais `ODDS`, que é o que dá mercado.
FAMILIAS_V2: Final[frozenset[CoverageFamily]] = TODAS_AS_FAMILIAS | {CoverageFamily.ODDS}


def catalogo_v2() -> ExtendedFeatureCatalog:
    return extended_feature_catalog()


def entrada_v2(
    *,
    odds: tuple[CanonicalOddsObservation, ...] | None = None,
    families: frozenset[CoverageFamily] | None = None,
    **kwargs: object,
) -> CanonicalMatchStateInput:
    """A entrada de estado do cenário V2 — com `ODDS` publicada.

    O CENÁRIO DA V1 NÃO PUBLICA ODDS, e por isso o mercado sairia
    `NOT_DECLARED` nele. Aqui a família entra, e as cotações também.
    """
    return entrada(
        families=FAMILIAS_V2 if families is None else families,
        odds=odds_do_cenario() if odds is None else odds,
        **kwargs,  # type: ignore[arg-type]
    )


def extrair_v2(
    entrada_: CanonicalMatchStateInput | None = None,
    *,
    as_of: FeatureAsOf | None = None,
    contexto: MatchContextInput | None = None,
    market_policy: MarketConsensusPolicy | None = None,
    context_policy: HistoricalContextPolicy = DEFAULT_CONTEXT_POLICY,
    families: frozenset[CoverageFamily] | None = None,
    sem_contexto: bool = False,
) -> FeatureSnapshot:
    """Um snapshot V2 do cenário — passando pelo construtor de estado."""
    politica = TemporalAvailabilityPolicy.default()
    fonte = origem(families=families or FAMILIAS_V2)
    # O CORTE DECLARA CONHECIMENTO por padrão: sem ele, o guarda do PR-05.1
    # recusa toda cotação por não haver como provar que ela era conhecida — e o
    # cenário de mercado nasceria vazio por um motivo que não é o mercado.
    build = HistoricalMatchStateBuilder(policy=politica).build(
        entrada_ or entrada_v2(),
        as_of=as_of or corte(conhecimento=63),
        source=fonte,
    )
    return ExtendedMatchStateFeatureExtractor().extract(
        ExtendedFeatureExtractionContext.of(
            build,
            space=match_state_raw_space_v2(context_policy=context_policy),
            catalog=extended_feature_catalog(context_policy=context_policy),
            source=fonte,
            policy=politica,
            v1_space=match_state_raw_space_v1(),
            context_policy=context_policy,
            market_policy=market_policy or MarketConsensusPolicy(),
            context=None if sem_contexto else (contexto or contexto_de_partida()),
        )
    )


# ------------------------------------------------------------ população --


def observacao(n: int, valor: str | None, *, corpus: str = "a" * 64) -> FeatureObservation:
    """Uma observação da população de ajuste, derivada de `n`."""
    return FeatureObservation(
        match_id=MatchId.derive("pr054-pop", str(n)),
        as_of=FeatureAsOf.at(MatchId.derive("pr054-pop", str(n)), Period.SECOND_HALF, 60),
        value=None if valor is None else Decimal(valor),
        corpus_fingerprint=corpus,
    )


def populacao(
    valores: list[str | None], *, feature_key: str = "shots_home_5m"
) -> FeaturePopulation:
    """Uma população com os valores dados, um por partida sintética."""
    return FeaturePopulation.of(
        COMPETICAO,
        feature_key,
        [observacao(n, v) for n, v in enumerate(valores)],
    )


def valores_de_zero_a(n: int) -> list[str | None]:
    """`0, 1, 2, …, n-1` — uma distribuição uniforme e conferível à mão."""
    return [str(i) for i in range(n)]


DIA: Final[timedelta] = timedelta(days=1)
