"""O relógio como dependência — a peça que torna o motor determinístico.

`datetime.now()` dentro do domínio faz o mesmo estado processado duas vezes
produzir resultados diferentes. Não é purismo: sem relógio injetado nenhum
teste consegue fixar "agora", e nenhum replay de uma partida passada consegue
reproduzir a conclusão que foi tomada naquele momento — porque o cálculo
consulta o relógio de hoje.

`FrozenClock` mora aqui, junto do protocolo, e não em `tests/`: ele é parte do
contrato. Um port cujo único uso real exige que cada teste invente o próprio
duplo é um port que convida a duplos divergentes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, final, runtime_checkable

from sports_intelligence.domain.shared.temporal import Instant, instant


@runtime_checkable
class ClockPort(Protocol):
    """A única fonte de "agora" para o motor."""

    def now(self) -> Instant: ...


@final
class SystemClock:
    """O relógio de verdade. Instanciado na borda, nunca no domínio."""

    def now(self) -> Instant:
        return instant(datetime.now(UTC))


@final
class FrozenClock:
    """Um relógio que não anda, ou anda quando mandam.

    Parte do contrato, não utilitário de teste: replay determinístico precisa
    de um relógio controlado tanto quanto os testes precisam.
    """

    def __init__(self, at: Instant) -> None:
        self._at = at

    def now(self) -> Instant:
        return self._at

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self._at = instant(self._at + timedelta(seconds=seconds))

    def set(self, at: Instant) -> None:
        self._at = at
