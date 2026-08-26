"""O cenário do PR-05.3 — uma partida montada para exercitar cada janela.

POR QUE UM TERCEIRO CENÁRIO. O do PR-05.1 exercita causalidade; o do PR-05.2
exercita transições de estado com onze de cada lado. Nenhum dos dois tem
finalizações suficientes, nem escanteios, nem xG ausente ao lado de xG zero —
e sem isso as janelas móveis não teriam o que contar.

A HISTÓRIA, minuto a minuto (tudo no SECOND_HALF salvo onde dito):

    FIRST_HALF 44'   chute da casa            ← só existe para provar §154:
    FIRST_HALF 45+2  chute da casa               janela não atravessa período

    46'  escanteio da casa
    52'  chute da casa                        xg 0.05
    53'  GOL da casa                          (1-0)
    56'  chute de fora                        xg 0.09
    58'  chute da casa   NO ALVO              xg 0.30
    59'  chute da casa   fora                 xg 0.11
    60'  chute de fora   NO ALVO              xg 0.21     ← FRONTEIRA de 5m
    61'  escanteio da casa
    61'  chute da casa   NO ALVO              xg 0.42
    62'  chute de fora   fora                 xg 0.00     ← zero OBSERVADO
    63'  chute da casa   NO ALVO              xg 0.30
    ---------------------- corte de referência: 63' ----------------------
    64'  chute da casa                        ← futuro
    70'  GOL da casa                          ← futuro

O CORTE DE REFERÊNCIA É 63'. Os valores esperados estão escritos à mão em
`ESPERADO_63`, e não calculados pela função sob teste (§167): um teste que
computa o esperado com o código que testa prova apenas que o código concorda
consigo mesmo.

O EVENTO DOS 60' É A FRONTEIRA (§151). Num corte de 63 com janela de 3
minutos, o intervalo é `(60, 63]` — e ele fica de FORA por um segundo de
definição. Na janela de 5 minutos, `(58, 63]`, ele entra.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Final

from sports_intelligence.domain.events.canonical import CanonicalMatchEvent, EventStatus
from sports_intelligence.domain.events.details import (
    BodyPart,
    CardDetail,
    CardType,
    EventDetail,
    ShotDetail,
    ShotOutcome,
    SubstitutionDetail,
)
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.features.availability import TemporalAvailabilityPolicy
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
from sports_intelligence.domain.features.projection import EventKnowledge
from sports_intelligence.domain.features.snapshot import FeatureSnapshot
from sports_intelligence.domain.features.space import FeatureSpaceDefinition
from sports_intelligence.domain.features.state.builder import (
    CanonicalMatchStateInput,
    HistoricalMatchStateBuilder,
)
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.matches.lineup import Lineup
from sports_intelligence.domain.matches.result import MatchResult
from sports_intelligence.domain.odds.models import CanonicalOddsObservation
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.feature_value import FeatureValue
from sports_intelligence.domain.shared.identity import MatchId, PlayerId, TeamId
from sports_intelligence.domain.shared.quality import DataQuality
from sports_intelligence.domain.shared.temporal import Instant, MatchClock, Period
from tests.support.feature_fixtures import (
    CASA,
    FORA,
    PARTIDA,
    corte,
    origem,
    partida,
    procedencia_do_cenario,
    relogio_de_parede,
)
from tests.support.state_fixtures import (
    CASA_TITULARES,
    FORA_TITULARES,
    escalacoes,
)

#: A raiz das identidades deste cenário — separada das outras duas para que
#: nenhum evento de um cenário colida com outro por acidente.
_RAIZ: Final[uuid.UUID] = uuid.UUID("00000000-0000-5000-8000-0000000053a3")

TODAS_AS_FAMILIAS: Final[frozenset[CoverageFamily]] = frozenset(
    {CoverageFamily.MATCH, CoverageFamily.LINEUP, CoverageFamily.EVENT}
)


def id_de(rotulo: str) -> uuid.UUID:
    return uuid.uuid5(_RAIZ, rotulo)


def evento(
    rotulo: str,
    *,
    tipo: EventType,
    minuto: int,
    periodo: Period = Period.SECOND_HALF,
    stoppage: int = 0,
    sequencia: int = 0,
    time: TeamId | None = CASA,
    jogador_id: PlayerId | None = None,
    outcome: ShotOutcome | None = None,
    xg: str | None = None,
    sem_detalhe: bool = False,
    cartao: CardType | None = None,
    substituicao: tuple[PlayerId, PlayerId] | None = None,
    status: EventStatus = EventStatus.ACTIVE,
    revision: int = 1,
    supersedes: uuid.UUID | None = None,
    match_id: MatchId = PARTIDA,
    conhecido_em: Instant | None = None,
) -> CanonicalMatchEvent:
    """Um evento do cenário.

    `sem_detalhe=True` PRODUZ UMA FINALIZAÇÃO SEM `ShotDetail` — o caso do §44
    e do §158. O modelo canônico permite: `detail` é opcional, e um provedor
    que só publica «houve um chute» produz exatamente isto.
    """
    detalhe: EventDetail | None = None
    if tipo is EventType.CARD:
        detalhe = CardDetail(card_type=cartao or CardType.YELLOW)
    elif tipo is EventType.SUBSTITUTION and substituicao is not None:
        detalhe = SubstitutionDetail(player_out=substituicao[0], player_in=substituicao[1])
    elif tipo in (EventType.SHOT, EventType.GOAL) and not sem_detalhe:
        detalhe = ShotDetail(
            outcome=outcome
            or (ShotOutcome.GOAL if tipo is EventType.GOAL else ShotOutcome.OFF_TARGET),
            body_part=BodyPart.RIGHT_FOOT,
            xg=None if xg is None else FeatureValue.of(float(Decimal(xg))),
        )
    if tipo.requires_player and jogador_id is None:
        jogador_id = CASA_TITULARES[8] if time == CASA else FORA_TITULARES[8]
    if not tipo.requires_team:
        time = None
    return CanonicalMatchEvent(
        id=id_de(rotulo),
        match_id=match_id,
        type=tipo,
        clock=MatchClock(period=periodo, minute=minuto, stoppage=stoppage),
        sequence=sequencia,
        provenance=procedencia_do_cenario(conhecido_em or relogio_de_parede(minuto)),
        quality=DataQuality(
            completeness=1.0, consistency=1.0, freshness=1.0, identity_confidence=1.0
        ),
        team_id=time,
        player_id=jogador_id,
        start_location=None,
        detail=detalhe,
        revision=revision,
        supersedes=supersedes,
        status=status,
    )


# ------------------------------------------------------------- a história --


def primeiro_tempo() -> tuple[CanonicalMatchEvent, ...]:
    """Os fatos do PRIMEIRO tempo — eles existem para NÃO serem contados.

    §154 — a janela é local ao período. Um corte no segundo tempo não pode
    enxergá-los, por mais perto que estejam no relógio da TV.
    """
    return (
        evento(
            "ht-chute-44",
            tipo=EventType.SHOT,
            minuto=44,
            periodo=Period.FIRST_HALF,
            sequencia=1,
            xg="0.50",
            outcome=ShotOutcome.SAVED,
        ),
        evento(
            "ht-chute-45mais2",
            tipo=EventType.SHOT,
            minuto=45,
            stoppage=2,
            periodo=Period.FIRST_HALF,
            sequencia=2,
            xg="0.60",
            outcome=ShotOutcome.SAVED,
        ),
    )


def segundo_tempo_ate_o_corte() -> tuple[CanonicalMatchEvent, ...]:
    """Os fatos do segundo tempo ATÉ os 63 minutos, inclusive."""
    return (
        evento("st-escanteio-46", tipo=EventType.CORNER, minuto=46, sequencia=10),
        evento("st-chute-52", tipo=EventType.SHOT, minuto=52, sequencia=11, xg="0.05"),
        evento("st-gol-53", tipo=EventType.GOAL, minuto=53, sequencia=12, xg="0.40"),
        evento(
            "st-chute-56",
            tipo=EventType.SHOT,
            minuto=56,
            sequencia=13,
            time=FORA,
            xg="0.09",
        ),
        evento(
            "st-chute-58",
            tipo=EventType.SHOT,
            minuto=58,
            sequencia=14,
            outcome=ShotOutcome.SAVED,
            xg="0.30",
        ),
        evento("st-chute-59", tipo=EventType.SHOT, minuto=59, sequencia=15, xg="0.11"),
        evento(
            "st-chute-60",
            tipo=EventType.SHOT,
            minuto=60,
            sequencia=16,
            time=FORA,
            outcome=ShotOutcome.SAVED,
            xg="0.21",
        ),
        evento("st-escanteio-61", tipo=EventType.CORNER, minuto=61, sequencia=17),
        evento(
            "st-chute-61",
            tipo=EventType.SHOT,
            minuto=61,
            sequencia=18,
            outcome=ShotOutcome.SAVED,
            xg="0.42",
        ),
        # xG ZERO OBSERVADO (§48). Ele é um valor legítimo, e é diferente de
        # xG ausente — que o cenário do §157 injeta à parte.
        evento(
            "st-chute-62",
            tipo=EventType.SHOT,
            minuto=62,
            sequencia=19,
            time=FORA,
            xg="0.00",
        ),
        evento(
            "st-chute-63",
            tipo=EventType.SHOT,
            minuto=63,
            sequencia=20,
            outcome=ShotOutcome.SAVED,
            xg="0.30",
        ),
    )


def futuro() -> tuple[CanonicalMatchEvent, ...]:
    """Os fatos POSTERIORES ao corte — nenhum pode aparecer no snapshot."""
    return (
        evento("st-chute-64", tipo=EventType.SHOT, minuto=64, sequencia=30, xg="0.70"),
        evento("st-gol-70", tipo=EventType.GOAL, minuto=70, sequencia=31, xg="0.55"),
    )


def historia() -> tuple[CanonicalMatchEvent, ...]:
    """A história canônica COMPLETA, como o corpus a guarda."""
    return (*primeiro_tempo(), *segundo_tempo_ate_o_corte(), *futuro())


# --------------------------------------------------------------- entrada --


def entrada(
    *,
    eventos: tuple[CanonicalMatchEvent, ...] | None = None,
    lineups: tuple[Lineup, ...] | None = None,
    families: frozenset[CoverageFamily] | None = None,
    odds: tuple[CanonicalOddsObservation, ...] = (),
    result: MatchResult | None = None,
    knowledge: EventKnowledge | None = None,
) -> CanonicalMatchStateInput:
    """Os insumos de estado do cenário.

    `odds` É VAZIO POR PADRÃO e existe no parâmetro desde o PR-05.4: o cenário
    de features cruas não tem mercado, e o de mercado precisa das mesmas
    partidas e dos mesmos eventos. Duas entradas divergiriam no primeiro
    evento acrescentado a uma delas.
    """
    return CanonicalMatchStateInput(
        match=partida(),
        competition_code="PREMIER_LEAGUE",
        season_label="2025/26",
        published_families=TODAS_AS_FAMILIAS if families is None else families,
        candidate_events=historia() if eventos is None else eventos,
        lineups=escalacoes() if lineups is None else lineups,
        odds=odds,
        result=result,
        knowledge=knowledge or EventKnowledge(),
    )


def espaco() -> FeatureSpaceDefinition:
    return match_state_raw_space_v1()


def catalogo() -> ProductionFeatureCatalog:
    return production_feature_catalog()


def contexto(
    entrada_: CanonicalMatchStateInput | None = None,
    *,
    as_of: FeatureAsOf | None = None,
    policy: TemporalAvailabilityPolicy | None = None,
    families: frozenset[CoverageFamily] | None = None,
) -> MatchFeatureExtractionContext:
    """O contexto de extração — passando pelo construtor de estado (§5)."""
    politica = policy or TemporalAvailabilityPolicy.default()
    fonte = origem(families=families or TODAS_AS_FAMILIAS)
    build = HistoricalMatchStateBuilder(policy=politica).build(
        entrada_ or entrada(), as_of=as_of or corte(), source=fonte
    )
    return MatchFeatureExtractionContext.of(
        build, space=espaco(), catalog=catalogo(), source=fonte, policy=politica
    )


def extrair(
    entrada_: CanonicalMatchStateInput | None = None,
    *,
    as_of: FeatureAsOf | None = None,
    policy: TemporalAvailabilityPolicy | None = None,
    families: frozenset[CoverageFamily] | None = None,
) -> FeatureSnapshot:
    return MatchStateFeatureExtractor().extract(
        contexto(entrada_, as_of=as_of, policy=policy, families=families)
    )


# -------------------------------------------------- os valores ESPERADOS --
#
# ESCRITOS À MÃO A PARTIR DA TABELA DO CABEÇALHO (§167). Conferir o motor
# contra números que o próprio motor produziu provaria que ele é consistente,
# e não que está certo.
#
# O CORTE É `SECOND_HALF 63'`. As janelas, em minutos locais do segundo tempo:
#
#     1m   (62, 63]   chute 63 casa
#     3m   (60, 63]   escanteio 61 casa · chute 61 casa · chute 62 fora ·
#                     chute 63 casa
#     5m   (58, 63]   chute 59 casa · chute 60 fora · escanteio 61 casa ·
#                     chute 61 casa · chute 62 fora · chute 63 casa
#     10m  (53, 63]   chute 56 fora · chute 58 casa · e tudo da janela de 5m
#
# O CHUTE DOS 58 FICA DE FORA DA JANELA DE 5m: `(58, 63]` é aberto no início.
# O DOS 53 (gol) fica de fora da de 10m pelo mesmo motivo.

ESPERADO_63: Final[dict[str, float]] = {
    # ---- estado
    "clock_period_order": float(Period.SECOND_HALF.order),
    "clock_minute": 63.0,
    "clock_stoppage": 0.0,
    "score_home": 1.0,
    "score_away": 0.0,
    "score_difference": 1.0,
    "players_on_field_home": 11.0,
    "players_on_field_away": 11.0,
    "manpower_difference": 0.0,
    "yellow_cards_home": 0.0,
    "yellow_cards_away": 0.0,
    "dismissals_home": 0.0,
    "dismissals_away": 0.0,
    "substitutions_home": 0.0,
    "substitutions_away": 0.0,
    # ---- janela de 1 minuto: (62, 63]
    "shots_home_1m": 1.0,
    "shots_away_1m": 0.0,
    "shots_diff_1m": 1.0,
    "shots_on_target_home_1m": 1.0,
    "shots_on_target_away_1m": 0.0,
    "shots_on_target_diff_1m": 1.0,
    "xg_home_1m": 0.30,
    "xg_away_1m": 0.0,
    "xg_diff_1m": 0.30,
    "goals_home_1m": 0.0,
    "goals_away_1m": 0.0,
    "goals_diff_1m": 0.0,
    "corners_home_1m": 0.0,
    "corners_away_1m": 0.0,
    "corners_diff_1m": 0.0,
    # ---- janela de 3 minutos: (60, 63]
    "shots_home_3m": 2.0,  # 61, 63
    "shots_away_3m": 1.0,  # 62
    "shots_diff_3m": 1.0,
    "shots_on_target_home_3m": 2.0,
    "shots_on_target_away_3m": 0.0,
    "shots_on_target_diff_3m": 2.0,
    "xg_home_3m": 0.72,  # 0.42 + 0.30
    "xg_away_3m": 0.0,  # 0.00 observado
    "xg_diff_3m": 0.72,
    "goals_home_3m": 0.0,
    "goals_away_3m": 0.0,
    "goals_diff_3m": 0.0,
    "corners_home_3m": 1.0,
    "corners_away_3m": 0.0,
    "corners_diff_3m": 1.0,
    # ---- janela de 5 minutos: (58, 63]
    "shots_home_5m": 3.0,  # 59, 61, 63
    "shots_away_5m": 2.0,  # 60, 62
    "shots_diff_5m": 1.0,
    "shots_on_target_home_5m": 2.0,  # 61, 63
    "shots_on_target_away_5m": 1.0,  # 60
    "shots_on_target_diff_5m": 1.0,
    "xg_home_5m": 0.83,  # 0.11 + 0.42 + 0.30
    "xg_away_5m": 0.21,  # 0.21 + 0.00
    "xg_diff_5m": 0.62,
    "goals_home_5m": 0.0,
    "goals_away_5m": 0.0,
    "goals_diff_5m": 0.0,
    "corners_home_5m": 1.0,
    "corners_away_5m": 0.0,
    "corners_diff_5m": 1.0,
    # ---- janela de 10 minutos: (53, 63]
    "shots_home_10m": 4.0,  # 58, 59, 61, 63
    "shots_away_10m": 3.0,  # 56, 60, 62
    "shots_diff_10m": 1.0,
    "shots_on_target_home_10m": 3.0,  # 58, 61, 63
    "shots_on_target_away_10m": 1.0,  # 60
    "shots_on_target_diff_10m": 2.0,
    "xg_home_10m": 1.13,  # 0.30 + 0.11 + 0.42 + 0.30
    "xg_away_10m": 0.30,  # 0.09 + 0.21 + 0.00
    "xg_diff_10m": 0.83,
    "goals_home_10m": 0.0,  # o gol dos 53 está FORA de (53, 63]
    "goals_away_10m": 0.0,
    "goals_diff_10m": 0.0,
    # O escanteio dos 46 está FORA de (53, 63]; só o dos 61 entra.
    "corners_home_10m": 1.0,
    "corners_away_10m": 0.0,
    "corners_diff_10m": 1.0,
}
