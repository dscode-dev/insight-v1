"""De onde veio um número de feature.

A PERGUNTA QUE ISTO EXISTE PARA RESPONDER: «este `4` saiu de quais fatos
canônicos?». Sem ela, uma feature é um número sem defesa — e o dia em que
alguém discordar dele, a única saída será recalcular tudo e torcer.

TRÊS COISAS, E ELAS NÃO SE MISTURAM:

    classe          o que este número É — observado, derivado, normalizado
    contribuições   QUAIS fatos canônicos entraram
    digest          a impressão determinística do conjunto que entrou

A LINHAGEM É LIMITADA POR DESENHO (§49). Uma feature de contagem sobre dez
minutos de um jogo movimentado pode ter centenas de contribuintes, e carregar
todos eles em memória, dentro de cada valor, multiplicaria o custo de um vetor
por três ordens de grandeza. O que viaja é: quantos foram, uma AMOSTRA
limitada, e o digest do conjunto INTEIRO — que é o que permite comparar duas
proveniências sem tê-las inteiras.

    mesmo conjunto de contribuintes  ⇒  mesmo digest       (§50)
    digests diferentes               ⇒  conjuntos diferentes

O DIGEST É SOBRE O CONJUNTO ORDENADO. Duas execuções que leem os mesmos fatos
em ordens diferentes produzem o mesmo digest; duas que leem fatos diferentes,
não. É essa propriedade que torna a proveniência comparável entre execuções.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Self, final

from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError

#: Quantos contribuintes a amostra carrega. Ele é pequeno de propósito: a
#: amostra é para o diagnóstico — «que fatos são esses?» —, e a linhagem
#: completa se reconstrói recalculando a feature sobre o mesmo corte, que é
#: determinístico.
CONTRIBUTION_SAMPLE_LIMIT: Final[int] = 16


@final
class FeatureProvenanceClass(StrEnum):
    """O que este número é, do ponto de vista da procedência (§40, §103).

    `OBSERVED_INPUT` NÃO SIGNIFICA «não derivado». Mesmo copiar um valor
    observado para uma representação matemática é derivação — o que a classe
    distingue é se houve TRANSFORMAÇÃO além do transporte. A distinção existe
    porque `xg` de fonte e `xg` calculado por modelo nunca podem ser
    comparados como se fossem a mesma coisa (ADR-0009).
    """

    #: O valor veio de um fato canônico sem transformação além do transporte.
    OBSERVED_INPUT = "OBSERVED_INPUT"
    #: Calculado a partir de fatos canônicos — contagem, diferença, razão.
    DERIVED_FROM_CANONICAL = "DERIVED_FROM_CANONICAL"
    #: Um valor derivado que passou por normalizador declarado.
    NORMALIZED = "NORMALIZED"
    #: Preenchido por imputação. NENHUM caminho produz isto na V1 (§101), e a
    #: classe existe para que, no dia em que alguém a produzir, o valor não
    #: possa se passar por observado.
    IMPUTED = "IMPUTED"


@final
@dataclass(frozen=True, slots=True, order=True)
class FeatureContribution:
    """UM fato canônico que entrou no cálculo.

    ELE É UMA REFERÊNCIA, e não uma cópia: `kind` diz de que espécie é o fato
    e `reference` o identifica no corpus — o id do evento canônico, a chave da
    cotação. Guardar o fato aqui duplicaria o corpus dentro da feature.
    """

    kind: str
    reference: str

    def __post_init__(self) -> None:
        if not self.kind.strip() or not self.reference.strip():
            raise ValidationError("contribuição sem espécie ou sem referência")

    def as_canonical(self) -> dict[str, str]:
        return {"kind": self.kind, "reference": self.reference}


@final
@dataclass(frozen=True, slots=True)
class FeatureProvenance:
    """A procedência de um valor de feature (§47, §48, §49).

    `count` E `sample` RESPONDEM PERGUNTAS DIFERENTES. O primeiro é a resposta
    a «quantos fatos sustentam este número» e ele é EXATO. A segunda é «quais
    são alguns deles», e ela é truncada — `sample_truncated` diz quando.
    Apresentar a amostra como se fosse o conjunto seria a mentira mais fácil
    de cometer aqui.
    """

    provenance_class: FeatureProvenanceClass
    count: int = 0
    sample: tuple[FeatureContribution, ...] = ()
    sample_truncated: bool = False
    #: O digest do conjunto COMPLETO de contribuintes. Vazio quando não há
    #: contribuinte nenhum — uma feature indisponível não tem procedência de
    #: cálculo, e forjar um digest de conjunto vazio a faria parecer calculada.
    contribution_digest: str = ""

    def __post_init__(self) -> None:
        if self.count < 0:
            raise ValidationError("procedência com contagem negativa")
        if len(self.sample) > CONTRIBUTION_SAMPLE_LIMIT:
            raise ValidationError(
                f"amostra de procedência com {len(self.sample)} contribuintes, acima "
                f"do teto de {CONTRIBUTION_SAMPLE_LIMIT}"
            )
        if len(self.sample) > self.count:
            raise ValidationError(
                "a amostra tem mais contribuintes que a contagem — um dos dois está "
                "errado, e o errado é sempre o que alguém vai citar"
            )

    @classmethod
    def of(
        cls,
        provenance_class: FeatureProvenanceClass,
        contributions: Iterable[FeatureContribution] = (),
    ) -> Self:
        """Monta a procedência a partir dos contribuintes.

        ELA ORDENA ANTES DE IMPRIMIR (§50). Duas execuções que leram os mesmos
        fatos em ordens diferentes precisam produzir o mesmo digest — senão a
        procedência diria «diferente» sobre cálculos idênticos, e a comparação
        entre execuções deixaria de valer.
        """
        ordenadas = tuple(sorted(set(contributions)))
        return cls(
            provenance_class=provenance_class,
            count=len(ordenadas),
            sample=ordenadas[:CONTRIBUTION_SAMPLE_LIMIT],
            sample_truncated=len(ordenadas) > CONTRIBUTION_SAMPLE_LIMIT,
            contribution_digest=_digest(ordenadas),
        )

    @classmethod
    def none(cls) -> Self:
        """A procedência de um valor que NÃO foi calculado.

        Ela existe para que «indisponível» não tenha procedência forjada:
        contagem zero, amostra vazia, digest vazio.
        """
        return cls(provenance_class=FeatureProvenanceClass.DERIVED_FROM_CANONICAL)

    def as_canonical(self) -> dict[str, object]:
        return {
            "class": self.provenance_class.value,
            "contribution_digest": self.contribution_digest,
            "count": self.count,
            "sample": [c.as_canonical() for c in self.sample],
            "sample_truncated": self.sample_truncated,
        }

    def __str__(self) -> str:
        return (
            f"{self.provenance_class.value}·{self.count}"
            f"[{self.contribution_digest[:12] or '—'}]"
        )


def _digest(contributions: Sequence[FeatureContribution]) -> str:
    if not contributions:
        return ""
    return hashlib.sha256(
        canonical_json([c.as_canonical() for c in contributions])
    ).hexdigest()


@final
@dataclass(frozen=True, slots=True)
class ProvenanceBuilder:
    """Acumula contribuições durante um cálculo. NÃO é `frozen` por dentro.

    Ele existe para que um futuro calculador não precise montar listas à mão e
    lembrar de ordenar. O resultado é imutável; o acumulador não viaja.
    """

    _itens: list[FeatureContribution] = field(default_factory=list)

    def add(self, kind: str, reference: str) -> None:
        self._itens.append(FeatureContribution(kind=kind, reference=reference))

    def finish(self, provenance_class: FeatureProvenanceClass) -> FeatureProvenance:
        return FeatureProvenance.of(provenance_class, self._itens)

    @property
    def count(self) -> int:
        return len(self._itens)
