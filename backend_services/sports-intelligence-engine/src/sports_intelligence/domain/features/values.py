"""O valor de uma feature — com a ausência ao lado, e não no lugar dele.

`FeatureValue` JÁ EXISTIA e continua sendo o que era (§41): um número que pode
não existir, com motivo. O que faltava é o CONTEXTO — de qual definição este
número é, sob qual corte foi calculado, de onde veio, e por que está ausente
quando está. É isso que `ComputedFeature` acrescenta, sem duplicar o primeiro.

    FeatureValue      «o número existe? qual é? por que não?»
    ComputedFeature   «de qual feature, sob qual corte, com qual procedência»

DUAS AUSÊNCIAS DIFERENTES, E AS DUAS PRECISAM SOBREVIVER:

    Unavailability        por que o NÚMERO não existe   (contrato do PR-01)
    FeatureAvailability   por que a FEATURE não existe  (§45)

Um chute sem xG publicado é `NOT_PUBLISHED` no primeiro. Uma feature que não
pôde ser calculada porque o fato era do futuro é `TEMPORALLY_UNAVAILABLE` no
segundo. Colapsá-las faria «a fonte não mediu» e «o corte proibiu» virarem a
mesma coisa — e elas exigem ações opostas.

MISSING ≠ ZERO CONTINUA ABSOLUTO (§42, §43). `red_cards_home = 0` é um fato:
ninguém foi expulso. `red_cards_home = indisponível` é outro: não se sabe. Um
`0` no lugar do segundo produz média que soma perfeitamente e está errada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self, final

from sports_intelligence.domain.features.availability import FeatureAvailability
from sports_intelligence.domain.features.leakage import LeakageReason
from sports_intelligence.domain.features.provenance import FeatureProvenance
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.shared.canonical import decimal_text
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.feature_value import FeatureValue


@final
@dataclass(frozen=True, slots=True)
class ComputedFeature:
    """Um valor de feature, com tudo que o explica.

    O QUE ELE CARREGA, e por que nada disso é opcional:

        definition_key/…    de QUAL feature este número é. Sem a impressão,
                            dois `shots_home_5m` de janelas diferentes seriam
                            o mesmo nome
        as_of               sob qual corte. Um valor sem corte é um número sem
                            instante, e comparar dois assim é comparar nada
        availability        por que existe ou não existe
        provenance          de onde veio

    `value` É `None` QUANDO A FEATURE NÃO ESTÁ DISPONÍVEL, e o construtor
    recusa a combinação incoerente: valor presente com disponibilidade
    negativa, ou disponível sem valor. É a mesma guarda do `FeatureValue`, um
    nível acima.
    """

    definition_key: str
    definition_fingerprint: str
    as_of: FeatureAsOf
    availability: FeatureAvailability
    value: FeatureValue | None = None
    #: Presente somente quando a indisponibilidade é TEMPORAL: ela diz qual
    #: guarda recusou o fato, e é o que separa «do futuro» de «não existe».
    leakage_reason: LeakageReason | None = None
    provenance: FeatureProvenance = field(default_factory=FeatureProvenance.none)
    detail: str = ""

    def __post_init__(self) -> None:
        if self.availability.is_available:
            if self.value is None:
                raise ValidationError(
                    f"feature {self.definition_key} declarada AVAILABLE sem valor — "
                    "disponível é uma afirmação sobre o número, e não sobre a "
                    "intenção de calculá-lo"
                )
            if self.leakage_reason is not None:
                raise ValidationError(
                    f"feature {self.definition_key} disponível com motivo de recusa"
                )
        elif self.value is not None:
            raise ValidationError(
                f"feature {self.definition_key} indisponível carregando valor: quem "
                "ler a máscara vai ignorar o número, e quem não ler vai usá-lo"
            )
        if (
            self.availability is FeatureAvailability.TEMPORALLY_UNAVAILABLE
            and self.leakage_reason is None
        ):
            raise ValidationError(
                f"feature {self.definition_key} recusada por tempo sem dizer qual "
                "guarda recusou — «indisponível» sem motivo não conserta nada"
            )

    # ------------------------------------------------------ construtores --

    @classmethod
    def available(
        cls,
        *,
        definition_key: str,
        definition_fingerprint: str,
        as_of: FeatureAsOf,
        value: float | int,
        provenance: FeatureProvenance,
    ) -> Self:
        return cls(
            definition_key=definition_key,
            definition_fingerprint=definition_fingerprint,
            as_of=as_of,
            availability=FeatureAvailability.AVAILABLE,
            value=FeatureValue.of(value),
            provenance=provenance,
        )

    @classmethod
    def unavailable(
        cls,
        *,
        definition_key: str,
        definition_fingerprint: str,
        as_of: FeatureAsOf,
        availability: FeatureAvailability,
        leakage_reason: LeakageReason | None = None,
        detail: str = "",
    ) -> Self:
        """A feature que NÃO pôde ser calculada.

        Ela não tem valor nem procedência de cálculo — `FeatureProvenance.none()`
        declara isso explicitamente, em vez de forjar um digest de conjunto
        vazio que a faria parecer calculada.
        """
        if availability.is_available:
            raise ValidationError("`unavailable` chamada com disponibilidade positiva")
        return cls(
            definition_key=definition_key,
            definition_fingerprint=definition_fingerprint,
            as_of=as_of,
            availability=availability,
            leakage_reason=leakage_reason,
            provenance=FeatureProvenance.none(),
            detail=detail,
        )

    # ------------------------------------------------------------ leitura --

    @property
    def is_available(self) -> bool:
        return self.availability.is_available

    @property
    def numeric(self) -> float | None:
        """O número, ou `None`. NUNCA zero por conveniência (§42)."""
        if self.value is None or not self.value.is_available:
            return None
        return self.value.require(f"feature {self.definition_key}")

    def as_canonical(self) -> dict[str, object]:
        """A forma que entra na impressão do snapshot.

        O NÚMERO ENTRA COMO TEXTO NORMALIZADO quando é decimal, pela mesma
        razão de sempre: `float` não é comparável entre plataformas do jeito
        que um hash exige.
        """
        return {
            "availability": self.availability.value,
            "definition_fingerprint": self.definition_fingerprint,
            "definition_key": self.definition_key,
            "leakage_reason": (
                None if self.leakage_reason is None else self.leakage_reason.value
            ),
            "provenance": self.provenance.as_canonical(),
            "value": _valor_canonico(self.numeric),
        }

    def __str__(self) -> str:
        if self.is_available:
            return f"{self.definition_key}={self.numeric}"
        motivo = "" if self.leakage_reason is None else f"/{self.leakage_reason.value}"
        return f"{self.definition_key}=∅ ({self.availability.value}{motivo})"


def _valor_canonico(numero: float | None) -> str | None:
    """O número na forma canônica, ou `None`.

    INTEIRO SAI COMO INTEIRO. `1.0` e `1` são o mesmo valor, e duas execuções
    que chegassem a ele por caminhos diferentes produziriam impressões
    diferentes se a forma não fosse normalizada.
    """
    if numero is None:
        return None
    from decimal import Decimal

    return decimal_text(Decimal(str(numero)))


@final
@dataclass(frozen=True, slots=True)
class FeatureAvailabilityMask:
    """Quais features de um conjunto existem — de primeira classe (§44, §102).

    ELA NÃO É UM DETALHE DE IMPLEMENTAÇÃO. A máscara acompanha o valor até a
    similaridade e o retrieval: comparar dois estados em que uma dimensão está
    ausente exige saber que ela está ausente, e um vetor que já esqueceu isso
    força quem compara a tratar o buraco como zero.

    ELA É ORDENADA, e a ordem é a do `FeatureSpace` — a mesma que vai virar
    vetor. Uma máscara com ordem própria seria uma segunda ordem para o mesmo
    conjunto, e o dia em que as duas divergissem, as dimensões trocariam de
    lugar em silêncio.
    """

    keys: tuple[str, ...]
    states: tuple[FeatureAvailability, ...]

    def __post_init__(self) -> None:
        if len(self.keys) != len(self.states):
            raise ValidationError(
                f"máscara com {len(self.keys)} chaves e {len(self.states)} estados"
            )
        if len(set(self.keys)) != len(self.keys):
            raise ValidationError("máscara com chave repetida")

    @classmethod
    def of(cls, features: tuple[ComputedFeature, ...]) -> Self:
        return cls(
            keys=tuple(f.definition_key for f in features),
            states=tuple(f.availability for f in features),
        )

    @property
    def available_count(self) -> int:
        return sum(1 for e in self.states if e.is_available)

    @property
    def is_complete(self) -> bool:
        return all(e.is_available for e in self.states)

    def state_of(self, key: str) -> FeatureAvailability:
        return self.states[self.keys.index(key)]

    def as_canonical(self) -> list[dict[str, str]]:
        return [
            {"availability": estado.value, "key": chave}
            for chave, estado in zip(self.keys, self.states, strict=True)
        ]

    def __str__(self) -> str:
        return f"{self.available_count}/{len(self.keys)} disponíveis"
