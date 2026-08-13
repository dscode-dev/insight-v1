"""O evento canônico — imutável, revisável, e nunca destrutivo.

O PROBLEMA QUE A REVISÃO RESOLVE. Provedores corrigem. Um gol atribuído ao
camisa 9 vira do camisa 11 vinte minutos depois; um pênalti é anulado pelo
VAR; um cartão muda de amarelo para vermelho.

Se a correção sobrescreve o evento, duas perguntas ficam sem resposta:

  «o que sabíamos no minuto 63?»   — a base só tem a versão corrigida
  «quando soubemos que mudou?»     — não há registro de que mudou

A primeira é o que torna o replay honesto. Se a correção chegou aos 85 e o
replay do minuto 63 usa a versão corrigida, o replay está enxergando o futuro.

A SOLUÇÃO: correção é EVENTO NOVO. `revision` incrementa, `supersedes` aponta
para o anterior, e o anterior passa a `CORRECTED` — permanecendo na base.
Anulação é `CANCELLED`, também sem apagar nada.

    revisão 1  GOAL  camisa 9   status=CORRECTED   (supersedes=None)
    revisão 2  GOAL  camisa 11  status=ACTIVE      (supersedes=rev1)

Reconstruir "o que sabíamos às 21h40" é filtrar por quando cada revisão
chegou; reconstruir a verdade final é pegar as `ACTIVE`.

`sequence` ORDENA DENTRO DO PERÍODO. O relógio da partida empata — dois
eventos no mesmo minuto são comuns — e a ordem entre eles muda a leitura de
uma sequência de jogo.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Self, final

from sports_intelligence.domain.events.coordinates import PitchCoordinate
from sports_intelligence.domain.events.details import EventDetail
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.shared.identity import MatchId, PlayerId, TeamId
from sports_intelligence.domain.shared.provenance import DataProvenance
from sports_intelligence.domain.shared.quality import DataQuality
from sports_intelligence.domain.shared.temporal import MatchClock


class EventStatus(StrEnum):
    """O estado de uma revisão.

    `CORRECTED` e `CANCELLED` são DIFERENTES: o primeiro diz "existe uma
    versão melhor deste fato"; o segundo diz "este fato não aconteceu". Um gol
    anulado pelo VAR não é um gol corrigido.
    """

    ACTIVE = "ACTIVE"
    #: Existe uma revisão posterior. Este permanece como registro.
    CORRECTED = "CORRECTED"
    #: O fato foi anulado. Não há sucessor.
    CANCELLED = "CANCELLED"

    @property
    def is_current_truth(self) -> bool:
        """Se esta revisão faz parte da verdade reconciliada."""
        return self is EventStatus.ACTIVE


@final
@dataclass(frozen=True, slots=True)
class CanonicalMatchEvent:
    """Um fato da partida, no vocabulário do motor.

    IMUTÁVEL. Correção produz um evento NOVO por `correct_to`; anulação
    produz uma cópia com status por `cancel`. Nada é sobrescrito.
    """

    id: uuid.UUID
    match_id: MatchId
    type: EventType
    clock: MatchClock
    #: Ordem dentro do período. O relógio empata; isto não.
    sequence: int
    provenance: DataProvenance
    quality: DataQuality
    team_id: TeamId | None = None
    player_id: PlayerId | None = None
    start_location: PitchCoordinate | None = None
    end_location: PitchCoordinate | None = None
    detail: EventDetail | None = None
    revision: int = 1
    supersedes: uuid.UUID | None = None
    status: EventStatus = EventStatus.ACTIVE

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError(f"sequence negativa: {self.sequence}")
        if self.revision < 1:
            raise ValueError(f"revision começa em 1, recebeu {self.revision}")
        if self.type.requires_team and self.team_id is None:
            raise ValueError(f"{self.type} pertence a um time e veio sem team_id")
        if not self.type.requires_team and self.team_id is not None:
            raise ValueError(
                f"{self.type} não pertence a nenhum time (é estrutural ou interrupção), "
                f"e veio com team_id — inventar um dono distorce toda contagem por equipe"
            )
        if self.type.requires_player and self.player_id is None:
            raise ValueError(f"{self.type} exige executante e veio sem player_id")
        if self.supersedes is not None and self.supersedes == self.id:
            raise ValueError("evento não pode suceder a si mesmo")
        # Revisão maior que 1 sem apontar o anterior quebra a cadeia: não há
        # como reconstruir o que se sabia antes.
        if self.revision > 1 and self.supersedes is None:
            raise ValueError(
                f"revisão {self.revision} sem `supersedes`: a cadeia de correção fica quebrada "
                "e 'o que sabíamos antes' deixa de ter resposta"
            )
        if self.start_location is not None and self.end_location is not None:
            self.start_location.assert_comparable(self.end_location)

    @classmethod
    def record(
        cls,
        *,
        match_id: MatchId,
        type: EventType,
        clock: MatchClock,
        sequence: int,
        provenance: DataProvenance,
        quality: DataQuality,
        team_id: TeamId | None = None,
        player_id: PlayerId | None = None,
        start_location: PitchCoordinate | None = None,
        end_location: PitchCoordinate | None = None,
        detail: EventDetail | None = None,
    ) -> Self:
        """A primeira revisão de um fato."""
        return cls(
            id=uuid.uuid4(),
            match_id=match_id,
            type=type,
            clock=clock,
            sequence=sequence,
            provenance=provenance,
            quality=quality,
            team_id=team_id,
            player_id=player_id,
            start_location=start_location,
            end_location=end_location,
            detail=detail,
        )

    def correct_to(
        self,
        *,
        provenance: DataProvenance,
        quality: DataQuality,
        team_id: TeamId | None = None,
        player_id: PlayerId | None = None,
        start_location: PitchCoordinate | None = None,
        end_location: PitchCoordinate | None = None,
        detail: EventDetail | None = None,
        clock: MatchClock | None = None,
    ) -> tuple[Self, Self]:
        """A correção. Devolve (o anterior marcado, a revisão nova).

        DEVOLVE OS DOIS de propósito: quem chama precisa persistir ambos, e
        uma assinatura que devolvesse só o novo deixaria o anterior sem marca
        — indistinguível de uma revisão ainda válida.

        A procedência é a da CORREÇÃO, não a do original: quem corrigiu e
        quando é justamente o que se quer saber depois.
        """
        if self.status is EventStatus.CANCELLED:
            raise ValueError(
                "evento cancelado não se corrige: ele não aconteceu. "
                "Se voltou a valer, registre um evento novo."
            )
        anterior = self._with_status(EventStatus.CORRECTED)
        nova = type(self)(
            id=uuid.uuid4(),
            match_id=self.match_id,
            type=self.type,
            clock=clock or self.clock,
            sequence=self.sequence,
            provenance=provenance,
            quality=quality,
            team_id=team_id if team_id is not None else self.team_id,
            player_id=player_id if player_id is not None else self.player_id,
            start_location=start_location or self.start_location,
            end_location=end_location or self.end_location,
            detail=detail if detail is not None else self.detail,
            revision=self.revision + 1,
            supersedes=self.id,
            status=EventStatus.ACTIVE,
        )
        return anterior, nova

    def cancel(self) -> Self:
        """O fato foi anulado — VAR, erro de coleta.

        Não apaga: a linha permanece, e a diferença entre "não aconteceu" e
        "nunca foi registrado" continua visível.
        """
        if self.status is EventStatus.CANCELLED:
            raise ValueError("evento já cancelado")
        return self._with_status(EventStatus.CANCELLED)

    def _with_status(self, status: EventStatus) -> Self:
        return type(self)(
            id=self.id,
            match_id=self.match_id,
            type=self.type,
            clock=self.clock,
            sequence=self.sequence,
            provenance=self.provenance,
            quality=self.quality,
            team_id=self.team_id,
            player_id=self.player_id,
            start_location=self.start_location,
            end_location=self.end_location,
            detail=self.detail,
            revision=self.revision,
            supersedes=self.supersedes,
            status=status,
        )

    @property
    def is_current_truth(self) -> bool:
        return self.status.is_current_truth

    def __str__(self) -> str:
        return f"{self.type}@{self.clock} #{self.sequence} r{self.revision} [{self.status}]"


def current_truth(
    events: tuple[CanonicalMatchEvent, ...],
) -> tuple[CanonicalMatchEvent, ...]:
    """A verdade reconciliada: só as revisões ativas, em ordem.

    ORDENAÇÃO EXPLÍCITA por (período, minuto, acréscimo, sequência). A ordem
    de chegada não serve — provedores entregam fora de ordem — e uma ordenação
    implícita muda entre execuções, o que quebra determinismo (Constituição
    §9).
    """
    ativos = [e for e in events if e.is_current_truth]
    return tuple(
        sorted(
            ativos,
            key=lambda e: (
                e.clock.period.value,
                e.clock.minute,
                e.clock.stoppage,
                e.sequence,
            ),
        )
    )
