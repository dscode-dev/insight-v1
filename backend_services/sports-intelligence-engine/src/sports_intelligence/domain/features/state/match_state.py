"""`HistoricalMatchState` — como a partida ESTAVA num instante.

    HistoricalMatchState_t = Reduce(InitialState, EffectiveCanonicalFacts<=t)

ELE NÃO É UM VETOR (§5, §173):

    HistoricalMatchState   representação ESTRUTURAL e tipada da realidade
    MatchStateVector       representação MATEMÁTICA derivada dela

O primeiro tem placar, elenco em campo, cartões, substituições aplicadas e
cotações conhecidas — cada um com disponibilidade própria e procedência. O
segundo é uma lista de números com eixos fixos, e ele não existe ainda.

A IDENTIDADE INCLUI A ORIGEM (§8, §70, §71). Dois estados só são comparáveis
quando se sabe de qual corpus e sob qual causalidade foram reconstruídos —
por isso a impressão depende de:

    corpus_fingerprint · temporal_policy_fingerprint · as_of · conteúdo

Se o corpus mudar, a identidade muda mesmo que o estado observável pareça
igual: o «parece igual» seria coincidência, e reprodutibilidade não se apoia em
coincidência.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final, Self, final

from sports_intelligence.domain.features.availability import (
    FeatureAvailability,
    TemporalAvailabilityPolicy,
)
from sports_intelligence.domain.features.context import CorpusSource
from sports_intelligence.domain.features.state.components import (
    DisciplinaryState,
    EventStructuralState,
    OddsState,
    OnFieldState,
    ScoreState,
    SubstitutionState,
)
from sports_intelligence.domain.features.state.issues import StateIssue
from sports_intelligence.domain.features.state.provenance import MatchStateProvenance
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.shared.canonical import canonical_json, instant_text
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import (
    CompetitionId,
    MatchId,
    SeasonId,
    TeamId,
)
from sports_intelligence.domain.shared.temporal import Instant

#: O algoritmo da impressão do estado. Nomeado como os outros: dois hex de 64
#: caracteres produzidos por construções diferentes são indistinguíveis.
STATE_FINGERPRINT_ALGORITHM: Final[str] = "match-state-sha256-v1"


@final
@dataclass(frozen=True, slots=True)
class MatchStateIdentity:
    """De qual partida é este estado (§7).

    NADA É RESOLVIDO AQUI. Os identificadores vêm do corpus como estão; o motor
    de estado não consulta resolução de identidade nem clube atual de jogador
    (§109, §110).
    """

    match_id: MatchId
    competition_id: CompetitionId
    season_id: SeasonId
    home_team_id: TeamId
    away_team_id: TeamId

    def as_canonical(self) -> dict[str, str]:
        return {
            "away_team_id": str(self.away_team_id),
            "competition_id": str(self.competition_id),
            "home_team_id": str(self.home_team_id),
            "match_id": str(self.match_id),
            "season_id": str(self.season_id),
        }


@final
@dataclass(frozen=True, slots=True)
class MatchContext:
    """O contexto ESTRUTURAL da partida (§9).

    SÓ O QUE O CORPUS JÁ PUBLICA. Competição, temporada, fase, mando, local e
    horário marcado. Nada de estatística de contexto — «média de gols da
    competição» é feature, tem população, janela e versão.
    """

    competition_code: str
    season_label: str
    stage: str | None = None
    venue: str | None = None
    neutral_venue: bool = False
    scheduled_kickoff: Instant | None = None

    def as_canonical(self) -> dict[str, object]:
        return {
            "competition_code": self.competition_code,
            "neutral_venue": self.neutral_venue,
            "scheduled_kickoff": (
                None if self.scheduled_kickoff is None else instant_text(self.scheduled_kickoff)
            ),
            "season_label": self.season_label,
            "stage": self.stage,
            "venue": self.venue,
        }


@final
@dataclass(frozen=True, slots=True)
class HistoricalMatchState:
    """O estado reconstruído — imutável, identificável e explicável.

    A DISPONIBILIDADE É POR COMPONENTE (§54, §55). O estado global existe
    mesmo com partes ausentes: uma partida sem cotações publicadas continua
    tendo placar; uma sem escalação continua tendo cartões. Rejeitar a partida
    inteira por causa de uma família faria o motor descartar o que ele tem.
    """

    identity: MatchStateIdentity
    context: MatchContext
    as_of: FeatureAsOf
    source: CorpusSource
    policy_version: str
    policy_fingerprint: str
    score: ScoreState
    on_field: OnFieldState
    discipline: DisciplinaryState
    substitutions: SubstitutionState
    events: EventStructuralState
    odds: OddsState
    provenance: MatchStateProvenance
    issues: tuple[StateIssue, ...] = ()

    def __post_init__(self) -> None:
        if self.identity.match_id != self.as_of.match_id:
            raise ValidationError(
                f"estado de {self.identity.match_id} com corte de {self.as_of.match_id}"
            )

    @classmethod
    def of(
        cls,
        *,
        identity: MatchStateIdentity,
        context: MatchContext,
        as_of: FeatureAsOf,
        source: CorpusSource,
        policy: TemporalAvailabilityPolicy,
        score: ScoreState,
        on_field: OnFieldState,
        discipline: DisciplinaryState,
        substitutions: SubstitutionState,
        events: EventStructuralState,
        odds: OddsState,
        provenance: MatchStateProvenance,
        issues: tuple[StateIssue, ...] = (),
    ) -> Self:
        return cls(
            identity=identity,
            context=context,
            as_of=as_of,
            source=source,
            policy_version=str(policy.version),
            policy_fingerprint=policy.fingerprint,
            score=score,
            on_field=on_field,
            discipline=discipline,
            substitutions=substitutions,
            events=events,
            odds=odds,
            provenance=provenance,
            issues=tuple(sorted(issues)),
        )

    # ----------------------------------------------------- leitura --

    @property
    def availability(self) -> dict[str, FeatureAvailability]:
        """A disponibilidade de cada componente, num mapa legível (§54)."""
        return {
            "discipline": self.discipline.home.availability,
            "events": self.events.availability,
            "odds": self.odds.availability,
            "on_field": self.on_field.home.availability,
            "score": self.score.availability,
            "substitutions": self.substitutions.availability,
        }

    @property
    def is_partial(self) -> bool:
        """Se algum componente não pôde ser afirmado (§19 do relatório, §105)."""
        return any(not a.is_available for a in self.availability.values())

    @property
    def degraded_issues(self) -> tuple[StateIssue, ...]:
        from sports_intelligence.domain.features.state.issues import StateIssueSeverity

        return tuple(i for i in self.issues if i.severity is StateIssueSeverity.DEGRADED)

    # -------------------------------------------------- impressão --

    def as_canonical(self) -> dict[str, object]:
        """A forma canônica do estado (§64, §65).

        O QUE NÃO ENTRA: id de execução, carimbo de criação, id de processo, id
        de linha de banco. Eles mudam entre duas reconstruções do MESMO estado,
        e um estado que mudasse de identidade por ter sido recalculado não
        serviria para comparar nada.

        A PROCEDÊNCIA ENTRA, e é uma decisão: dois estados com o mesmo placar
        obtido de gols DIFERENTES não são o mesmo estado — a coincidência
        numérica não os torna iguais.
        """
        return {
            "algorithm": STATE_FINGERPRINT_ALGORITHM,
            "as_of": self.as_of.as_canonical(),
            "availability": {
                nome: estado.value for nome, estado in sorted(self.availability.items())
            },
            "context": self.context.as_canonical(),
            "discipline": self.discipline.as_canonical(),
            "events": self.events.as_canonical(),
            "identity": self.identity.as_canonical(),
            "issues": [i.as_canonical() for i in self.issues],
            "odds": self.odds.as_canonical(),
            "on_field": self.on_field.as_canonical(),
            "provenance": self.provenance.as_canonical(),
            "score": self.score.as_canonical(),
            "source": self.source.as_canonical(),
            "substitutions": self.substitutions.as_canonical(),
            "temporal_policy": {
                "fingerprint": self.policy_fingerprint,
                "version": self.policy_version,
            },
        }

    @property
    def fingerprint(self) -> str:
        """A impressão SEMÂNTICA do estado (§63)."""
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def __str__(self) -> str:
        parcial = " (parcial)" if self.is_partial else ""
        return (
            f"{self.identity.match_id} @ {self.as_of.position}: "
            f"{self.score} · {self.on_field}{parcial}"
        )
