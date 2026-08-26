"""As duas travessias numéricas — declaradas, versionadas e impressas.

HÁ UMA FRONTEIRA REAL NO MEIO DESTE PR, e ela não pode ser atravessada por
acidente:

    Dataset cru        float64        (PR-05.5.1: é o valor OFICIAL da feature)
        ↓  entrada
    Ajuste             Decimal        (PR-05.4: mediana e IQR exatos)
        ↓  saída
    Dataset normalizado  float64      (o valor oficial da representação nova)

DUAS LINHAS DE CÓDIGO DECIDEM ISSO, e as duas são fáceis de escrever sem
pensar:

    Decimal(valor)          o binário inteiro: 0.1 vira
                            0.1000000000000000055511151231257827…
    Decimal(str(valor))     o texto curto: 0.1 vira exatamente 0.1

AS DUAS SÃO DEFENSÁVEIS, e é por isso que a escolha precisa ser um CONTRATO em
vez de um detalhe. Duas execuções que escolhessem diferente produziriam
medianas diferentes sobre os mesmos dados, e nada no artefato diria qual foi.

A ESCOLHA DA V1 É A EXATA (`Decimal.from_float`). O dataset cru já declarou
`float64` como o valor oficial da feature (ADR-0037): o ajuste tem de
normalizar **o número que de fato está no arquivo**, e não uma aproximação
decimal mais bonita dele. `Decimal(str(x))` produziria uma mediana sobre
valores que ninguém gravou.

    IEEE754_FLOAT64_EXACT_TO_DECIMAL_V1

E A SAÍDA VOLTA A `float64`, declaradamente. O valor escalado é `Decimal`
exato; persisti-lo como `float64` é uma CONVERSÃO, e ela perde dígitos. Isso é
aceitável — e é dito: a representação oficial do dataset normalizado passa a
ser o `float64` derivado, com a política que o derivou impressa junto.

    NORMALIZED_FLOAT64_V1

NÃO CHAME ISSO DE «DECIMAL SEM PERDA». A escala é calculada em `Decimal` e
gravada em `float64`; afirmar que o arquivo guarda o `Decimal` seria falso.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.shared.errors import ValidationError

#: Quantas casas o valor escalado carrega antes de virar `float64`. Ele vem do
#: transformador do PR-05.4, e está repetido aqui como declaração: a política
#: de saída precisa dizer o que recebe.
SCALED_DECIMAL_PLACES: Final[int] = 12


@final
class FloatToDecimalBridge(StrEnum):
    """Como um `float64` do dataset cru vira `Decimal` para o ajuste.

    AS DUAS ESTÃO NO CATÁLOGO de propósito. A segunda não é uma opção morta: o
    transformador do PR-05.4 usa `Decimal(str(...))` no caminho de
    `ComputedFeature`, e nomear a política aqui é o que torna a diferença
    visível em vez de acidental.
    """

    #: `Decimal.from_float` — o valor binário EXATO que o arquivo guarda.
    IEEE754_EXACT = "IEEE754_FLOAT64_EXACT_TO_DECIMAL_V1"
    #: `Decimal(str(x))` — o texto curto que volta ao mesmo `float64`.
    SHORTEST_REPR = "SHORTEST_ROUNDTRIP_TEXT_TO_DECIMAL_V1"

    def to_decimal(self, value: float) -> Decimal:
        """A travessia. Ela RECUSA `NaN` e infinito (§41).

        FAIL-CLOSED, E NÃO «PULE ESTA OBSERVAÇÃO». Um `NaN` no dataset cru é um
        defeito a montante; deixá-lo entrar produziria uma mediana `NaN` que
        contaminaria a competição inteira, e ignorá-lo silenciosamente
        esconderia o defeito.
        """
        if not math.isfinite(value):
            raise ValidationError(
                f"valor não finito no dataset cru: {value!r}. Ele não pode entrar num "
                "ajuste nem num dataset normalizado — é defeito a montante, e "
                "silenciá-lo contaminaria a escala da competição inteira"
            )
        if self is FloatToDecimalBridge.IEEE754_EXACT:
            return Decimal.from_float(value)
        return Decimal(str(value))

    def as_canonical(self) -> dict[str, object]:
        return {"policy": self.value}


@final
class DecimalToFloatEncoding(StrEnum):
    """Como o `Decimal` escalado vira o valor persistido do dataset normalizado."""

    #: `float(escalado)`. A representação oficial do dataset normalizado.
    FLOAT64 = "NORMALIZED_FLOAT64_V1"

    def to_float(self, value: Decimal) -> float:
        """A conversão de saída. Ela também RECUSA não finito.

        UM `Decimal` GIGANTE VIRA `inf` EM `float`, e é o caso que importa:
        dividir por um IQR minúsculo produz números enormes, e um `inf` gravado
        no Parquet seria lido como um valor. O artefato `DEGENERATE_SCALE` já
        cobre o IQR zero; isto cobre o quase-zero.
        """
        convertido = float(value)
        if not math.isfinite(convertido):
            raise ValidationError(
                f"valor escalado {value} não cabe em float64 (virou {convertido!r}): "
                "gravá-lo faria o dataset normalizado publicar um infinito que a "
                "leitura trataria como número"
            )
        return convertido

    def as_canonical(self) -> dict[str, object]:
        return {
            "policy": self.value,
            "scaled_decimal_places": SCALED_DECIMAL_PLACES,
        }


#: As escolhas da V1.
DEFAULT_INPUT_BRIDGE: Final[FloatToDecimalBridge] = FloatToDecimalBridge.IEEE754_EXACT
DEFAULT_OUTPUT_ENCODING: Final[DecimalToFloatEncoding] = DecimalToFloatEncoding.FLOAT64


@final
@dataclass(frozen=True, slots=True)
class NumericBridge:
    """As duas políticas juntas, para quem transforma uma linha inteira."""

    input_bridge: FloatToDecimalBridge = DEFAULT_INPUT_BRIDGE
    output_encoding: DecimalToFloatEncoding = DEFAULT_OUTPUT_ENCODING

    def inbound(self, value: float | None) -> Decimal | None:
        """`None` continua `None` — ausente nunca vira zero (ADR-0009)."""
        return None if value is None else self.input_bridge.to_decimal(value)

    def outbound(self, value: Decimal | None) -> float | None:
        return None if value is None else self.output_encoding.to_float(value)

    def as_canonical(self) -> dict[str, object]:
        return {
            "input": self.input_bridge.as_canonical(),
            "output": self.output_encoding.as_canonical(),
        }


def float64_bytes(value: float) -> bytes:
    """Os oito bytes IEEE-754 do valor, em big-endian.

    ELE EXISTE PARA O DIGESTO (§70). Formatar `float` como texto para depois
    fazer hash faz a identidade da linha depender da rotina de formatação do
    interpretador — e `repr(float)` já mudou entre versões de Python. Os bytes
    do número não mudam.

    `NaN` E INFINITO SÃO RECUSADOS aqui também: eles têm representação em bytes,
    e deixá-los passar faria o digesto aceitar o que o resto do módulo recusa.
    """
    import struct

    if not math.isfinite(value):
        raise ValidationError(
            f"valor não finito no digesto: {value!r} — o dataset normalizado não "
            "publica não finitos, e o digesto não pode ser mais permissivo que ele"
        )
    # `-0.0` E `0.0` SÃO O MESMO NÚMERO e têm bytes diferentes. Normalizar o
    # zero negativo evita que duas execuções que cheguem a zero por caminhos
    # diferentes produzam digestos diferentes para o mesmo valor.
    if value == 0.0:
        value = 0.0
    return struct.pack(">d", value)
