"""A partida: o agregado central, e o que ele deliberadamente NÃO sabe.

`Match` NÃO CARREGA O RESULTADO. Esta é a decisão mais importante do módulo, e
ela contraria o instinto: uma partida "tem" um placar.

Mas o placar é informação PÓS-JOGO, e o motor descreve estados ANTERIORES. Se
o agregado carrega o resultado, qualquer caminho que descreva o minuto 63
pode lê-lo — e a descrição passa a conter a resposta. Nada falha; a
similaridade fica excelente e não descreve nada (ADR-0007, Constituição §1).

Então:

    Match          quem joga, quando, sob que regime e fase — o que se sabe ANTES
    MatchResult    o que aconteceu — observação pós-jogo, ligada por id

A separação é o que torna o replay honesto: reconstruir o estado do minuto 63
não tem como enxergar o fim, porque o fim não está no objeto.

`MatchIdentityCandidate` PREPARA A FUSÃO SEM FAZÊ-LA. Ele descreve os
elementos que futuramente identificam a mesma partida entre provedores, e
NÃO produz merge — deliberadamente. Merge automático por semelhança é como
duas partidas diferentes viram uma.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self, final

from sports_intelligence.domain.competitions.models import CompetitionRegime, Stage
from sports_intelligence.domain.matches.lifecycle import MatchLifecycle
from sports_intelligence.domain.shared.identity import (
    CompetitionId,
    MatchId,
    SeasonId,
    TeamId,
)
from sports_intelligence.domain.shared.temporal import Instant


@final
@dataclass(frozen=True, slots=True)
class Venue:
    """Onde se joga. Sem coordenadas: elas não são usadas por nada ainda, e
    uma abstração sem requisito conhecido é dívida (Constituição §15)."""

    name: str
    city: str | None = None
    country: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("venue sem nome")
        if self.country is not None and (len(self.country) != 2 or not self.country.isupper()):
            raise ValueError(f"country {self.country!r} inválido: ISO-3166 alpha-2 maiúsculo")


@final
@dataclass(frozen=True, slots=True)
class Match:
    """Uma partida, do ponto de vista do que se sabe ANTES dela.

    Imutável. Mudança de estado passa por método explícito, que devolve uma
    partida nova — o objeto anterior continua sendo o registro do que se sabia.
    """

    id: MatchId
    competition_id: CompetitionId
    season_id: SeasonId
    regime: CompetitionRegime
    stage: Stage
    home_team_id: TeamId
    away_team_id: TeamId
    scheduled_kickoff: Instant
    lifecycle: MatchLifecycle
    actual_kickoff: Instant | None = None
    venue: Venue | None = None
    neutral_venue: bool = False

    def __post_init__(self) -> None:
        if self.home_team_id == self.away_team_id:
            raise ValueError(
                f"mandante e visitante são o mesmo time ({self.home_team_id}) — "
                "quase sempre resolução de identidade que fundiu dois clubes"
            )
        if not self.regime.covers(self.scheduled_kickoff):
            raise ValueError(
                f"o regime {self.regime.code} não cobre o horário marcado "
                f"({self.scheduled_kickoff.isoformat()}): a partida aconteceu sob outro formato"
            )
        if self.actual_kickoff is not None and not self.regime.covers(self.actual_kickoff):
            raise ValueError(
                f"o regime {self.regime.code} não cobre o pontapé real "
                f"({self.actual_kickoff.isoformat()})"
            )

    @classmethod
    def register(
        cls,
        *,
        competition_id: CompetitionId,
        season_id: SeasonId,
        regime: CompetitionRegime,
        stage: Stage,
        home_team_id: TeamId,
        away_team_id: TeamId,
        scheduled_kickoff: Instant,
        venue: Venue | None = None,
        neutral_venue: bool = False,
    ) -> Self:
        """Uma partida recém-descoberta.

        Nasce em `DISCOVERED` porque é isso que ela é: alguma fonte disse que
        existe. Confirmá-la é uma transição, não um construtor diferente.

        Id SORTEADO. Derivá-lo de (competição, temporada, times, data) seria
        conveniente e faria duas partidas do mesmo par no mesmo dia — que
        acontece em torneios — colidirem. A ligação entre observações de
        provedores diferentes é `MatchIdentityCandidate`, resolvida depois.
        """
        return cls(
            id=MatchId.new(),
            competition_id=competition_id,
            season_id=season_id,
            regime=regime,
            stage=stage,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            scheduled_kickoff=scheduled_kickoff,
            lifecycle=MatchLifecycle.DISCOVERED,
            venue=venue,
            neutral_venue=neutral_venue,
        )

    def with_lifecycle(self, target: MatchLifecycle) -> Self:
        """A partida no estado novo.

        NÃO VALIDA A TRANSIÇÃO AQUI. Quem valida é `transition_to`, no módulo
        de lifecycle, porque a transição precisa de instante e motivo — e um
        método que aceitasse qualquer alvo seria a porta de trás que o grafo
        fechado existe para fechar. O caso de uso chama os dois.
        """
        return type(self)(
            id=self.id,
            competition_id=self.competition_id,
            season_id=self.season_id,
            regime=self.regime,
            stage=self.stage,
            home_team_id=self.home_team_id,
            away_team_id=self.away_team_id,
            scheduled_kickoff=self.scheduled_kickoff,
            lifecycle=target,
            actual_kickoff=self.actual_kickoff,
            venue=self.venue,
            neutral_venue=self.neutral_venue,
        )

    def with_actual_kickoff(self, at: Instant) -> Self:
        """O pontapé de verdade, que raramente é o marcado."""
        return type(self)(
            id=self.id,
            competition_id=self.competition_id,
            season_id=self.season_id,
            regime=self.regime,
            stage=self.stage,
            home_team_id=self.home_team_id,
            away_team_id=self.away_team_id,
            scheduled_kickoff=self.scheduled_kickoff,
            lifecycle=self.lifecycle,
            actual_kickoff=at,
            venue=self.venue,
            neutral_venue=self.neutral_venue,
        )

    def involves(self, team_id: TeamId) -> bool:
        return team_id in (self.home_team_id, self.away_team_id)

    def opponent_of(self, team_id: TeamId) -> TeamId:
        if team_id == self.home_team_id:
            return self.away_team_id
        if team_id == self.away_team_id:
            return self.home_team_id
        raise ValueError(f"{team_id} não joga esta partida")

    @property
    def kickoff(self) -> Instant:
        """O melhor instante conhecido: o real quando existe, o marcado antes.

        Explícito porque a escolha importa: usar o marcado depois de o jogo
        começar produz um relógio errado; exigir o real antes do jogo torna a
        partida inutilizável na janela pré-jogo.
        """
        return self.actual_kickoff or self.scheduled_kickoff


@final
@dataclass(frozen=True, slots=True)
class MatchIdentityCandidate:
    """Os elementos que PODEM identificar a mesma partida entre provedores.

    NÃO PRODUZ MERGE, e a ausência é o contrato. Não há `matches()`, não há
    `similarity_to()`, não há `merge_with()`. Este objeto é a descrição do
    problema; a solução é o Identity Resolution Engine, num PR próprio, com
    regras que podem falhar e pedir revisão humana.

    Oferecer um `==` aqui convidaria alguém a fundir por igualdade — e duas
    partidas do mesmo par no mesmo dia existem em torneios de ida e volta com
    jogo único adiado.
    """

    competition_id: CompetitionId
    season_id: SeasonId
    home_team_id: TeamId
    away_team_id: TeamId
    kickoff: Instant
    stage: Stage | None = None

    def __post_init__(self) -> None:
        if self.home_team_id == self.away_team_id:
            raise ValueError("candidato com mandante e visitante iguais")

    @classmethod
    def of(cls, match: Match) -> Self:
        return cls(
            competition_id=match.competition_id,
            season_id=match.season_id,
            home_team_id=match.home_team_id,
            away_team_id=match.away_team_id,
            kickoff=match.kickoff,
            stage=match.stage,
        )
