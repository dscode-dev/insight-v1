"""Odds: observações temporais imutáveis, sem nenhum cálculo.

O QUE ESTE MÓDULO DELIBERADAMENTE NÃO FAZ. Nada de probabilidade implícita,
overround, consenso, mediana, IQR ou velocidade de movimento. Tudo isso é
Odds Intelligence, num PR próprio — e cada um desses números tem uma decisão
por trás (qual casa, qual normalização, qual janela) que precisa ser
versionada como qualquer outro cálculo.

Guardá-los aqui os transformaria em fato, e eles são interpretação.

NADA DE `current_odds`. Um campo assim descreve "agora" e apaga o histórico —
e a diferença entre a cotação de abertura e a de fechamento é o sinal, não o
valor final. Cada `OddsQuote` é uma OBSERVAÇÃO com instante próprio; a série
delas é o dado.

`suspended` É INFORMAÇÃO, NÃO AUSÊNCIA. Uma casa suspende o mercado quando
algo aconteceu — gol iminente, lesão, VAR. Descartar quotes suspensas apaga
justamente o momento mais informativo. A quote entra, marcada.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Self, final

from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.provenance import DataProvenance
from sports_intelligence.domain.shared.temporal import Instant


@final
@dataclass(frozen=True, slots=True)
class BookmakerRef:
    """A casa de apostas. Slug, como `ProviderId` — poucas e nomeadas."""

    code: str

    def __post_init__(self) -> None:
        texto = self.code.strip().lower()
        if not texto:
            raise ValueError("BookmakerRef vazio")
        if not texto.replace("_", "").isalnum() or not texto[0].isalpha():
            raise ValueError(
                f"BookmakerRef {self.code!r} inválido: minúsculas, dígitos e underscore"
            )
        object.__setattr__(self, "code", texto)

    def __str__(self) -> str:
        return self.code


class OddsMarket(StrEnum):
    """Os mercados da V1. Fechado, pelo mesmo motivo dos outros catálogos."""

    MATCH_RESULT_1X2 = "MATCH_RESULT_1X2"
    TOTAL_GOALS = "TOTAL_GOALS"
    ASIAN_HANDICAP = "ASIAN_HANDICAP"
    BOTH_TEAMS_TO_SCORE = "BOTH_TEAMS_TO_SCORE"

    @property
    def requires_line(self) -> bool:
        """Se o mercado precisa de uma linha para significar algo.

        "Mais de 2,5 gols" e "mais de 3,5" são apostas diferentes com a mesma
        seleção `OVER`. Sem a linha, a cotação não diz nada — e guardá-la sem
        linha produziria uma série temporal que mistura mercados distintos.
        """
        return self in (OddsMarket.TOTAL_GOALS, OddsMarket.ASIAN_HANDICAP)

    @property
    def selections(self) -> frozenset[OddsSelection]:
        return _SELECOES[self]


class OddsSelection(StrEnum):
    """O lado da aposta."""

    HOME = "HOME"
    DRAW = "DRAW"
    AWAY = "AWAY"
    OVER = "OVER"
    UNDER = "UNDER"
    YES = "YES"
    NO = "NO"


#: Que seleções cada mercado admite. Sem isto, `TOTAL_GOALS` com seleção
#: `DRAW` seria aceito e produziria uma série que ninguém sabe ler.
_SELECOES: dict[OddsMarket, frozenset[OddsSelection]] = {
    OddsMarket.MATCH_RESULT_1X2: frozenset(
        {OddsSelection.HOME, OddsSelection.DRAW, OddsSelection.AWAY}
    ),
    OddsMarket.TOTAL_GOALS: frozenset({OddsSelection.OVER, OddsSelection.UNDER}),
    OddsMarket.ASIAN_HANDICAP: frozenset({OddsSelection.HOME, OddsSelection.AWAY}),
    OddsMarket.BOTH_TEAMS_TO_SCORE: frozenset({OddsSelection.YES, OddsSelection.NO}),
}


@final
@dataclass(frozen=True, slots=True)
class OddsQuote:
    """Uma cotação observada num instante. Imutável.

    `Decimal` E NÃO `float` para a cotação. Odds vêm como texto decimal
    (`1.95`) e serão comparadas, agrupadas e diferenciadas; `float` introduz
    ruído de representação que aparece quando duas casas cotam "o mesmo"
    preço e a comparação diz que não. O cálculo matemático converte para
    `float64` quando chegar — no PR que o fizer, com a decisão registrada.
    """

    match_id: MatchId
    bookmaker: BookmakerRef
    market: OddsMarket
    selection: OddsSelection
    decimal_odds: Decimal
    observed_at: Instant
    provenance: DataProvenance
    line: Decimal | None = None
    suspended: bool = False

    def __post_init__(self) -> None:
        if self.selection not in self.market.selections:
            raise ValueError(
                f"seleção {self.selection} não existe no mercado {self.market}; "
                f"as válidas são {sorted(s.value for s in self.market.selections)}"
            )
        # Cotação decimal <= 1 pagaria menos que a aposta: impossível, e é a
        # forma que uma coluna mal lida toma.
        if self.decimal_odds <= Decimal(1):
            raise ValueError(
                f"decimal_odds={self.decimal_odds} deve ser > 1: uma cotação decimal inclui "
                "o valor apostado, então 1,00 seria devolver o dinheiro"
            )
        if self.decimal_odds > Decimal(1000):
            raise ValueError(f"decimal_odds={self.decimal_odds} implausível")
        if self.market.requires_line and self.line is None:
            raise ValueError(
                f"{self.market} exige linha: 'mais de 2,5' e 'mais de 3,5' são apostas "
                "diferentes com a mesma seleção"
            )
        if not self.market.requires_line and self.line is not None:
            raise ValueError(f"{self.market} não tem linha, e veio com {self.line}")

    @classmethod
    def observe(
        cls,
        *,
        match_id: MatchId,
        bookmaker: BookmakerRef,
        market: OddsMarket,
        selection: OddsSelection,
        decimal_odds: Decimal | str,
        observed_at: Instant,
        provenance: DataProvenance,
        line: Decimal | str | None = None,
        suspended: bool = False,
    ) -> Self:
        """Uma observação. Aceita texto para que o adapter não converta.

        A conversão mora aqui porque `Decimal(1.95)` a partir de `float` já
        carrega o erro de representação que o `Decimal` existe para evitar —
        e `Decimal("1.95")` não.
        """
        return cls(
            match_id=match_id,
            bookmaker=bookmaker,
            market=market,
            selection=selection,
            decimal_odds=Decimal(str(decimal_odds)),
            observed_at=observed_at,
            provenance=provenance,
            line=Decimal(str(line)) if line is not None else None,
            suspended=suspended,
        )

    @property
    def market_key(self) -> tuple[str, str, str | None]:
        """O que identifica a SÉRIE à qual esta observação pertence.

        Casa, mercado e linha — não a seleção: as seleções de um mercado são
        lados da mesma cotação e se movem juntas.
        """
        return (str(self.bookmaker), self.market.value, str(self.line) if self.line else None)

    def __str__(self) -> str:
        linha = f" @{self.line}" if self.line is not None else ""
        marca = " [suspenso]" if self.suspended else ""
        return f"{self.bookmaker} {self.market}{linha} {self.selection}={self.decimal_odds}{marca}"


@final
@dataclass(frozen=True, slots=True)
class CanonicalOddsObservation:
    """Uma cotação HISTÓRICA canônica — cujo instante pode ser desconhecido.

    POR QUE ELA NÃO É UM `OddsQuote`. `OddsQuote` exige `observed_at`, e a
    exigência está certa para o caminho AO VIVO: ali cada tick tem instante, e
    a diferença entre abertura e fechamento é o sinal.

    Um arquivo histórico de futebol publica UMA cotação por casa e por partida,
    e não diz quando ela foi observada. As três saídas possíveis eram:

        exigir o instante             a família inteira ficaria de fora do
                                      corpus, por um metadado que a fonte não
                                      tem
        preencher com o kickoff       inventar um fato — e um fato inventado
                                      que parece plausível é o pior tipo
        registrar a ausência          `None`, que é a resposta honesta (§44)

    A terceira. `observed_at is None` significa «esta fonte não declara quando
    observou», e é distinto de qualquer instante — inclusive do instante em
    que NÓS lemos o arquivo, que descreve a nossa leitura e não a cotação.

    A IDENTIDADE DA V1 NÃO MUDA (§43). Ela continua sendo (partida, casa,
    mercado, seleção, linha) — exatamente o que o PR-03.2 entregou. O instante
    NÃO entra nela, e por isso duas leituras do mesmo arquivo produzem a mesma
    observação em vez de duas.

    NUNCA UMA MÉDIA (§42). `Bet365 @ 2.00` e `Pinnacle @ 2.05` são DUAS
    observações. `2.025` é um preço que casa nenhuma ofereceu, e ele apagaria
    justamente a dispersão entre casas, que é o sinal.
    """

    match_id: MatchId
    bookmaker: BookmakerRef
    market: OddsMarket
    selection: OddsSelection
    decimal_odds: Decimal
    provenance: DataProvenance
    line: Decimal | None = None
    #: `None` quando a fonte não declara. NUNCA o kickoff, nunca `now()`.
    observed_at: Instant | None = None

    def __post_init__(self) -> None:
        if self.selection not in self.market.selections:
            raise ValueError(
                f"seleção {self.selection} não existe no mercado {self.market}; "
                f"as válidas são {sorted(s.value for s in self.market.selections)}"
            )
        if self.decimal_odds <= Decimal(1):
            raise ValueError(
                f"decimal_odds={self.decimal_odds} deve ser > 1: uma cotação decimal "
                "inclui o valor apostado, então 1,00 seria devolver o dinheiro"
            )
        if self.decimal_odds > Decimal(1000):
            raise ValueError(f"decimal_odds={self.decimal_odds} implausível")
        if self.market.requires_line and self.line is None:
            raise ValueError(
                f"{self.market} exige linha: 'mais de 2,5' e 'mais de 3,5' são apostas "
                "diferentes com a mesma seleção"
            )
        if not self.market.requires_line and self.line is not None:
            raise ValueError(f"{self.market} não tem linha, e veio com {self.line}")

    @property
    def identity(self) -> tuple[str, str, str, str, str | None]:
        """A chave da V1 (§43). Sem instante, sem id de cotação do provedor."""
        return (
            str(self.match_id),
            str(self.bookmaker),
            self.market.value,
            self.selection.value,
            str(self.line) if self.line is not None else None,
        )

    @property
    def observation_time_is_known(self) -> bool:
        """Se a fonte declarou quando observou. Explícito porque a resposta
        `False` é informação, e um `observed_at is None` espalhado pelo código
        vira uma checagem que alguém esquece."""
        return self.observed_at is not None

    def __str__(self) -> str:
        linha = f" @{self.line}" if self.line is not None else ""
        quando = (
            self.observed_at.isoformat()
            if self.observed_at is not None
            else "instante não declarado"
        )
        return (
            f"{self.bookmaker} {self.market}{linha} {self.selection}={self.decimal_odds} ({quando})"
        )
