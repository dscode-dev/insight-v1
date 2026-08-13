"""O placar — e por que dois inteiros não bastam.

UM 1-1 QUE FOI 4-2 NOS PÊNALTIS NÃO É UM 4-2. Achatar tudo em "placar final"
apaga a diferença entre um jogo decidido no tempo normal e um que foi ao
limite, e essas são situações opostas para qualquer descrição de contexto.

Pior: uma disputa de pênaltis somada ao placar FALSIFICA o jogo corrido. Um
histórico de gols marcados que inclua pênaltis de desempate infla o ataque de
todo clube que foi a decisões.

TRÊS ESCOPOS, SEPARADOS:

    regular_time   os 90 minutos. Sempre existe.
    extra_time     a prorrogação, quando houve. Placar ACUMULADO com o normal,
                   que é como o futebol o conta.
    penalties      a disputa. NÃO é gol, e não entra em nenhuma soma de gols.

O DESFECHO É DERIVADO, NUNCA INFORMADO. Um campo `outcome` preenchido pela
fonte pode discordar do placar que a mesma fonte mandou — e aí há duas
verdades. Aqui ele é calculado, e a contradição deixa de ser possível.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Self, final


class Outcome(StrEnum):
    HOME = "HOME"
    DRAW = "DRAW"
    AWAY = "AWAY"


@final
@dataclass(frozen=True, slots=True)
class Score:
    """Gols de cada lado num escopo."""

    home: int
    away: int

    def __post_init__(self) -> None:
        if self.home < 0 or self.away < 0:
            raise ValueError(f"placar negativo: {self.home}-{self.away}")
        # 30 é folgado para futebol e ainda pega coluna trocada ou parse
        # errado, que é a forma real do defeito.
        if self.home > 30 or self.away > 30:
            raise ValueError(f"placar implausível: {self.home}-{self.away}")

    @property
    def outcome(self) -> Outcome:
        if self.home > self.away:
            return Outcome.HOME
        if self.away > self.home:
            return Outcome.AWAY
        return Outcome.DRAW

    @property
    def total(self) -> int:
        return self.home + self.away

    @property
    def margin(self) -> int:
        return abs(self.home - self.away)

    def __str__(self) -> str:
        return f"{self.home}-{self.away}"


@final
@dataclass(frozen=True, slots=True)
class MatchResult:
    """O resultado completo, com cada escopo no seu lugar.

    INFORMAÇÃO PÓS-JOGO. Nada que descreva um estado ANTERIOR da partida pode
    ler isto — ver ADR-0007 e a Constituição §1. Um estado do minuto 63 que
    consulte o placar final está se descrevendo com a resposta.
    """

    regular_time: Score
    extra_time: Score | None = None
    penalties: Score | None = None

    def __post_init__(self) -> None:
        # A prorrogação é ACUMULADA: quem estava 1-0 aos 90 não pode estar
        # 0-0 aos 120. Um placar de prorrogação menor que o do tempo normal é
        # coluna trocada.
        if self.extra_time is not None and (
            self.extra_time.home < self.regular_time.home
            or self.extra_time.away < self.regular_time.away
        ):
            raise ValueError(
                f"prorrogação ({self.extra_time}) tem menos gols que o tempo normal "
                f"({self.regular_time}): o placar da prorrogação é acumulado"
            )
        if self.penalties is not None:
            # Pênaltis só existem depois de um empate. Se o jogo teve
            # vencedor em campo, uma disputa registrada é dado de outra
            # partida.
            base = self.extra_time or self.regular_time
            if base.outcome is not Outcome.DRAW:
                raise ValueError(
                    f"disputa de pênaltis registrada num jogo que terminou {base} "
                    "— pênaltis só decidem empate"
                )
            if self.penalties.outcome is Outcome.DRAW:
                raise ValueError(
                    f"disputa de pênaltis empatada ({self.penalties}): ela existe para decidir"
                )
        # Prorrogação sem estar empatado aos 90 é a mesma classe de erro.
        if self.extra_time is not None and self.regular_time.outcome is not Outcome.DRAW:
            raise ValueError(
                f"prorrogação num jogo que terminou {self.regular_time} no tempo normal"
            )

    @property
    def goals(self) -> Score:
        """Os GOLS da partida — prorrogação incluída, pênaltis nunca.

        É este o placar que alimenta qualquer estatística de gols. Somar
        pênaltis aqui é o defeito que este módulo existe para impedir.
        """
        return self.extra_time or self.regular_time

    @property
    def outcome(self) -> Outcome:
        """Quem venceu, contando a decisão por pênaltis quando houve.

        DIFERENTE de `goals.outcome`: um 1-1 decidido nos pênaltis tem
        `goals.outcome == DRAW` e `outcome == HOME`. As duas leituras são
        legítimas e servem a perguntas diferentes — "como terminou o jogo" e
        "quem passou de fase".
        """
        if self.penalties is not None:
            return self.penalties.outcome
        return self.goals.outcome

    @property
    def went_to_extra_time(self) -> bool:
        return self.extra_time is not None

    @property
    def went_to_penalties(self) -> bool:
        return self.penalties is not None

    @property
    def decided_in_regular_time(self) -> bool:
        return self.regular_time.outcome is not Outcome.DRAW

    @classmethod
    def in_regular_time(cls, home: int, away: int) -> Self:
        """O caso comum: decidido em 90 minutos."""
        return cls(regular_time=Score(home=home, away=away))

    def __str__(self) -> str:
        partes = [str(self.regular_time)]
        if self.extra_time is not None:
            partes.append(f"aet {self.extra_time}")
        if self.penalties is not None:
            partes.append(f"pen {self.penalties}")
        return " · ".join(partes)
