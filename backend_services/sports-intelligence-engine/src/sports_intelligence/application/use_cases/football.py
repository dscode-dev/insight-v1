"""Os casos de uso mínimos que provam o domínio.

POR QUE ELES EXISTEM NESTE PR. Sem um caso de uso, os invariantes do domínio
são verificados só por testes que os chamam diretamente — e o caminho real
(coordenar repositório, relógio e publicação de evento) nunca é exercitado. É
nesse caminho que a regra costuma vazar para a API ou para a CLI.

O QUE ELES NÃO FAZEM. Não validam de novo o que o domínio já valida. Um caso
de uso que reconfere `home != away` cria uma segunda regra que diverge da
primeira no dia em que uma das duas mudar. Aqui eles COORDENAM: pegam o
instante do relógio injetado, chamam o domínio, persistem pelo port, publicam
o evento.

NENHUM CASO DE USO SEM UTILIDADE CONCRETA. Cada um destes é chamado por um
teste que prova um invariante do domínio no caminho real.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import final

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.competitions.models import (
    Competition,
    CompetitionRegime,
    Season,
    Stage,
)
from sports_intelligence.domain.events.canonical import CanonicalMatchEvent
from sports_intelligence.domain.events.envelope import EventEnvelope
from sports_intelligence.domain.events.envelope_types import (
    DOMAIN_SCHEMA,
    LINEUP_CONFIRMED,
    MATCH_LIFECYCLE_CHANGED,
    MATCH_REGISTERED,
)
from sports_intelligence.domain.matches.lifecycle import MatchLifecycle, transition_to
from sports_intelligence.domain.matches.lineup import Lineup, assert_squads_are_disjoint
from sports_intelligence.domain.matches.models import Match, Venue
from sports_intelligence.domain.odds.models import OddsQuote
from sports_intelligence.domain.players.models import Player, PlayerTeamTenure
from sports_intelligence.domain.shared.errors import ConflictError, NotFoundError
from sports_intelligence.domain.shared.identity import MatchId, SeasonId, TeamId
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.teams.models import Team
from sports_intelligence.ports.clock import ClockPort
from sports_intelligence.ports.event_bus import EventPublisherPort
from sports_intelligence.ports.repositories.football import (
    CanonicalEventRepositoryPort,
    CompetitionRepositoryPort,
    LineupRepositoryPort,
    MatchRepositoryPort,
    OddsRepositoryPort,
    PlayerRepositoryPort,
    SeasonRepositoryPort,
    TeamRepositoryPort,
)


@final
@dataclass(frozen=True, slots=True)
class RegisterCompetition:
    """Materializa uma das cinco do catálogo.

    Não aceita nome nem região: eles vêm do catálogo. Aceitá-los permitiria
    duas Premier Leagues com nomes diferentes.
    """

    repository: CompetitionRepositoryPort

    async def execute(self, code: CompetitionCode) -> Competition:
        competicao = Competition.from_code(code)
        await self.repository.upsert(competicao)
        return competicao


@final
@dataclass(frozen=True, slots=True)
class RegisterSeason:
    competitions: CompetitionRepositoryPort
    seasons: SeasonRepositoryPort

    async def execute(
        self,
        *,
        code: CompetitionCode,
        label: str,
        starts_at: Instant,
        ends_at: Instant,
        regime: CompetitionRegime,
    ) -> Season:
        competicao = await self.competitions.by_code(code)
        if competicao is None:
            raise NotFoundError(
                f"competição {code} não registrada",
                context={"code": code.value},
            )
        temporada = Season.create(
            competition_id=competicao.id,
            label=label,
            starts_at=starts_at,
            ends_at=ends_at,
            regime=regime,
        )
        await self.seasons.upsert(temporada)
        return temporada


@final
@dataclass(frozen=True, slots=True)
class RegisterTeam:
    repository: TeamRepositoryPort

    async def execute(
        self, *, canonical_name: str, country: str, short_name: str | None = None
    ) -> Team:
        time = Team.register(
            canonical_name=canonical_name, country=country, short_name=short_name
        )
        await self.repository.upsert(time)
        return time


@final
@dataclass(frozen=True, slots=True)
class RegisterPlayer:
    repository: PlayerRepositoryPort

    async def execute(self, **campos: object) -> Player:
        jogador = Player.register(**campos)  # type: ignore[arg-type]
        await self.repository.upsert(jogador)
        return jogador


@final
@dataclass(frozen=True, slots=True)
class RecordPlayerTenure:
    """Registra a passagem de um jogador por um clube.

    NÃO fecha o vínculo anterior automaticamente. Empréstimo é vínculo
    simultâneo legítimo, e fechar por conta própria apagaria isso — a decisão
    é de quem sabe o que aconteceu.
    """

    players: PlayerRepositoryPort
    teams: TeamRepositoryPort

    async def execute(self, tenure: PlayerTeamTenure) -> PlayerTeamTenure:
        if await self.players.by_id(tenure.player_id) is None:
            raise NotFoundError(f"jogador {tenure.player_id} não registrado")
        if await self.teams.by_id(tenure.team_id) is None:
            raise NotFoundError(f"time {tenure.team_id} não registrado")
        await self.players.record_tenure(tenure)
        return tenure


@final
@dataclass(frozen=True, slots=True)
class RegisterMatch:
    """Cria a partida e publica `MatchRegistered`."""

    matches: MatchRepositoryPort
    seasons: SeasonRepositoryPort
    teams: TeamRepositoryPort
    clock: ClockPort
    publisher: EventPublisherPort

    async def execute(
        self,
        *,
        season_id: SeasonId,
        stage: Stage,
        home_team_id: TeamId,
        away_team_id: TeamId,
        scheduled_kickoff: Instant,
        venue: Venue | None = None,
        neutral_venue: bool = False,
    ) -> Match:
        temporada = await self.seasons.by_id(season_id)
        if temporada is None:
            raise NotFoundError(f"temporada {season_id} não registrada")
        for team_id in (home_team_id, away_team_id):
            if await self.teams.by_id(team_id) is None:
                raise NotFoundError(f"time {team_id} não registrado")
        # A partida precisa cair DENTRO da temporada. Uma partida fora da
        # janela é quase sempre temporada errada — e ela contaminaria a
        # tabela de uma edição que não a teve.
        if not temporada.contains(scheduled_kickoff):
            raise ConflictError(
                f"o pontapé {scheduled_kickoff.isoformat()} está fora da temporada "
                f"{temporada.label}",
                context={
                    "season_starts": temporada.starts_at.isoformat(),
                    "season_ends": temporada.ends_at.isoformat(),
                },
            )

        partida = Match.register(
            competition_id=temporada.competition_id,
            season_id=temporada.id,
            regime=temporada.regime,
            stage=stage,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            scheduled_kickoff=scheduled_kickoff,
            venue=venue,
            neutral_venue=neutral_venue,
        )
        await self.matches.upsert(partida)

        agora = self.clock.now()
        await self.publisher.publish(
            EventEnvelope.create(
                event_type=MATCH_REGISTERED,
                schema_version=DOMAIN_SCHEMA,
                occurred_at=agora,
                produced_at=agora,
                payload={
                    "match_id": str(partida.id),
                    "competition_id": str(partida.competition_id),
                    "season_id": str(partida.season_id),
                    "scheduled_kickoff": partida.scheduled_kickoff.isoformat(),
                },
                match_id=partida.id,
            )
        )
        return partida


@final
@dataclass(frozen=True, slots=True)
class ChangeMatchLifecycle:
    """A ÚNICA porta para mudar o estado de uma partida.

    Valida a transição pelo grafo do domínio, persiste, e publica. Nenhum
    outro caminho pode escrever `lifecycle` — é isso que impede uma partida
    cancelada de voltar a ficar ao vivo.
    """

    matches: MatchRepositoryPort
    clock: ClockPort
    publisher: EventPublisherPort

    async def execute(
        self, *, match_id: MatchId, target: MatchLifecycle, reason: str
    ) -> Match:
        partida = await self.matches.by_id(match_id)
        if partida is None:
            raise NotFoundError(f"partida {match_id} não registrada")

        agora = self.clock.now()
        transicao = transition_to(
            partida.lifecycle, target, at=agora, reason=reason
        )
        atualizada = partida.with_lifecycle(target)
        await self.matches.upsert(atualizada)
        await self.publisher.publish(
            EventEnvelope.create(
                event_type=MATCH_LIFECYCLE_CHANGED,
                schema_version=DOMAIN_SCHEMA,
                occurred_at=agora,
                produced_at=agora,
                payload={
                    "match_id": str(match_id),
                    "from": transicao.from_state.value,
                    "to": transicao.to_state.value,
                    "reason": transicao.reason,
                },
                match_id=match_id,
            )
        )
        return atualizada


@final
@dataclass(frozen=True, slots=True)
class ConfirmLineup:
    """Confirma a escalação de um time, checando contra a do adversário.

    A CHECAGEM CRUZADA é o ponto deste caso de uso. Sozinha, uma escalação é
    válida; o erro caro — o mesmo jogador nos dois times, vindo de resolução
    de identidade que fundiu homônimos — só aparece ao confrontar as duas.
    """

    matches: MatchRepositoryPort
    lineups: LineupRepositoryPort
    clock: ClockPort
    publisher: EventPublisherPort

    async def execute(self, lineup: Lineup) -> Lineup:
        partida = await self.matches.by_id(lineup.match_id)
        if partida is None:
            raise NotFoundError(f"partida {lineup.match_id} não registrada")
        if not partida.involves(lineup.team_id):
            raise ConflictError(
                f"o time {lineup.team_id} não joga a partida {lineup.match_id}"
            )

        for existente in await self.lineups.for_match(lineup.match_id):
            if existente.team_id == lineup.team_id:
                continue
            assert_squads_are_disjoint(
                *(
                    (lineup, existente)
                    if lineup.team_id == partida.home_team_id
                    else (existente, lineup)
                )
            )

        await self.lineups.confirm(lineup)
        agora = self.clock.now()
        await self.publisher.publish(
            EventEnvelope.create(
                event_type=LINEUP_CONFIRMED,
                schema_version=DOMAIN_SCHEMA,
                occurred_at=agora,
                produced_at=agora,
                payload={
                    "match_id": str(lineup.match_id),
                    "team_id": str(lineup.team_id),
                    "starters": len(lineup.starters),
                    "formation": str(lineup.formation) if lineup.formation else None,
                },
                match_id=lineup.match_id,
            )
        )
        return lineup


@final
@dataclass(frozen=True, slots=True)
class RecordCanonicalEvents:
    """Grava revisões de eventos. Append, nunca update."""

    matches: MatchRepositoryPort
    events: CanonicalEventRepositoryPort

    async def execute(self, events: Sequence[CanonicalMatchEvent]) -> int:
        if not events:
            return 0
        partidas = {e.match_id for e in events}
        if len(partidas) > 1:
            raise ConflictError(
                "lote com eventos de partidas diferentes",
                context={"matches": sorted(str(m) for m in partidas)},
            )
        match_id = next(iter(partidas))
        if await self.matches.by_id(match_id) is None:
            raise NotFoundError(f"partida {match_id} não registrada")
        return await self.events.append(events)


@final
@dataclass(frozen=True, slots=True)
class RecordOddsQuotes:
    """Grava observações de cotação. Cada uma com seu instante."""

    matches: MatchRepositoryPort
    odds: OddsRepositoryPort

    async def execute(self, quotes: Sequence[OddsQuote]) -> int:
        if not quotes:
            return 0
        partidas = {q.match_id for q in quotes}
        if len(partidas) > 1:
            raise ConflictError("lote com cotações de partidas diferentes")
        match_id = next(iter(partidas))
        if await self.matches.by_id(match_id) is None:
            raise NotFoundError(f"partida {match_id} não registrada")
        return await self.odds.record(quotes)
