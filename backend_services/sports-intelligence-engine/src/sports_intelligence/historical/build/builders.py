"""Os construtores canônicos — um por família, e nenhum decide qualidade.

CADA UM RECEBE A DECISÃO PRONTA e recusa trabalhar sem ela. Não é cerimônia:
é o que impede um caminho de código construir um fato canônico sem que a
política tenha autorizado — que é a duplicação de regra do §5 chegando pela
porta dos fundos.

O QUE NÃO EXISTE AQUI, e a ausência é declarada (§28, §92):

    CanonicalEventBuilder    nenhum papel semântico carrega evento. Um
                             construtor que nunca recebe evento nenhum seria
                             dívida com aparência de cobertura, e faria
                             `EVENT = 0%` parecer falha da fonte em vez de
                             limite do nosso contrato.

O CONSTRUTOR DE PARTIDA NÃO RESOLVE IDENTIDADE (§27). Ele exige
`MatchIdentityFacts` — que só se constrói com `TeamId`, `SeasonId` e
`CompetitionId` em mãos. Se a identidade não foi provada, não há o que
construir, e a decisão de build correspondente diz isso.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final, final

from sports_intelligence.domain.build.decisions import BuildDecision, CanonicalFactType
from sports_intelligence.domain.build.facts import (
    LineupDraft,
    MatchIdentityFacts,
    ScoreFacts,
)
from sports_intelligence.domain.fusion.models import ObservationSet
from sports_intelligence.domain.matches.lifecycle import MatchLifecycle
from sports_intelligence.domain.matches.lineup import (
    FormationLabel,
    Lineup,
    LineupEntry,
)
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.matches.result import MatchResult, Score
from sports_intelligence.domain.odds.models import (
    CanonicalOddsObservation,
    OddsMarket,
)
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.errors import (
    InvariantViolationError,
    ValidationError,
)
from sports_intelligence.domain.shared.identity import MatchId, PlayerId
from sports_intelligence.domain.shared.provenance import DataProvenance, SourceType
from sports_intelligence.domain.shared.temporal import Instant, ObservationTimes
from sports_intelligence.historical.build.translation import (
    ODDS_ROLE_SELECTION,
    bookmaker_of,
    decimal_odds_of,
)

#: O ÚNICO mercado que a V1 do contrato de odds descreve. Nomeado para que o
#: dia em que houver um segundo seja uma mudança visível, e não um literal
#: escondido numa expressão.
V1_ODDS_MARKET: Final[OddsMarket] = OddsMarket.MATCH_RESULT_1X2

#: O estado em que uma partida entra no corpus histórico construído. NÃO é
#: `HISTORICAL_ACTIVE`: essa promoção é o PR-04.3, e usá-la aqui faria um fato
#: recém-construído ser lido como conhecimento histórico publicado (ADR-0007).
BUILT_LIFECYCLE: Final[MatchLifecycle] = MatchLifecycle.RECONCILED


def _assert_authorized(decision: BuildDecision, family: CoverageFamily) -> None:
    """Recusa construir o que a política não autorizou.

    `InvariantViolationError` E NÃO `ValidationError`: chegar aqui com uma
    família não autorizada não é entrada ruim do usuário — é o orquestrador
    tendo perdido a decisão pelo caminho, que é defeito nosso.
    """
    if not decision.outcome.materializes:
        raise InvariantViolationError(
            f"construção de {family} pedida para uma partida em {decision.outcome} — "
            "a decisão de build é o único contrato entre qualidade e construção, e "
            "ignorá-la aqui recriaria a regra num segundo lugar (§5)",
            context={"match_id": str(decision.match_id), "family": family.value},
        )
    if not decision.includes(family):
        raise InvariantViolationError(
            f"{family} não foi incluída na decisão de {decision.match_id} e mesmo "
            "assim foi pedida — uma família excluída que aparece no corpus é "
            "exatamente o que o §20 existe para impedir",
            context={
                "match_id": str(decision.match_id),
                "excluded": [f.value for f in decision.excluded_families],
            },
        )


@final
@dataclass(frozen=True, slots=True)
class CanonicalMatchBuilder:
    """Constrói o agregado `Match` — e NADA que descreva o depois.

    `Match` NÃO GANHA `result`, `final_score` NEM `winner` (§32). É a decisão
    central do PR-01 e o primeiro write real não pode desfazê-la: o motor
    descreve estados ANTERIORES, e um agregado que carrega o placar deixa
    qualquer caminho que descreva o minuto 63 ler o fim.
    """

    fact_type: ClassVar[CanonicalFactType] = CanonicalFactType.MATCH

    def build(
        self, *, decision: BuildDecision, identity: MatchIdentityFacts
    ) -> Match:
        _assert_authorized(decision, CoverageFamily.MATCH)
        if identity.match_id != decision.match_id:
            raise InvariantViolationError(
                f"identidade de {identity.match_id} usada para construir "
                f"{decision.match_id} — seriam duas partidas viradas uma",
                context={"decision": str(decision.match_id)},
            )
        # MAPEAMENTO EXPLÍCITO, campo a campo (§30). Um `**` aqui aceitaria
        # qualquer chave que a identidade tivesse ganhado e calaria a que ela
        # tivesse perdido.
        return Match(
            id=identity.match_id,
            competition_id=identity.competition_id,
            season_id=identity.season_id,
            regime=identity.regime,
            stage=identity.stage,
            home_team_id=identity.home_team_id,
            away_team_id=identity.away_team_id,
            scheduled_kickoff=identity.scheduled_kickoff,
            lifecycle=BUILT_LIFECYCLE,
            actual_kickoff=identity.actual_kickoff,
            venue=identity.venue,
            neutral_venue=identity.neutral_venue,
        )


@final
@dataclass(frozen=True, slots=True)
class CanonicalResultBuilder:
    """Constrói `MatchResult` — SEPARADO do `Match`, e opcional.

    ELE PODE NÃO PRODUZIR NADA, e é o ponto (§33, §89). Placar ausente devolve
    `None`; um `MatchResult` de `0-0` no lugar seria um empate sem gols que
    ninguém distingue de um empate sem gols de verdade — o defeito mais caro
    que um corpus de futebol pode ter, porque é plausível.
    """

    fact_type: ClassVar[CanonicalFactType] = CanonicalFactType.MATCH_RESULT

    def build(
        self, *, decision: BuildDecision, scores: ScoreFacts
    ) -> MatchResult | None:
        _assert_authorized(decision, CoverageFamily.MATCH)
        if not scores.has_regular_time:
            return None
        assert scores.regular_home is not None  # garantido por has_regular_time
        assert scores.regular_away is not None
        return MatchResult(
            regular_time=Score(home=scores.regular_home, away=scores.regular_away),
            # OS DOIS ESCOPOS SEGUEM `None` (§34). Prorrogação e pênaltis não
            # são deriváveis do tempo normal, e derivá-los inventaria um jogo.
            extra_time=(
                Score(home=scores.extra_home, away=scores.extra_away)
                if scores.extra_home is not None and scores.extra_away is not None
                else None
            ),
            penalties=(
                Score(home=scores.penalties_home, away=scores.penalties_away)
                if scores.penalties_home is not None
                and scores.penalties_away is not None
                else None
            ),
        )


@final
@dataclass(frozen=True, slots=True)
class CanonicalLineupBuilder:
    """Constrói `Lineup` — só com `PlayerId` CANÔNICO.

    NENHUM ID INVENTADO (§36). Nem derivado do nome, nem sorteado, nem
    «temporário até resolver». Os três parecem inofensivos e contaminam
    influência de jogador, força de elenco e grafo tático de forma que não se
    detecta depois, porque tudo continua somando.

    A ESCALAÇÃO É A INICIAL E NÃO MUDA (§37). Substituição é evento; como esta
    fase não constrói eventos, não existe caminho de código que aplique uma
    sobre isto.
    """

    fact_type: ClassVar[CanonicalFactType] = CanonicalFactType.LINEUP

    def build(self, *, decision: BuildDecision, draft: LineupDraft) -> Lineup:
        _assert_authorized(decision, CoverageFamily.LINEUP)
        if draft.match_id != decision.match_id:
            raise InvariantViolationError(
                f"escalação de {draft.match_id} numa decisão de {decision.match_id}"
            )
        if not draft.is_fully_resolved:
            raise InvariantViolationError(
                f"escalação de {draft.team_id} com {len(draft.unresolved)} jogador(es) "
                "sem identidade canônica. Construí-la exigiria inventar um `PlayerId`, "
                "e a família deveria ter sido excluída pela política (§36, §91)",
                context={
                    "match_id": str(draft.match_id),
                    "unresolved": list(draft.unresolved[:8]),
                },
            )
        entradas = tuple(
            LineupEntry(
                # `is_fully_resolved` já garantiu; o `assert` documenta ao
                # checador de tipos o que a guarda acima provou.
                player_id=_resolved(entrada.player_id),
                status=entrada.status,
                shirt_number=entrada.shirt_number,
                position=entrada.position,
                captain=entrada.captain,
            )
            for entrada in draft.entries
        )
        return Lineup.confirm(
            match_id=draft.match_id,
            team_id=draft.team_id,
            entries=entradas,
            formation=_formacao(draft.formation),
        )


@final
@dataclass(frozen=True, slots=True)
class CanonicalOddsBuilder:
    """Constrói o CONJUNTO de observações de odds. Nunca uma cotação média.

    `Bet365 @ 2.00` E `Pinnacle @ 2.05` VIRAM DUAS OBSERVAÇÕES (§42, §93).
    `2.025` é um preço que casa nenhuma ofereceu, e ele apagaria justamente a
    dispersão entre casas — que é o sinal que o Odds Intelligence vai ler.

    UMA OBSERVAÇÃO POR SELEÇÃO. Uma linha de fonte com `ODDS_HOME`,
    `ODDS_DRAW` e `ODDS_AWAY` descreve três lados do MESMO mercado, e cada
    lado é uma cotação própria — colapsá-los perderia dois terços do mercado.
    """

    fact_type: ClassVar[CanonicalFactType] = CanonicalFactType.ODDS_OBSERVATION

    def build(
        self,
        *,
        decision: BuildDecision,
        observations: ObservationSet,
        match_id: MatchId,
        ingested_at: Instant,
    ) -> tuple[CanonicalOddsObservation, ...]:
        _assert_authorized(decision, CoverageFamily.ODDS)
        construidas: list[CanonicalOddsObservation] = []
        for observacao in observations.observations:
            casa = bookmaker_of(observacao)
            if casa is None:
                # SEM CASA NÃO HÁ OBSERVAÇÃO. A casa faz parte da identidade
                # da cotação (§43); sem ela, duas casas seriam a mesma coisa e
                # uma sumiria como duplicata.
                continue
            for papel, selecao in ODDS_ROLE_SELECTION.items():
                bruto = observacao.values.get(papel.value)
                if bruto is None:
                    continue
                cotacao = decimal_odds_of(bruto)
                if cotacao is None:
                    continue
                construidas.append(
                    CanonicalOddsObservation(
                        match_id=match_id,
                        bookmaker=casa,
                        market=V1_ODDS_MARKET,
                        selection=selecao,
                        decimal_odds=cotacao,
                        provenance=DataProvenance(
                            source_type=SourceType.OPEN_DATA,
                            provider_id=observacao.provider_id,
                            source_record_id=str(observacao.record_ref),
                            times=ObservationTimes.at_once(ingested_at),
                            license_class=observacao.license_class,
                        ),
                        # `None` QUANDO A FONTE NÃO DECLARA (§44). Nunca o
                        # kickoff, nunca `now()`: os dois seriam um fato
                        # inventado com aparência de fato.
                        observed_at=observacao.observed_at,
                    )
                )
        return tuple(construidas)


def _resolved(player_id: PlayerId | None) -> PlayerId:
    """Devolve o id, e explode se ele for `None`.

    A guarda de `is_fully_resolved` já rodou; isto existe para que o `None`
    impossível não vire um id inventado se alguém reordenar o código — e para
    que o checador de tipos saiba o que a guarda provou.
    """
    if player_id is None:
        raise InvariantViolationError(
            "jogador sem identidade canônica chegou ao construtor de escalação"
        )
    return player_id


def _formacao(raw: str | None) -> FormationLabel | None:
    """A formação declarada, ou `None`.

    RÓTULO INVÁLIDO VIRA AUSÊNCIA e não erro. Uma fonte que publica `4231`
    sem hífens não deveria derrubar a escalação inteira — e inferir a formação
    contando posições erra sistematicamente (PR-01).
    """
    if raw is None or not raw.strip():
        return None
    try:
        return FormationLabel(raw.strip())
    except (ValidationError, ValueError):
        return None
