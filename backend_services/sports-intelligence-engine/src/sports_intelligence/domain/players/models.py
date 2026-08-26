"""Jogador, e o vínculo dele com clubes ao longo do tempo.

O DEFEITO QUE `PlayerTeamTenure` EXISTE PARA IMPEDIR. Um jogador tem um clube
ATUAL, e é tentador guardá-lo no jogador — `player.team_id`. Aí, ao descrever
uma partida de 2019, o histórico dele aparece sob o clube de 2026.

Isso reescreve o passado. Um gol marcado pelo Santos passa a contar para o
clube de hoje, e a média móvel daquele clube ganha jogos que ele não jogou.
Nada falha; o número só fica errado.

O VÍNCULO É TEMPORAL E VIVE FORA DO JOGADOR. `Player` guarda o que não muda —
quem ele é. O clube é uma relação com validade, e "de quem era este jogador
naquela data" é uma pergunta com resposta.

NADA DE RATING, FORMA OU INFLUÊNCIA. Esses são derivados, mudam a cada
partida, e pertencem ao Feature Engine. Guardá-los aqui misturaria fato com
cálculo, e o cálculo tem versão.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Self, final

from sports_intelligence.domain.players.positions import Position
from sports_intelligence.domain.shared.identity import PlayerId, TeamId
from sports_intelligence.domain.shared.temporal import Instant


class PreferredFoot(StrEnum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    BOTH = "BOTH"


@final
@dataclass(frozen=True, slots=True)
class Player:
    """Quem o jogador é. Não o que ele vale, nem onde joga hoje.

    Os campos opcionais são os que ajudam a RESOLVER identidade depois: data
    de nascimento e nacionalidade distinguem dois homônimos melhor que
    qualquer heurística sobre o nome.
    """

    id: PlayerId
    canonical_name: str
    date_of_birth: date | None = None
    nationality: str | None = None
    preferred_foot: PreferredFoot | None = None
    primary_position: Position | None = None
    active: bool = True

    def __post_init__(self) -> None:
        if not self.canonical_name.strip():
            raise ValueError("jogador sem canonical_name")
        if self.nationality is not None:
            if len(self.nationality) != 2 or not self.nationality.isalpha():
                raise ValueError(f"nationality {self.nationality!r} inválida: ISO-3166 alpha-2")
            if self.nationality != self.nationality.upper():
                raise ValueError(f"nationality {self.nationality!r} deve ser maiúscula")

    @classmethod
    def register(
        cls,
        *,
        canonical_name: str,
        date_of_birth: date | None = None,
        nationality: str | None = None,
        preferred_foot: PreferredFoot | None = None,
        primary_position: Position | None = None,
    ) -> Self:
        """Id SORTEADO, pelo mesmo motivo de `Team.register`.

        Nomes de jogador colidem com frequência — há vários "Rodrigo Silva" —
        e derivar identidade do nome fundiria carreiras.
        """
        return cls(
            id=PlayerId.new(),
            canonical_name=canonical_name.strip(),
            date_of_birth=date_of_birth,
            nationality=nationality,
            preferred_foot=preferred_foot,
            primary_position=primary_position,
        )


@final
@dataclass(frozen=True, slots=True)
class PlayerTeamTenure:
    """De qual clube o jogador era, e quando.

    `valid_to` ausente quer dizer "ainda é" — o estado normal do vínculo
    corrente, não um dado faltando.
    """

    player_id: PlayerId
    team_id: TeamId
    valid_from: Instant
    valid_to: Instant | None = None

    def __post_init__(self) -> None:
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError(
                f"vínculo termina ({self.valid_to.isoformat()}) antes de começar "
                f"({self.valid_from.isoformat()})"
            )

    @property
    def is_current(self) -> bool:
        return self.valid_to is None

    def covers(self, moment: Instant) -> bool:
        """Se o vínculo valia naquele instante.

        É ESTA a pergunta que o histórico faz — nunca "de qual clube ele é".
        A segunda pergunta responde sobre hoje e seria aplicada ao passado.
        """
        if moment < self.valid_from:
            return False
        return self.valid_to is None or moment <= self.valid_to

    def close(self, at: Instant) -> Self:
        """Encerra o vínculo. Não altera a identidade do jogador."""
        if self.valid_to is not None:
            raise ValueError("vínculo já encerrado")
        return type(self)(
            player_id=self.player_id,
            team_id=self.team_id,
            valid_from=self.valid_from,
            valid_to=at,
        )


def team_at(tenures: tuple[PlayerTeamTenure, ...], moment: Instant) -> TeamId | None:
    """De qual clube o jogador era NAQUELE instante.

    `None` quando nenhum vínculo conhecido cobre a data — e `None` é a
    resposta honesta. Devolver o clube atual como aproximação é exatamente o
    defeito que este módulo existe para impedir.

    Sobreposição de vínculos (empréstimo mal fechado, dado sujo) devolve o
    mais recente por `valid_from`, deterministicamente — e o desempate é
    explícito porque ordenação implícita muda entre execuções.
    """
    cobrindo = [t for t in tenures if t.covers(moment)]
    if not cobrindo:
        return None
    return max(cobrindo, key=lambda t: (t.valid_from, str(t.team_id))).team_id
