"""A escalação oficial, e a formação nominal.

A ESCALAÇÃO É A CONFIGURAÇÃO INICIAL — E NÃO MUDA. Substituição é EVENTO, não
edição da escalação. Atualizar a lineup a cada troca apaga quem começou
jogando, que é justamente o que descreve a intenção tática da equipe.

Reconstruir "quem estava em campo no minuto 63" é aplicar os eventos sobre a
escalação inicial. Guardar só o estado corrente torna isso impossível e apaga
o registro do que o técnico planejou.

A FORMAÇÃO É NOMINAL E DECLARADA, NUNCA INFERIDA. Contar posições e concluir
"4-3-3" erra sistematicamente: um 4-2-3-1 tem quatro defensores, cinco
meio-campistas por linha e um atacante — a mesma contagem de um 4-5-1, que é
outra coisa. E times jogam com desenhos assimétricos que nenhuma contagem
descreve.

`FormationLabel` guarda o que a fonte declarou. Grafo tático é PR futuro.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self, final

from sports_intelligence.domain.players.positions import Position, TacticalRole
from sports_intelligence.domain.shared.identity import MatchId, PlayerId, TeamId

#: Onze em campo. Não é configurável: é a regra do futebol, e um número
#: parametrizável convidaria a "flexibilizar" quando uma fonte vier errada.
STARTERS: Final = 11

_FORMACAO = re.compile(r"^\d(?:-\d){1,4}$")


@final
@dataclass(frozen=True, slots=True)
class FormationLabel:
    """`4-3-3`, `4-2-3-1`, `3-4-2-1`. O rótulo, validado.

    Preparado para alimentar `ExpectedFormationGraph` e
    `ObservedFormationGraph` num PR futuro — aqui ele é só o rótulo, porque é
    só isso que existe hoje.
    """

    value: str

    def __post_init__(self) -> None:
        texto = self.value.strip()
        if not _FORMACAO.match(texto):
            raise ValueError(
                f"formação {self.value!r} inválida: use dígitos separados por hífen, "
                "por exemplo 4-3-3 ou 4-2-3-1"
            )
        # O goleiro não entra no rótulo, por convenção universal — `4-3-3` são
        # dez jogadores de linha. Uma soma de 11 quer dizer que alguém incluiu
        # o goleiro, e aí o rótulo descreve outro desenho.
        if sum(int(d) for d in texto.split("-")) != STARTERS - 1:
            raise ValueError(
                f"formação {self.value!r} soma {sum(int(d) for d in texto.split('-'))} "
                f"jogadores de linha; o esperado é {STARTERS - 1} (o goleiro não entra no rótulo)"
            )
        object.__setattr__(self, "value", texto)

    @property
    def lines(self) -> tuple[int, ...]:
        return tuple(int(d) for d in self.value.split("-"))

    def __str__(self) -> str:
        return self.value


class LineupStatus(StrEnum):
    STARTER = "STARTER"
    BENCH = "BENCH"


@final
@dataclass(frozen=True, slots=True)
class LineupEntry:
    """Um jogador na escalação.

    `position` e `tactical_role` são opcionais porque muitas fontes não os
    publicam — e ausência aqui é ausência, nunca uma posição suposta.
    """

    player_id: PlayerId
    status: LineupStatus
    shirt_number: int | None = None
    position: Position | None = None
    tactical_role: TacticalRole | None = None
    captain: bool = False

    def __post_init__(self) -> None:
        if self.shirt_number is not None and not 1 <= self.shirt_number <= 99:
            raise ValueError(
                f"número {self.shirt_number} fora de 1..99 — número ausente é `None`, "
                "nunca 0 (Constituição §4)"
            )
        # Capitão no banco existe no papel e não em campo. Se a fonte diz
        # isso, ela está descrevendo outra coisa (o capitão do elenco), e
        # aceitá-lo faria "quem é o capitão em campo" ter duas respostas.
        if self.captain and self.status is not LineupStatus.STARTER:
            raise ValueError("capitão precisa ser titular")

    @property
    def is_starter(self) -> bool:
        return self.status is LineupStatus.STARTER


@final
@dataclass(frozen=True, slots=True)
class Lineup:
    """A escalação oficial de UM time numa partida.

    Os invariantes aqui são os que pegam erro de fusão de fontes — o tipo de
    problema que passa despercebido e corrompe todo cálculo por jogador.
    """

    match_id: MatchId
    team_id: TeamId
    entries: tuple[LineupEntry, ...]
    formation: FormationLabel | None = None

    def __post_init__(self) -> None:
        if not self.entries:
            raise ValueError("escalação vazia")

        vistos: set[PlayerId] = set()
        for entrada in self.entries:
            if entrada.player_id in vistos:
                raise ValueError(
                    f"jogador {entrada.player_id} aparece duas vezes na mesma escalação — "
                    "sintoma clássico de duas fontes fundidas sem deduplicação"
                )
            vistos.add(entrada.player_id)

        titulares = [e for e in self.entries if e.is_starter]
        if len(titulares) > STARTERS:
            raise ValueError(f"{len(titulares)} titulares: o máximo é {STARTERS}")

        capitaes = [e for e in self.entries if e.captain]
        if len(capitaes) > 1:
            raise ValueError(f"{len(capitaes)} capitães na mesma escalação")

        numeros = [e.shirt_number for e in self.entries if e.shirt_number is not None]
        if len(numeros) != len(set(numeros)):
            raise ValueError("dois jogadores com o mesmo número na mesma escalação")

    @property
    def starters(self) -> tuple[LineupEntry, ...]:
        return tuple(e for e in self.entries if e.is_starter)

    @property
    def bench(self) -> tuple[LineupEntry, ...]:
        return tuple(e for e in self.entries if not e.is_starter)

    @property
    def captain(self) -> LineupEntry | None:
        return next((e for e in self.entries if e.captain), None)

    @property
    def player_ids(self) -> frozenset[PlayerId]:
        return frozenset(e.player_id for e in self.entries)

    @property
    def is_complete(self) -> bool:
        """Onze titulares. Uma escalação parcial é legítima na janela
        pré-jogo — é o que se sabe antes de a oficial sair."""
        return len(self.starters) == STARTERS

    def entry_for(self, player_id: PlayerId) -> LineupEntry | None:
        return next((e for e in self.entries if e.player_id == player_id), None)

    def __iter__(self) -> Iterator[LineupEntry]:
        return iter(self.entries)

    @classmethod
    def confirm(
        cls,
        *,
        match_id: MatchId,
        team_id: TeamId,
        entries: tuple[LineupEntry, ...],
        formation: FormationLabel | None = None,
    ) -> Self:
        return cls(match_id=match_id, team_id=team_id, entries=entries, formation=formation)


def assert_squads_are_disjoint(home: Lineup, away: Lineup) -> None:
    """Nenhum jogador nas duas escalações da mesma partida.

    NÃO É PARANOIA — é o invariante que pega o erro mais caro da fusão de
    fontes. Quando a resolução de identidade funde dois jogadores homônimos
    de times adversários, ele aparece dos dois lados, e toda estatística por
    jogador daquela partida passa a contar duas vezes.

    Também confere que as duas descrevem a MESMA partida e times DIFERENTES:
    comparar escalações de partidas distintas passaria trivialmente.
    """
    if home.match_id != away.match_id:
        raise ValueError(f"escalações de partidas diferentes: {home.match_id} e {away.match_id}")
    if home.team_id == away.team_id:
        raise ValueError(f"as duas escalações são do mesmo time ({home.team_id})")
    comuns = home.player_ids & away.player_ids
    if comuns:
        raise ValueError(
            f"{len(comuns)} jogador(es) escalado(s) nos dois times da mesma partida: "
            f"{sorted(str(p) for p in comuns)}"
        )
