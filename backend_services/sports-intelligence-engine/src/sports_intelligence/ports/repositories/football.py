"""Ports do domínio futebolístico. Pequenos e orientados ao domínio.

NADA DE CRUD GENÉRICO. Um `save(entity)` com `find_by(**kwargs)` parece
econômico e destrói a informação mais útil que um port carrega: o que o
domínio realmente faz com aquela entidade. Um port genérico obriga todo
adapter a suportar qualquer consulta, e nenhuma otimização é possível porque
nenhum padrão de acesso é conhecido.

Cada método aqui existe porque um caso de uso do PR-01 o chama.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.competitions.models import Competition, Season
from sports_intelligence.domain.events.canonical import CanonicalMatchEvent
from sports_intelligence.domain.matches.lineup import Lineup
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.odds.models import OddsQuote
from sports_intelligence.domain.players.models import Player, PlayerTeamTenure
from sports_intelligence.domain.shared.identity import (
    MatchId,
    PlayerId,
    SeasonId,
    TeamId,
)
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.teams.models import Team


@runtime_checkable
class CompetitionRepositoryPort(Protocol):
    async def upsert(self, competition: Competition) -> None: ...

    async def by_code(self, code: CompetitionCode) -> Competition | None: ...


@runtime_checkable
class SeasonRepositoryPort(Protocol):
    async def upsert(self, season: Season) -> None: ...

    async def by_id(self, season_id: SeasonId) -> Season | None: ...

    async def containing(
        self, *, competition_code: CompetitionCode, moment: Instant
    ) -> Season | None:
        """Qual temporada desta competição contém esta data.

        PROCURADA, não derivada por regra: temporadas europeias atravessam
        dois anos civis e sul-americanas cabem em um; e o futebol argentino
        mudou de formato quase todo ano. Uma regra acerta metade.
        """
        ...


@runtime_checkable
class TeamRepositoryPort(Protocol):
    async def upsert(self, team: Team) -> None: ...

    async def by_id(self, team_id: TeamId) -> Team | None: ...


@runtime_checkable
class PlayerRepositoryPort(Protocol):
    async def upsert(self, player: Player) -> None: ...

    async def by_id(self, player_id: PlayerId) -> Player | None: ...

    async def tenures(self, player_id: PlayerId) -> Sequence[PlayerTeamTenure]:
        """Todo o histórico de vínculos, não o atual.

        Devolver só o corrente faria o histórico ser lido com o clube de hoje
        — que é exatamente o defeito que `PlayerTeamTenure` existe para
        impedir.
        """
        ...

    async def record_tenure(self, tenure: PlayerTeamTenure) -> None: ...


@runtime_checkable
class MatchRepositoryPort(Protocol):
    """Ampliação do port do PR-00, que já carrega o invariante histórico."""

    async def upsert(self, match: Match) -> None: ...

    async def by_id(self, match_id: MatchId) -> Match | None: ...


@runtime_checkable
class LineupRepositoryPort(Protocol):
    async def confirm(self, lineup: Lineup) -> None: ...

    async def for_match(self, match_id: MatchId) -> Sequence[Lineup]:
        """As escalações da partida — no máximo duas, uma por time.

        A CONFIGURAÇÃO INICIAL, sempre. Substituições são eventos e não
        alteram o que está guardado aqui; reconstruir quem estava em campo
        num minuto é aplicar os eventos sobre isto.
        """
        ...


@runtime_checkable
class CanonicalEventRepositoryPort(Protocol):
    async def append(self, events: Sequence[CanonicalMatchEvent]) -> int:
        """Grava revisões. Devolve quantas entraram.

        APPEND, nunca update: correção é revisão nova, e a anterior permanece
        (ADR-0013). O número devolvido importa — "gravado com sucesso" sem
        contagem é afirmação sem medida.
        """
        ...

    async def for_match(self, match_id: MatchId) -> Sequence[CanonicalMatchEvent]:
        """TODAS as revisões, inclusive corrigidas e canceladas.

        Filtrar aqui pelas ativas impediria reconstruir "o que sabíamos
        naquele momento" — que é metade da razão de a revisão existir.
        """
        ...


@runtime_checkable
class OddsRepositoryPort(Protocol):
    async def record(self, quotes: Sequence[OddsQuote]) -> int: ...

    async def series(self, match_id: MatchId) -> Sequence[OddsQuote]:
        """A série temporal completa, em ordem de observação.

        A série, e não a última: a diferença entre abertura e fechamento é o
        sinal, e um "current_odds" a apagaria.
        """
        ...
