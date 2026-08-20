"""Quantis EXATOS e determinísticos sobre `Decimal` — com o método declarado.

O DEFEITO QUE ESTE MÓDULO EXISTE PARA IMPEDIR (§58, §60, §61). «Mediana» e
«quartil» soam como conceitos únicos e não são: há pelo menos nove definições
de quantil amostral em uso, e bibliotecas diferentes escolhem diferentes. O
`statistics.quantiles` do Python usa exclusiva por padrão; o `numpy.percentile`
usa interpolação linear inclusiva; o R tem sete tipos numerados.

Trocar uma pela outra muda o Q1 de uma amostra de oito valores — e nada
denuncia. O IQR muda, a escala do normalizador muda, e todo valor normalizado
do histórico deixa de ser comparável com os novos. O sintoma aparece longe da
causa: alguém nota que os números «mudaram um pouquinho» depois de um
`pip install -U`.

    O MÉTODO É VERSIONADO E É NOSSO.

`LINEAR_INTERPOLATED_QUANTILE_V1` é a interpolação linear inclusiva —
equivalente ao tipo 7 do R e ao padrão do NumPy —, implementada aqui em
`Decimal` para que:

    1. o resultado não dependa de que biblioteca está instalada;
    2. a aritmética não seja binária, e `0.1 + 0.2` valha `0.3`;
    3. o método entre na impressão de quem o usa.

NÃO É APROXIMADO (§183, §184). Nada de t-digest, nada de mediana em fluxo. A V1
ordena a população inteira e indexa — `O(N log N)` de tempo e `O(N)` de
memória. Isso é aceitável porque o ajuste é offline; o dia em que não for, a
troca por um esboço será uma DECISÃO com método novo e versão nova, e não uma
otimização silenciosa.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import Decimal
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.shared.errors import ValidationError

#: Quantas casas decimais o resultado de um quantil interpolado mantém.
#:
#: ELE É FIXO E DECLARADO. Sem quantização, a interpolação entre `2.00` e
#: `2.05` com peso `1/3` produziria uma dízima de precisão arbitrária, e duas
#: execuções com contextos decimais diferentes dariam textos diferentes para o
#: mesmo número. Doze casas é folgado para cotação (duas) e para xG (três), e
#: pequeno o bastante para não carregar ruído.
QUANTILE_DECIMAL_PLACES: Final[int] = 12

_QUANTUM: Final[Decimal] = Decimal(1).scaleb(-QUANTILE_DECIMAL_PLACES)


@final
class QuantileMethod(StrEnum):
    """Como um quantil amostral é definido. Catálogo FECHADO.

    UM SÓ MÉTODO NA V1, e ele está nomeado. O catálogo existe para que o dia em
    que um segundo aparecer, os dois convivam com identidades distintas — e
    ninguém troque um pelo outro sem que a impressão mude.
    """

    #: Interpolação linear inclusiva: `h = (n-1)·p`, e o valor sai da
    #: interpolação entre `x[⌊h⌋]` e `x[⌈h⌉]`. É o tipo 7 do R e o padrão do
    #: NumPy — escolhido por ser o mais difundido, e não por ser o «certo»:
    #: não existe um certo, existe um DECLARADO.
    LINEAR_INTERPOLATED_V1 = "LINEAR_INTERPOLATED_QUANTILE_V1"


@final
class QuantileSummary:
    """Mediana e quartis de uma amostra, calculados uma vez.

    ELE NÃO É UM `dataclass` POR ACIDENTE: guarda a amostra ordenada para que
    os três quantis saiam de uma ordenação só. Calcular `median`, `q1` e `q3`
    em três chamadas independentes ordenaria a população três vezes — e numa de
    cem mil valores isso é a diferença entre um segundo e três.
    """

    __slots__ = ("_ordenada", "method")

    def __init__(
        self,
        values: Iterable[Decimal],
        *,
        method: QuantileMethod = QuantileMethod.LINEAR_INTERPOLATED_V1,
    ) -> None:
        ordenada = sorted(values)
        if not ordenada:
            raise ValidationError(
                "quantis de uma amostra vazia: não há valor nenhum sobre o qual "
                "interpolar, e devolver zero inventaria uma distribuição"
            )
        self._ordenada: Sequence[Decimal] = ordenada
        self.method = method

    @property
    def size(self) -> int:
        return len(self._ordenada)

    @property
    def minimum(self) -> Decimal:
        return self._ordenada[0]

    @property
    def maximum(self) -> Decimal:
        return self._ordenada[-1]

    def quantile(self, p: Decimal) -> Decimal:
        """O quantil `p` ∈ [0,1], por interpolação linear inclusiva.

            h = (n - 1) · p
            resultado = x[⌊h⌋] + (h - ⌊h⌋) · (x[⌈h⌉] - x[⌊h⌋])

        AMOSTRA DE UM ELEMENTO devolve o próprio elemento para qualquer `p`:
        `h = 0` sempre. Isso é correto e é exatamente por que a mediana admite
        suporte 1 e o IQR não — o IQR de um elemento seria zero, e zero
        significaria «não há dispersão», que é uma afirmação que uma observação
        sozinha não sustenta.
        """
        if not Decimal(0) <= p <= Decimal(1):
            raise ValidationError(f"quantil fora de [0,1]: {p}")
        if self.size == 1:
            return self._ordenada[0]
        posicao = (Decimal(self.size - 1) * p).quantize(_QUANTUM)
        inferior = int(posicao)
        fracao = posicao - Decimal(inferior)
        if fracao == 0:
            return self._ordenada[inferior]
        baixo = self._ordenada[inferior]
        alto = self._ordenada[inferior + 1]
        return (baixo + fracao * (alto - baixo)).quantize(_QUANTUM).normalize()

    @property
    def median(self) -> Decimal:
        return self.quantile(Decimal("0.5"))

    @property
    def q1(self) -> Decimal:
        return self.quantile(Decimal("0.25"))

    @property
    def q3(self) -> Decimal:
        return self.quantile(Decimal("0.75"))

    @property
    def iqr(self) -> Decimal:
        """`Q3 - Q1`.

        ELE PODE SER ZERO, E ZERO É UM VALOR. Quatro casas cotando exatamente
        `2.00` têm dispersão nula observada — o que é diferente de dispersão
        desconhecida. Quem decide se há suporte suficiente para AFIRMAR isso é
        a política de quem chama, e não este cálculo.
        """
        return (self.q3 - self.q1).quantize(_QUANTUM).normalize()

    def __str__(self) -> str:
        return f"n={self.size} mediana={self.median} IQR={self.iqr}"
