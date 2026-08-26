"""Os mercados CANÔNICOS que viram dimensão — e por que eles são fixos.

O PROBLEMA QUE ESTE MÓDULO RESOLVE (§45, §99). Um `FeatureSpace` tem dimensão
FIXA: ela é a ordem dos eixos do vetor futuro, e entra na identidade do espaço.
Uma feature por casa de aposta descoberta faria a dimensão do espaço depender
de quantas casas o provedor publicou naquele corpus — e dois snapshots do mesmo
jogo, lidos de corpus diferentes, teriam tamanhos diferentes.

A saída é declarar os mercados por extenso. `CanonicalMarketSpec` é
`(mercado, seleção, linha)`, e o catálogo da V1 tem sete deles. A casa de
aposta NÃO aparece no espaço: ela é entrada e procedência (§72).

    dimensão do espaço  ←  catálogo declarado
    casas de aposta     →  agregação e procedência

O HANDICAP FICA DE FORA (§49). `ASIAN_HANDICAP` existe no modelo canônico e
exige linha — e a linha dele VARIA por jogo: `-0.5`, `-1.0`, `-1.25`. Fixar
uma produziria uma dimensão vazia na maioria das partidas; não fixar produziria
dimensão variável. As duas saídas são erradas, e a decisão de qual mercado de
handicap canonizar é própria.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, final

from sports_intelligence.domain.odds.models import OddsMarket, OddsSelection
from sports_intelligence.domain.shared.canonical import decimal_text
from sports_intelligence.domain.shared.errors import ValidationError


@final
@dataclass(frozen=True, slots=True, order=True)
class CanonicalMarketSpec:
    """UM mercado que vira três dimensões do espaço (§46).

    `line` É PARTE DA IDENTIDADE (§87). «Mais de 2,5 gols» e «mais de 3,5» são
    apostas diferentes com a mesma seleção `OVER`; sem a linha na chave e na
    impressão, as duas seriam a mesma feature e a agregação misturaria dois
    mercados.

    `key_fragment` é o pedaço que aparece na chave da feature. Ele é
    DECLARADO, e não derivado de `repr` de enum: um `repr` mudaria com a
    refatoração do enum e levaria toda a identidade junto (§69, §84).
    """

    key_fragment: str
    market: OddsMarket
    selection: OddsSelection
    line: Decimal | None = None

    def __post_init__(self) -> None:
        if self.selection not in self.market.selections:
            raise ValidationError(
                f"o mercado {self.market.value} não admite a seleção {self.selection.value}"
            )
        if self.market.requires_line and self.line is None:
            raise ValidationError(
                f"{self.market.value} exige linha: sem ela a cotação não diz nada, e "
                "a série mistura mercados distintos"
            )
        if not self.market.requires_line and self.line is not None:
            raise ValidationError(
                f"{self.market.value} não usa linha e recebeu {self.line}: ela mudaria "
                "a identidade da feature sem mudar o que ela mede"
            )
        if not self.key_fragment.strip():
            raise ValidationError("especificação de mercado sem fragmento de chave")

    @property
    def line_text(self) -> str | None:
        """A linha na forma canônica — a MESMA que o estado guarda.

        `OddsQuoteState.line` é texto produzido por `decimal_as_text`. Comparar
        `Decimal("2.5")` com a string `"2.5"` exigiria converter de um lado; o
        que este módulo faz é converter de uma vez e comparar texto com texto.
        """
        return None if self.line is None else decimal_text(self.line)

    def matches(self, *, market: str, selection: str, line: str | None) -> bool:
        """Se uma cotação do estado pertence a esta especificação."""
        return (
            market == self.market.value
            and selection == self.selection.value
            and (line or None) == self.line_text
        )

    def as_canonical(self) -> dict[str, object]:
        return {
            "line": self.line_text,
            "market": self.market.value,
            "selection": self.selection.value,
        }

    def __str__(self) -> str:
        linha = "" if self.line_text is None else f" {self.line_text}"
        return f"{self.market.value}{linha} {self.selection.value}"


#: A LINHA DE GOLS TOTAIS DA V1. Ela é 2,5 porque é a linha que praticamente
#: todo provedor publica em praticamente todo jogo — uma dimensão que existe
#: quase sempre. Uma linha rara produziria uma coluna quase toda indisponível.
TOTAL_GOALS_LINE_V1: Final[Decimal] = Decimal("2.5")

#: O CATÁLOGO FIXO da V1 (§47). Sete especificações, na ORDEM que vira a ordem
#: dos eixos do espaço — e ela é declarada, não alfabética.
MARKET_SPECS_V1: Final[tuple[CanonicalMarketSpec, ...]] = (
    CanonicalMarketSpec(
        key_fragment="1x2_home",
        market=OddsMarket.MATCH_RESULT_1X2,
        selection=OddsSelection.HOME,
    ),
    CanonicalMarketSpec(
        key_fragment="1x2_draw",
        market=OddsMarket.MATCH_RESULT_1X2,
        selection=OddsSelection.DRAW,
    ),
    CanonicalMarketSpec(
        key_fragment="1x2_away",
        market=OddsMarket.MATCH_RESULT_1X2,
        selection=OddsSelection.AWAY,
    ),
    CanonicalMarketSpec(
        key_fragment="totals_over_25",
        market=OddsMarket.TOTAL_GOALS,
        selection=OddsSelection.OVER,
        line=TOTAL_GOALS_LINE_V1,
    ),
    CanonicalMarketSpec(
        key_fragment="totals_under_25",
        market=OddsMarket.TOTAL_GOALS,
        selection=OddsSelection.UNDER,
        line=TOTAL_GOALS_LINE_V1,
    ),
    CanonicalMarketSpec(
        key_fragment="btts_yes",
        market=OddsMarket.BOTH_TEAMS_TO_SCORE,
        selection=OddsSelection.YES,
    ),
    CanonicalMarketSpec(
        key_fragment="btts_no",
        market=OddsMarket.BOTH_TEAMS_TO_SCORE,
        selection=OddsSelection.NO,
    ),
)
