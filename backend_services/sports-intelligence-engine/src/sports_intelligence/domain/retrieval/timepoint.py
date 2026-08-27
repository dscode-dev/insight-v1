"""O alinhamento temporal — e as duas componentes que a grade fixa.

A POLÍTICA É `EXACT_MATCH_TIME_POINT_V1`: um candidato só entra quando ocupa
EXATAMENTE a mesma posição de jogo que a query.

    query  FIRST_HALF 30    →  candidatos FIRST_HALF 30, e mais nada
    query  PRE_MATCH        →  candidatos PRE_MATCH, e mais nada

POR QUE EXATO, E NÃO UMA JANELA. Sem ele, três coisas quebram de uma vez:

    o relógio domina        `minute` é um eixo do espaço, e comparar o 20' com
                            o 85' faria a diferença de relógio ser a maior
                            parcela de uma distância que deveria falar de
                            futebol
    a mesma partida infla   minutos adjacentes da mesma partida são quase
                            idênticos entre si, e um top-K sob janela viraria
                            «os cinco minutos vizinhos do mesmo jogo»
    o baseline fica opaco   «vizinho no minuto 29» exige explicar o custo do
                            deslocamento antes de explicar a distância

`MatchTimePoint` TEM QUATRO COMPONENTES — fase, minuto, acréscimo e desempate —
e a grade fixa duas delas. `SnapshotGridPolicy` constrói todo corte intra-jogo
com `FeatureAsOf.at(match_id, period, minute)`: acréscimo é sempre `0` e não há
sequência de desempate. Isso NÃO é uma simplificação desta política; é o que a
grade é.

    A DIFERENÇA IMPORTA. Descartar acréscimo e desempate em silêncio seria
    comparar dois cortes que a grade nunca produziu e chamar de iguais. Aqui
    eles são RECONSTRUÍDOS com as constantes da grade e CONFERIDOS — um corte
    com acréscimo chegando deste dataset é defeito a montante, e para.

O QUE NÃO EXISTE AQUI, e cada ausência é decisão do §20: janela de ±1 ou ±5
minutos, tolerância dinâmica, «mesma fase basta», alinhamento de trajetória,
DTW. Políticas mais flexíveis podem existir depois — e vão precisar dizer o que
fazem com o custo do deslocamento.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self, final

from sports_intelligence.domain.features.temporal import (
    SEM_DESEMPATE,
    MatchTimePoint,
)
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import Period

#: O acréscimo que todo corte da grade carrega. A grade é de MINUTO, e um
#: corte «45+2» não existe nela.
GRID_STOPPAGE: Final[int] = 0

#: O desempate que todo corte da grade carrega — nenhum. O corte inclui tudo
#: daquele relógio, e não uma posição dentro dele.
GRID_SEQUENCE: Final[int] = SEM_DESEMPATE


@final
class TimeAlignmentPolicy(StrEnum):
    """Como um candidato se alinha temporalmente à query. Catálogo FECHADO.

    ELE TEM UM MEMBRO SÓ, e o catálogo existe assim mesmo: a política entra na
    impressão do universo, e um campo livre faria duas execuções sob regras
    diferentes produzirem impressões que se comparam.
    """

    #: Mesma fase, mesmo minuto, mesmo acréscimo, mesmo desempate.
    EXACT_MATCH_TIME_POINT = "EXACT_MATCH_TIME_POINT_V1"


@final
@dataclass(frozen=True, slots=True, order=True)
class GridTimePoint:
    """A posição de jogo de uma linha do dataset normalizado.

    ELA EXISTE PORQUE O PARQUET GUARDA `(period, minute)`, e o domínio fala em
    `MatchTimePoint`. A travessia entre os dois é onde alguém compararia texto
    com texto e deixaria passar um corte que a grade não produz — então ela
    acontece num lugar só, e confere.

    `order=True` E A FASE PRIMEIRO: a ordem é a do jogo, e ela vem de
    `Period.order` — a mesma tabela do registro canônico de eventos. Ordenar
    por texto poria `EXTRA_TIME_FIRST` antes de `FIRST_HALF`.
    """

    #: A ordem da fase, e não a fase: `dataclass(order=True)` compara na ordem
    #: de declaração, e o minuto não pode pesar mais que o período.
    period_order: int
    minute: int

    @classmethod
    def of(cls, period: Period, minute: int) -> Self:
        if minute < 0:
            raise ValidationError(
                f"posição de grade com minuto negativo: {minute}",
                context={"period": period.value, "minute": str(minute)},
            )
        return cls(period_order=period.order, minute=minute)

    @classmethod
    def from_columns(cls, *, period: str, minute: int) -> Self:
        """A posição a partir das colunas do Parquet normalizado.

        A FASE É VALIDADA CONTRA O CATÁLOGO, e não aceita texto qualquer: uma
        fase desconhecida vinda do arquivo é corrupção, e tratá-la como um
        rótulo opaco faria dois cortes incomparáveis passarem por alinhados.
        """
        try:
            fase = Period(period)
        except ValueError as erro:
            raise ValidationError(
                f"fase desconhecida no dataset normalizado: {period!r}. O alinhamento "
                "temporal compara POSIÇÕES DE JOGO, e um rótulo fora do catálogo não "
                "tem posição",
                context={"period": period},
            ) from erro
        return cls.of(fase, minute)

    @classmethod
    def from_match_time_point(cls, position: MatchTimePoint) -> Self:
        """A posição a partir do `MatchTimePoint` — CONFERINDO a grade.

        AS DUAS COMPONENTES QUE A GRADE FIXA são conferidas aqui, e a recusa é
        o ponto: um corte com acréscimo ou com desempate não vem da
        `SnapshotGridPolicy`, e alinhá-lo por `(fase, minuto)` diria que
        «45» e «45+3» são o mesmo instante de jogo.
        """
        if position.stoppage != GRID_STOPPAGE:
            raise ValidationError(
                f"posição com acréscimo {position.stoppage} no alinhamento de grade: "
                "a grade é de MINUTO, e alinhar por (fase, minuto) faria «45» e "
                f"«45+{position.stoppage}» passarem por o mesmo instante de jogo",
                context={"position": str(position)},
            )
        if position.sequence != GRID_SEQUENCE:
            raise ValidationError(
                f"posição com desempate {position.sequence} no alinhamento de grade: "
                "o corte da grade inclui tudo daquele relógio, e não uma posição "
                "dentro dele",
                context={"position": str(position)},
            )
        return cls.of(position.period, position.minute)

    # ------------------------------------------------------------ leitura --

    @property
    def period(self) -> Period:
        return _FASE_POR_ORDEM[self.period_order]

    @property
    def is_pre_match(self) -> bool:
        return self.period is Period.PRE_MATCH

    def as_match_time_point(self) -> MatchTimePoint:
        """De volta ao contrato temporal completo, com as constantes da grade.

        ELE RECONSTRÓI AS QUATRO COMPONENTES em vez de devolver duas: quem
        recebe uma posição de jogo tem direito ao contrato inteiro, e um par
        `(fase, minuto)` obrigaria cada chamador a lembrar sozinho que o
        acréscimo é zero.
        """
        return MatchTimePoint.of(self.period, self.minute, GRID_STOPPAGE)

    def aligns_with(self, other: GridTimePoint) -> bool:
        """Sob `EXACT_MATCH_TIME_POINT_V1`: a igualdade, e nada mais."""
        return self == other

    # -------------------------------------------------------------- forma --

    @property
    def text(self) -> str:
        """A forma canônica curta — é ela que entra nas impressões."""
        return f"{self.period.value}:{self.minute:03d}"

    def as_canonical(self) -> dict[str, object]:
        """A forma canônica COMPLETA, com as quatro componentes.

        O ACRÉSCIMO E O DESEMPATE ENTRAM, ainda que constantes. Eles são parte
        do contrato temporal, e omiti-los da impressão faria uma política
        futura que os usasse produzir impressões que colidem com as desta.
        """
        return {
            "alignment": TimeAlignmentPolicy.EXACT_MATCH_TIME_POINT.value,
            "minute": self.minute,
            "period": self.period.value,
            "sequence": None,
            "stoppage": GRID_STOPPAGE,
        }

    def __str__(self) -> str:
        return self.text


_FASE_POR_ORDEM: Final[dict[int, Period]] = {fase.order: fase for fase in Period}
