"""As ENTRADAS TIPADAS dos construtores — o antídoto contra `Match(**campos)`.

O QUE O §30 PROÍBE, e por que ele está certo. `Match(**fused_fields)` parece
econômico e faz três coisas ruins de uma vez: aceita qualquer chave que a
fusão tenha produzido, silencia a ausência de uma que ela não produziu, e
transforma toda mudança no mapeamento de fonte numa mudança no agregado
canônico — sem que nenhum tipo perceba.

Então entre a saída da fusão e o contrato canônico existe uma camada de
tradução EXPLÍCITA, e ela mora aqui. Cada campo é lido por nome, convertido
por tipo, e a falha de conversão vira ausência declarada — nunca zero (§44).

TRÊS CONTRATOS, UM POR FAMÍLIA CONSTRUÍVEL:

    MatchIdentityFacts   quem joga, quando, sob que regime — vem da IDENTIDADE
                         já resolvida, nunca da fusão de observações (§27)
    ScoreFacts           o placar por escopo, com ausência tipada
    LineupDraft          a escalação com `PlayerId` CANÔNICO ou nada (§36)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self, final

from sports_intelligence.domain.competitions.models import CompetitionRegime, Stage
from sports_intelligence.domain.matches.lineup import LineupStatus
from sports_intelligence.domain.matches.models import Venue
from sports_intelligence.domain.players.positions import Position
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import (
    CompetitionId,
    MatchId,
    PlayerId,
    SeasonId,
    TeamId,
)
from sports_intelligence.domain.shared.temporal import Instant


@final
@dataclass(frozen=True, slots=True)
class MatchIdentityFacts:
    """A identidade canônica de uma partida — JÁ RESOLVIDA, nunca inferida.

    O CONSTRUTOR NÃO RESOLVE IDENTIDADE (§27). Se um `TeamId` ou um `SeasonId`
    não existe, o build não pode inventá-lo: identidade é o PR-03, com
    evidência, confiança e possibilidade de falhar. Este tipo é a prova de que
    o trabalho já foi feito — ele só se constrói com os ids em mãos.

    O REGIME VEM DA TEMPORADA e não da partida, porque é a temporada que
    declara sob qual formato ela aconteceu (PR-01). Repeti-lo aqui é o que
    permite o construtor montar o `Match` sem uma segunda consulta por linha.
    """

    match_id: MatchId
    competition_id: CompetitionId
    season_id: SeasonId
    regime: CompetitionRegime
    stage: Stage
    home_team_id: TeamId
    away_team_id: TeamId
    scheduled_kickoff: Instant
    actual_kickoff: Instant | None = None
    venue: Venue | None = None
    neutral_venue: bool = False

    def __post_init__(self) -> None:
        if self.home_team_id == self.away_team_id:
            raise ValidationError(
                f"identidade com mandante e visitante iguais ({self.home_team_id}) — "
                "quase sempre resolução que fundiu dois clubes"
            )

    def __str__(self) -> str:
        return f"{self.match_id} · {self.home_team_id} x {self.away_team_id}"


@final
@dataclass(frozen=True, slots=True)
class ScoreFacts:
    """O placar por escopo, com ausência TIPADA.

    `None` E NUNCA `0`. Um placar ausente virando `0-0` produz o defeito mais
    caro que um corpus de futebol pode ter: ele é plausível, não dispara nada,
    e infla a contagem de empates sem gol de toda temporada mal ingerida
    (§44, §89).

    OS TRÊS ESCOPOS SEPARADOS, como no PR-01: prorrogação é acumulada com o
    tempo normal, e pênaltis NÃO são gol. Achatá-los aqui desfaria a decisão
    lá (§34).
    """

    regular_home: int | None = None
    regular_away: int | None = None
    extra_home: int | None = None
    extra_away: int | None = None
    penalties_home: int | None = None
    penalties_away: int | None = None

    def __post_init__(self) -> None:
        for nome, valor in (
            ("regular_home", self.regular_home),
            ("regular_away", self.regular_away),
            ("extra_home", self.extra_home),
            ("extra_away", self.extra_away),
            ("penalties_home", self.penalties_home),
            ("penalties_away", self.penalties_away),
        ):
            if valor is not None and valor < 0:
                raise ValidationError(f"{nome} negativo: {valor}")

    @property
    def has_regular_time(self) -> bool:
        """Se há placar de tempo normal — o mínimo para existir um resultado.

        OS DOIS LADOS, e não um: `2-None` não é `2-0`, é meio placar. Aceitar
        um lado só e completar o outro com zero é a forma que o §44 toma
        quando ninguém está olhando.
        """
        return self.regular_home is not None and self.regular_away is not None

    @property
    def has_extra_time(self) -> bool:
        return self.extra_home is not None and self.extra_away is not None

    @property
    def has_penalties(self) -> bool:
        return self.penalties_home is not None and self.penalties_away is not None

    @property
    def is_empty(self) -> bool:
        return not any(
            v is not None
            for v in (
                self.regular_home,
                self.regular_away,
                self.extra_home,
                self.extra_away,
                self.penalties_home,
                self.penalties_away,
            )
        )


@final
@dataclass(frozen=True, slots=True)
class LineupDraftEntry:
    """Um jogador de uma escalação candidata, resolvido ou NÃO.

    `player_id is None` É O CASO QUE ESTE TIPO EXISTE PARA CARREGAR. Um
    jogador que a resolução não provou não pode virar `PlayerId` — nem
    derivado do nome, nem sorteado, nem «temporário». Qualquer uma das três
    contaminaria influência de jogador, força de elenco e grafo tático de
    forma que ninguém detecta depois, porque tudo continua somando (§36).

    Então o rascunho carrega a ausência, e a política decide o que fazer com
    a família — nunca o construtor, e nunca com um id inventado.
    """

    source_name: str
    status: LineupStatus
    player_id: PlayerId | None = None
    shirt_number: int | None = None
    position: Position | None = None
    captain: bool = False

    def __post_init__(self) -> None:
        if not self.source_name.strip():
            raise ValidationError(
                "entrada de escalação sem nome de origem: sem ele, um jogador não "
                "resolvido não teria nem como ser procurado"
            )

    @property
    def is_resolved(self) -> bool:
        return self.player_id is not None


@final
@dataclass(frozen=True, slots=True)
class LineupDraft:
    """A escalação candidata de UM time numa partida.

    A ESCALAÇÃO É A CONFIGURAÇÃO INICIAL, e continua sendo (§37). Substituição
    é evento, não edição — e como esta fase não constrói eventos, não há
    caminho de código que aplique uma substituição sobre isto.
    """

    match_id: MatchId
    team_id: TeamId
    entries: tuple[LineupDraftEntry, ...]
    formation: str | None = None

    def __post_init__(self) -> None:
        if not self.entries:
            raise ValidationError("rascunho de escalação vazio")

    @property
    def unresolved(self) -> tuple[str, ...]:
        """Os nomes que a resolução não provou, em ordem estável.

        É O QUE A POLÍTICA CONSULTA para decidir entre pular a família e
        mandá-la para revisão (§40, §91). Vazio significa que toda a escalação
        tem identidade canônica.
        """
        return tuple(sorted(e.source_name for e in self.entries if not e.is_resolved))

    @property
    def is_fully_resolved(self) -> bool:
        return not self.unresolved

    @classmethod
    def of(
        cls,
        *,
        match_id: MatchId,
        team_id: TeamId,
        entries: tuple[LineupDraftEntry, ...],
        formation: str | None = None,
    ) -> Self:
        return cls(
            match_id=match_id, team_id=team_id, entries=entries, formation=formation
        )

    def __str__(self) -> str:
        pendentes = len(self.unresolved)
        marca = f" · {pendentes} não resolvido(s)" if pendentes else ""
        return f"escalação {self.team_id} · {len(self.entries)} jogador(es){marca}"
