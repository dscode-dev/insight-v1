"""Zero e ausente são coisas diferentes, e o tipo impõe isso.

O DEFEITO QUE ESTE MÓDULO EXISTE PARA TORNAR IMPOSSÍVEL. Um clube sem
estatística de chutes tem `chutes_por_jogo` AUSENTE. Gravado como `0.0`, ele
não vira "não sei" — vira "não finaliza", que é o extremo inferior da escala.
Padronizado contra um corpus, esse zero fabricado vira um z-score muito
negativo, e todos os clubes sem estatística passam a parecer parecidíssimos
entre si por um motivo que não existe.

O erro não dispara nada. A dimensão fica populada, a média fecha, o vetor tem
o tamanho certo. Só as respostas ficam erradas.

POR QUE UM TIPO E NÃO UMA CONVENÇÃO. `float | None` resolveria, e some no
primeiro `or 0.0` que alguém escreve para calar o type checker. `FeatureValue`
não tem `__float__`: para obter o número é preciso chamar `.require()`, que
falha alto, ou `.or_default()`, que exige escrever o default e por isso deixa
a decisão visível no diff.

TRÊS ESTADOS, NÃO DOIS. "Ausente" tem causas diferentes e elas não se tratam
igual: um dado que a fonte nunca publicou não é o mesmo que um dado que ainda
não chegou, nem que um recusado por inconsistência. `Unavailability` guarda
qual foi, porque é o que diz se vale esperar, buscar outra fonte, ou desistir.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Self, final


class Unavailability(StrEnum):
    """Por que o valor não existe. Cada motivo pede uma ação diferente."""

    #: A fonte não publica esta informação. Esperar não adianta; ou outra
    #: fonte a traz, ou a dimensão fica ausente para sempre nesta competição.
    NOT_PUBLISHED = "NOT_PUBLISHED"
    #: Existe na fonte e ainda não chegou. Vale esperar.
    NOT_YET_OBSERVED = "NOT_YET_OBSERVED"
    #: Não há histórico suficiente para calcular — as primeiras partidas de um
    #: clube não têm janela móvel. Resolve-se sozinho com o tempo.
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    #: Chegou e foi recusado pela validação. NÃO é o mesmo que não ter vindo:
    #: aqui há um problema de qualidade na fonte, que alguém precisa ver.
    REJECTED_BY_VALIDATION = "REJECTED_BY_VALIDATION"
    #: A entidade não pôde ser resolvida, então o valor não tem a quem
    #: pertencer.
    UNRESOLVED_ENTITY = "UNRESOLVED_ENTITY"


@final
@dataclass(frozen=True, slots=True)
class FeatureValue:
    """Um número que pode não existir — e que não vira zero por descuido.

    Construa por `FeatureValue.of(x)` ou `FeatureValue.absent(motivo)`. O
    construtor direto aceita os dois estados e não deve ser usado fora daqui.
    """

    _value: float | None
    _reason: Unavailability | None

    def __post_init__(self) -> None:
        if (self._value is None) == (self._reason is None):
            raise ValueError(
                "FeatureValue é ou um número ou um motivo de ausência, nunca ambos nem nenhum"
            )
        if self._value is not None and not math.isfinite(self._value):
            # NaN e infinito envenenam toda média, desvio e distância a
            # jusante, e o sintoma aparece longe da causa.
            raise ValueError(f"valor não finito: {self._value!r}")

    @classmethod
    def of(cls, value: float | int) -> Self:
        return cls(_value=float(value), _reason=None)

    @classmethod
    def absent(cls, reason: Unavailability) -> Self:
        return cls(_value=None, _reason=reason)

    @property
    def is_available(self) -> bool:
        return self._value is not None

    @property
    def reason(self) -> Unavailability | None:
        return self._reason

    def require(self, context: str) -> float:
        """O número, ou um erro que diz o que faltava e para quê.

        `context` não é decoração: "feature ausente" não conserta nada, e
        "home_shots_rate ausente ao montar o vetor de estado" conserta.
        """
        if self._value is None:
            raise MissingFeatureError(context=context, reason=self._reason)
        return self._value

    def or_default(self, default: float) -> float:
        """O número, ou o default — que quem chama escreveu e assumiu.

        Existe porque às vezes o default é a resposta certa (um neutro
        declarado). O que ele impede é o default INVISÍVEL: aqui o valor
        aparece no diff e alguém pode discordar dele.
        """
        return self._value if self._value is not None else default

    def map(self, fn: object) -> Self:
        """Aplica a função quando há valor; propaga a ausência quando não há.

        Sem isto, toda transformação vira um `if` — e é no `if` esquecido que
        a ausência vira zero.
        """
        if self._value is None:
            return self
        if not callable(fn):
            raise TypeError("map exige um callable")
        return type(self).of(float(fn(self._value)))

    def __repr__(self) -> str:
        if self._value is None:
            return f"FeatureValue.absent({self._reason})"
        return f"FeatureValue.of({self._value!r})"


class MissingFeatureError(Exception):
    """Pedir um valor ausente é erro, e o erro diz onde e por quê."""

    def __init__(self, *, context: str, reason: Unavailability | None) -> None:
        self.context = context
        self.reason = reason
        super().__init__(f"{context}: valor ausente ({reason or 'motivo não registrado'})")


@final
@dataclass(frozen=True, slots=True)
class FeatureMask:
    """Quais dimensões um vetor de fato tem.

    POR QUE ELA VIAJA COM O VETOR. Duas partidas comparadas por similaridade
    podem ter conjuntos diferentes de dimensões disponíveis, e a comparação só
    é honesta sobre a interseção. Sem a máscara, a dimensão ausente entra como
    algum valor — e qualquer valor escolhido é uma afirmação que ninguém fez.

    A máscara também é o que permite dizer, na resposta, QUANTO da lente
    estava disponível. Uma resposta calculada sobre metade das dimensões que a
    pergunta pede não é uma versão mais fraca da mesma resposta.
    """

    available: frozenset[str]
    total: frozenset[str]

    def __post_init__(self) -> None:
        extras = self.available - self.total
        if extras:
            raise ValueError(
                f"máscara declara disponíveis dimensões que não existem no espaço: {sorted(extras)}"
            )

    @classmethod
    def from_values(cls, values: Mapping[str, FeatureValue]) -> Self:
        return cls(
            available=frozenset(k for k, v in values.items() if v.is_available),
            total=frozenset(values),
        )

    @property
    def missing(self) -> frozenset[str]:
        return self.total - self.available

    @property
    def coverage(self) -> float:
        """Fração das dimensões presentes. 1.0 quando o espaço é vazio —
        nada foi pedido, nada faltou."""
        if not self.total:
            return 1.0
        return len(self.available) / len(self.total)

    def intersect(self, other: FeatureMask) -> frozenset[str]:
        """As dimensões que AS DUAS têm — o único conjunto sobre o qual uma
        comparação entre elas é honesta."""
        return self.available & other.available

    def __contains__(self, dimension: object) -> bool:
        return dimension in self.available

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self.available))

    def __len__(self) -> int:
        return len(self.available)
