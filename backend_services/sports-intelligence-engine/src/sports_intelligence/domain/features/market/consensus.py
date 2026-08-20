"""O consenso de mercado — agregação robusta, e nunca previsão.

O QUE ESTE MÓDULO CALCULA (§50, §52). Para cada mercado canônico, três números
a partir das cotações elegíveis do `OddsState`:

    median_decimal_odds   o nível — onde o mercado está
    iqr_decimal_odds      a dispersão — quanto as casas discordam
    bookmaker_support     quantas casas sustentam os dois acima

`median` NÃO É PREVISÃO DO INSIGHT (§52). Ela é o que as casas publicaram,
agregado de forma resistente a extremo. A distinção importa porque o dia em que
o motor tiver previsão própria, as duas vão aparecer lado a lado — e confundi-las
faria o modelo aprender a prever o mercado em vez do jogo.

TODAS AS CASAS PESAM 1 (§73). Não há «qualidade de casa de aposta» na V1:
declarar que a Pinnacle vale mais que outra é uma decisão de modelagem com
evidência própria, e embuti-la aqui a esconderia dentro de um número que parece
uma média.

O QUE ESTE MÓDULO NÃO CALCULA, e cada ausência é decisão registrada:

    probabilidade implícita   §74 — `1/odds` sem remover a margem produz um
                              vetor que soma mais que 1 e parece probabilidade
    overround                 §75 — remover a margem exige política própria
    movimento                 §76, §77 — exige decidir linha de base, suporte
                              ao longo do tempo, conjunto variável de casas e
                              cadência de observação. Escondê-las numa feature
                              «delta» faria quatro decisões passarem por uma
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final, final

from sports_intelligence.domain.features.market.specs import CanonicalMarketSpec
from sports_intelligence.domain.features.quantiles import QuantileMethod, QuantileSummary
from sports_intelligence.domain.features.state.components import OddsQuoteState, OddsState
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.versioning import Version

#: A versão da política de referência — constante de módulo pelo mesmo motivo
#: da política de contexto: `default` de `dataclass` não chama função.
_V1: Final[Version] = Version(major=1, minor=0)

#: O algoritmo da impressão da política de consenso.
MARKET_POLICY_FINGERPRINT_ALGORITHM: Final[str] = "market-consensus-sha256-v1"

#: Quantas casas bastam para AFIRMAR o nível. Uma só já diz onde aquela casa
#: está, e isso é uma informação legítima — o que ela não sustenta é dispersão.
DEFAULT_MEDIAN_SUPPORT: Final[int] = 1

#: Quantas casas bastam para AFIRMAR a dispersão (§63). Quatro é o mínimo em
#: que os dois quartis são interpolados entre pontos distintos: com três, o Q1
#: e o Q3 caem sobre os próprios valores, e o IQR vira a amplitude entre o
#: primeiro e o terceiro — que é outra medida com o mesmo nome.
DEFAULT_IQR_SUPPORT: Final[int] = 4


@final
@dataclass(frozen=True, slots=True)
class MarketConsensusPolicy:
    """Como as cotações viram consenso. VERSIONADA (§64).

    POR QUE ELA É UM OBJETO E NÃO CONSTANTES. Os limiares e o método de quantil
    mudam o número — e quem comparar dois números produzidos por políticas
    diferentes precisa poder ver que são coisas diferentes. A impressão entra
    na identidade da feature de mercado.
    """

    version: Version = _V1
    median_minimum_support: int = DEFAULT_MEDIAN_SUPPORT
    iqr_minimum_support: int = DEFAULT_IQR_SUPPORT
    quantile_method: QuantileMethod = QuantileMethod.LINEAR_INTERPOLATED_V1
    #: Como duas cotações da MESMA casa no mesmo fluxo são tratadas (§56). O
    #: `OddsState` já garante uma por fluxo; isto declara a regra para quem
    #: lê o contrato sem ler o estado.
    duplicate_bookmaker: str = "LAST_KNOWN_PER_STREAM"

    def __post_init__(self) -> None:
        if self.median_minimum_support < 1:
            raise ValidationError(
                "suporte mínimo da mediana abaixo de 1: sem cotação nenhuma não há "
                "nível para afirmar"
            )
        if self.iqr_minimum_support < self.median_minimum_support:
            raise ValidationError(
                f"suporte de IQR ({self.iqr_minimum_support}) abaixo do suporte da "
                f"mediana ({self.median_minimum_support}): dispersão exige ao menos "
                "tanto quanto nível"
            )

    def as_canonical(self) -> dict[str, object]:
        return {
            "algorithm": MARKET_POLICY_FINGERPRINT_ALGORITHM,
            "duplicate_bookmaker": self.duplicate_bookmaker,
            "iqr_minimum_support": self.iqr_minimum_support,
            "median_minimum_support": self.median_minimum_support,
            "quantile_method": self.quantile_method.value,
            "version": str(self.version),
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def __str__(self) -> str:
        return f"consenso@{self.version}#{self.fingerprint[:12]}"


@final
@dataclass(frozen=True, slots=True)
class MarketConsensus:
    """O consenso de UM mercado canônico, num corte.

    OS TRÊS NÚMEROS TÊM DISPONIBILIDADES INDEPENDENTES. Uma casa só sustenta
    `median` e `support` e não sustenta `iqr` — e devolver `0` para o terceiro
    afirmaria que as casas concordam, quando não há com quem concordar.
    """

    spec: CanonicalMarketSpec
    #: As cotações que entraram, uma por casa, ordenadas canonicamente.
    quotes: tuple[OddsQuoteState, ...] = ()
    median: Decimal | None = None
    q1: Decimal | None = None
    q3: Decimal | None = None
    iqr: Decimal | None = None

    @property
    def support(self) -> int:
        """Quantas casas DISTINTAS sustentam este mercado (§55, §56)."""
        return len({q.bookmaker for q in self.quotes})

    @property
    def has_quotes(self) -> bool:
        return bool(self.quotes)

    def __str__(self) -> str:
        if self.median is None:
            return f"{self.spec}: sem cotação"
        return f"{self.spec}: mediana {self.median} · {self.support} casa(s)"


def compute_consensus(
    odds: OddsState, spec: CanonicalMarketSpec, *, policy: MarketConsensusPolicy
) -> MarketConsensus:
    """O consenso daquele mercado a partir do estado — puro (§43, §79).

    ELE NÃO VAI AO BANCO E NÃO REFILTRA POR TEMPO (§44). O `OddsState` do
    PR-05.2 já é a autoridade: ele carrega a ÚLTIMA cotação temporalmente
    elegível de cada fluxo, uma por casa. Reimplementar o filtro aqui criaria
    uma segunda regra temporal, que divergiria da primeira no caso difícil.
    """
    elegiveis = tuple(
        q
        for q in odds.quotes
        if spec.matches(market=q.market, selection=q.selection, line=q.line)
    )
    if not elegiveis:
        return MarketConsensus(spec=spec)

    # UMA COTAÇÃO POR CASA. O `OddsState` já garante uma por FLUXO, e o fluxo
    # inclui a casa — então isto é defesa em profundidade, e a ordem canônica
    # torna a escolha determinística caso a garantia caia.
    por_casa: dict[str, OddsQuoteState] = {}
    for cotacao in sorted(elegiveis, key=lambda q: (q.bookmaker, q.decimal_odds)):
        por_casa.setdefault(cotacao.bookmaker, cotacao)
    escolhidas = tuple(por_casa[c] for c in sorted(por_casa))

    valores = [_para_decimal(q) for q in escolhidas]
    resumo = QuantileSummary(valores, method=policy.quantile_method)
    suporte = len(escolhidas)
    tem_mediana = suporte >= policy.median_minimum_support
    tem_iqr = suporte >= policy.iqr_minimum_support
    return MarketConsensus(
        spec=spec,
        quotes=escolhidas,
        median=resumo.median if tem_mediana else None,
        q1=resumo.q1 if tem_iqr else None,
        q3=resumo.q3 if tem_iqr else None,
        iqr=resumo.iqr if tem_iqr else None,
    )


def _para_decimal(quote: OddsQuoteState) -> Decimal:
    """A cotação como `Decimal` (§53).

    O ESTADO GUARDA TEXTO CANÔNICO, e é de propósito: `float` faria duas casas
    que publicaram «o mesmo preço» comparar como diferentes. Aqui o texto volta
    a ser número sem passar por binário em momento nenhum.
    """
    try:
        valor = Decimal(quote.decimal_odds)
    except InvalidOperation as erro:  # pragma: no cover - o estado já valida
        raise ValidationError(
            f"cotação não decimal no estado: {quote.decimal_odds!r}"
        ) from erro
    if valor <= 0:
        # §68 — cotação decimal zero ou negativa não existe no domínio. Ela não
        # é «ausente»: é um dado inválido que chegou onde só há válidos.
        raise ValidationError(
            f"cotação decimal {valor} de {quote.bookmaker}: o domínio de odds não "
            "admite zero nem negativo"
        )
    return valor
