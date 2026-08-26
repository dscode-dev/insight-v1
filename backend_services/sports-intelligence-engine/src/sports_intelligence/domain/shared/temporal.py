"""Tempo: quatro instantes diferentes, e o relógio como dependência.

QUATRO CARIMBOS, E ELES NÃO SÃO INTERCAMBIÁVEIS.

    occurred_at   quando o fato aconteceu no mundo (o gol saiu)
    observed_at   quando o provedor viu (a API dele registrou)
    received_at   quando chegou até nós (o worker leu do stream)
    ingested_at   quando virou linha nossa (o adapter gravou)

Colapsá-los num "timestamp" só produz duas classes de erro que não disparam
nada. A primeira: ordenar eventos por chegada em vez de por ocorrência, o que
inverte a sequência de um jogo quando um provedor atrasa. A segunda: medir
frescor contra o relógio errado, o que faz um dado de ontem parecer novo
porque foi reprocessado hoje.

O RELÓGIO É INJETADO, SEMPRE. `datetime.now()` dentro do domínio torna todo
cálculo irreproduzível: o mesmo estado processado duas vezes dá resultados
diferentes, e nenhum teste consegue fixar o "agora". `ClockPort` é o único
caminho, e no domínio ele chega por parâmetro.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final, NewType, Self, final

#: Um instante em UTC, sempre com fuso. O tipo distinto existe para que uma
#: assinatura diga o que aceita: `datetime` sozinho não distingue um instante
#: absoluto de um horário local sem fuso.
Instant = NewType("Instant", datetime)


def instant(value: datetime) -> Instant:
    """Converte para UTC, ou recusa se não houver fuso.

    RECUSA E NÃO SUPÕE. Assumir UTC para um datetime ingênuo é o defeito
    clássico de ingestão de fonte pública: o arquivo publica em hora local,
    ninguém declara, e a partida cai no dia errado — e o dia costuma fazer
    parte da identidade.
    """
    if value.tzinfo is None:
        raise ValueError(
            "instante sem fuso horário: o fuso precisa ser declarado pela fonte, nunca suposto"
        )
    return Instant(value.astimezone(UTC))


def parse_instant(raw: str) -> Instant:
    """ISO-8601 com fuso explícito. `Z` é aceito como sinônimo de `+00:00`."""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as erro:
        raise ValueError(f"{raw!r} não é um instante ISO-8601") from erro
    return instant(parsed)


class Period(StrEnum):
    """A fase do jogo. `StrEnum` para que serialize legível."""

    PRE_MATCH = "PRE_MATCH"
    FIRST_HALF = "FIRST_HALF"
    HALF_TIME = "HALF_TIME"
    SECOND_HALF = "SECOND_HALF"
    EXTRA_TIME_FIRST = "EXTRA_TIME_FIRST"
    EXTRA_TIME_BREAK = "EXTRA_TIME_BREAK"
    EXTRA_TIME_SECOND = "EXTRA_TIME_SECOND"
    PENALTY_SHOOTOUT = "PENALTY_SHOOTOUT"
    FULL_TIME = "FULL_TIME"

    @property
    def order(self) -> int:
        """A posição desta fase na ORDEM DO JOGO.

        POR QUE ELA MORA AQUI (PR-05.1 §10). Três módulos já carregavam a
        mesma tabela — o adapter de eventos, o canonicalizador e a
        serialização do corpus —, e os três a escreviam por extenso. Uma
        quarta cópia no motor de features seria a que finalmente divergiria, e
        a divergência apareceria como dois fatos do mesmo jogo em ordens
        diferentes conforme quem os ordenou.

        A ORDEM NÃO É A DECLARAÇÃO DO ENUM por acidente: ela é a do jogo, e
        `PRE_MATCH < FIRST_HALF < … < FULL_TIME` é uma afirmação sobre futebol,
        não sobre a sintaxe do arquivo.
        """
        return _ORDEM_DAS_FASES[self]

    @property
    def is_ball_in_play(self) -> bool:
        """Se o relógio da partida corre nesta fase.

        Separa o que é intervalo do que é jogo: uma janela móvel de pressão
        não pode contar quinze minutos de vestiário como quinze minutos sem
        finalização.
        """
        return self in (
            Period.FIRST_HALF,
            Period.SECOND_HALF,
            Period.EXTRA_TIME_FIRST,
            Period.EXTRA_TIME_SECOND,
        )


#: A ordem das fases, escrita UMA vez. Ela é consultada por `Period.order`, e
#: quem precisa ordenar fatos de uma partida usa a propriedade — nunca uma
#: cópia local.
_ORDEM_DAS_FASES: Final[dict[Period, int]] = {
    Period.PRE_MATCH: 0,
    Period.FIRST_HALF: 1,
    Period.HALF_TIME: 2,
    Period.SECOND_HALF: 3,
    Period.EXTRA_TIME_FIRST: 4,
    Period.EXTRA_TIME_BREAK: 5,
    Period.EXTRA_TIME_SECOND: 6,
    Period.PENALTY_SHOOTOUT: 7,
    Period.FULL_TIME: 8,
}


@final
@dataclass(frozen=True, slots=True)
class MatchClock:
    """O minuto da partida — que não é o tempo decorrido.

    POR QUE `minute` E `stoppage` SÃO SEPARADOS. O futebol numera os
    acréscimos como `45+3`, e achatá-los em `48` confunde o terceiro minuto de
    acréscimo do primeiro tempo com o terceiro minuto do segundo. São momentos
    táticos opostos, e uma janela móvel que os confunde mistura os dois.
    """

    period: Period
    minute: int
    stoppage: int = 0

    def __post_init__(self) -> None:
        if self.minute < 0:
            raise ValueError(f"minuto negativo: {self.minute}")
        if self.stoppage < 0:
            raise ValueError(f"acréscimo negativo: {self.stoppage}")
        if not self.period.is_ball_in_play and (self.minute or self.stoppage):
            raise ValueError(f"{self.period} não tem relógio correndo, mas veio {self.label}")

    @property
    def label(self) -> str:
        return f"{self.minute}+{self.stoppage}" if self.stoppage else str(self.minute)

    def __str__(self) -> str:
        return f"{self.period}:{self.label}"


@final
@dataclass(frozen=True, slots=True)
class ObservationTimes:
    """Os quatro carimbos de um fato, com a ordem que faz sentido garantida.

    A ORDEM É VERIFICADA, e não por rigor: um `observed_at` anterior ao
    `occurred_at` significa que o provedor viu antes de acontecer, o que é a
    assinatura de um fuso mal lido — o erro mais comum e mais silencioso da
    ingestão. Detectá-lo aqui é barato; detectá-lo depois exige explicar por
    que um jogo tem eventos fora de ordem.
    """

    occurred_at: Instant
    observed_at: Instant
    received_at: Instant
    ingested_at: Instant

    def __post_init__(self) -> None:
        if self.observed_at < self.occurred_at:
            raise ValueError(
                f"observed_at ({self.observed_at.isoformat()}) é anterior a occurred_at "
                f"({self.occurred_at.isoformat()}): o provedor não pode ver antes de acontecer — "
                "quase sempre um fuso lido errado"
            )
        if self.received_at < self.observed_at:
            raise ValueError("received_at é anterior a observed_at")
        if self.ingested_at < self.received_at:
            raise ValueError("ingested_at é anterior a received_at")

    @property
    def provider_lag(self) -> timedelta:
        """Quanto o provedor demorou para ver o que aconteceu."""
        return self.observed_at - self.occurred_at

    @property
    def pipeline_lag(self) -> timedelta:
        """Quanto NÓS demoramos depois que o provedor viu."""
        return self.ingested_at - self.observed_at

    @property
    def total_lag(self) -> timedelta:
        return self.ingested_at - self.occurred_at

    @classmethod
    def at_once(cls, moment: Instant) -> Self:
        """Os quatro no mesmo instante.

        Para dados nascidos internamente, onde ocorrência e ingestão são o
        mesmo evento. Nunca para dado de provedor: ali os quatro instantes
        são de fato diferentes, e igualá-los apaga a latência que a qualidade
        do dado depende de medir.
        """
        return cls(occurred_at=moment, observed_at=moment, received_at=moment, ingested_at=moment)
