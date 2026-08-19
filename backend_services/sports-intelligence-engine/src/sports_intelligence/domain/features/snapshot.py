"""O contrato do que um cálculo de features PRODUZ — sem produzir nenhum ainda.

ELE NÃO SE CHAMA `MatchStateVector` (§62), e o nome importa. Um vetor é uma
lista de números com dimensões fixas; um snapshot é o RESULTADO de um cálculo,
com máscara de disponibilidade, procedência e identidade temporal. O vetor sai
do snapshot quando as features reais existirem — e antecipar o nome faria
parecer que elas já existem.

A IDENTIDADE É SEMÂNTICA, E ELA É A ENTREGA DESTE MÓDULO (§63, §64, §139):

    SameCorpus + SameFeatureSpace + SameAsOf + SameTemporalPolicy
        ⇒  SameFeatureSnapshot

Os quatro entram na impressão. O que NÃO entra é tudo que muda entre duas
execuções idênticas: id de execução, carimbo de criação, id de processo, id de
linha de banco (§141). Um snapshot que mudasse de identidade por ter sido
calculado de novo não serviria para comparar nada.

    corpus diferente          ⇒ identidade diferente   (§142)
    espaço diferente          ⇒ identidade diferente   (§143)
    política temporal outra   ⇒ identidade diferente   (§144)
    corte outro               ⇒ identidade diferente   (§145)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final, Self, final

from sports_intelligence.domain.features.availability import TemporalAvailabilityPolicy
from sports_intelligence.domain.features.context import CorpusSource
from sports_intelligence.domain.features.space import FeatureSpaceDefinition
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.features.values import (
    ComputedFeature,
    FeatureAvailabilityMask,
)
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError

#: O algoritmo da impressão do snapshot. Nomeado como os outros: dois hex de 64
#: caracteres de construções diferentes são indistinguíveis.
SNAPSHOT_FINGERPRINT_ALGORITHM: Final[str] = "feature-snapshot-sha256-v1"


@final
@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    """O estado de features de UMA partida, num corte (§61).

    O QUE ELE CARREGA:

        as_of                de qual instante é este estado
        space                qual conjunto ordenado de features
        source               de qual versão do corpus
        policy_fingerprint   sob qual causalidade
        features             os valores, NA ORDEM do espaço
        mask                 quais existem, e por que os outros não

    A ORDEM É VERIFICADA CONTRA O ESPAÇO. Um snapshot cujas features estejam
    fora da ordem declarada viraria, no dia em que houver vetor, um vetor com
    os eixos trocados — e a comparação entre ele e outro daria um número que
    parece uma distância.

    ELE NÃO CALCULA NADA. Recebe os valores prontos; o cálculo é de quem
    implementar as features, na fase seguinte.
    """

    as_of: FeatureAsOf
    space: FeatureSpaceDefinition
    source: CorpusSource
    policy_version: str
    policy_fingerprint: str
    features: tuple[ComputedFeature, ...]

    def __post_init__(self) -> None:
        esperadas = self.space.keys
        recebidas = tuple(f.definition_key for f in self.features)
        if recebidas != esperadas:
            raise ValidationError(
                f"o snapshot de {self.as_of.match_id} traz {list(recebidas)} e o "
                f"espaço {self.space.name} declara {list(esperadas)}. A ordem é parte "
                "da identidade do espaço: fora dela, os eixos trocam de lugar "
                "(PR-05.1 §52, §55)",
                context={"space": self.space.name},
            )
        for computada in self.features:
            declarada = self.space.definition_of(computada.definition_key)
            if computada.definition_fingerprint != declarada.fingerprint:
                raise ValidationError(
                    f"a feature {computada.definition_key} foi calculada sob a "
                    f"impressão {computada.definition_fingerprint[:12]} e o espaço "
                    f"declara {declarada.fingerprint[:12]}: são definições diferentes "
                    "com o mesmo nome (§33)",
                    context={"key": computada.definition_key},
                )
            if computada.as_of != self.as_of:
                raise ValidationError(
                    f"a feature {computada.definition_key} foi calculada em "
                    f"{computada.as_of.position} e o snapshot é de {self.as_of.position}"
                )

    @classmethod
    def of(
        cls,
        *,
        as_of: FeatureAsOf,
        space: FeatureSpaceDefinition,
        source: CorpusSource,
        policy: TemporalAvailabilityPolicy,
        features: tuple[ComputedFeature, ...],
    ) -> Self:
        return cls(
            as_of=as_of,
            space=space,
            source=source,
            policy_version=str(policy.version),
            policy_fingerprint=policy.fingerprint,
            features=features,
        )

    @property
    def mask(self) -> FeatureAvailabilityMask:
        """A máscara — derivada dos valores, e nunca guardada em paralelo.

        Guardá-la num campo abriria a chance de ela discordar dos valores, e a
        discordância seria silenciosa: quem lê a máscara veria uma dimensão
        disponível cujo valor está vazio.
        """
        return FeatureAvailabilityMask.of(self.features)

    @property
    def is_complete(self) -> bool:
        return self.mask.is_complete

    def value_of(self, key: str) -> ComputedFeature:
        for computada in self.features:
            if computada.definition_key == key:
                return computada
        raise ValidationError(f"o snapshot não contém a feature {key!r}")

    def as_canonical(self) -> dict[str, object]:
        """A forma canônica — e a lista do que NÃO entra é a decisão (§141).

        NÃO ENTRAM: id de execução, carimbo de criação, id de processo, id de
        linha. Eles mudam entre duas execuções do MESMO cálculo sobre o MESMO
        dado, e um snapshot que mudasse de identidade por isso não serviria
        para comparar nada.
        """
        return {
            "algorithm": SNAPSHOT_FINGERPRINT_ALGORITHM,
            "as_of": self.as_of.as_canonical(),
            "features": [f.as_canonical() for f in self.features],
            "feature_space": {
                "fingerprint": self.space.fingerprint,
                "name": self.space.name,
                "version": str(self.space.version),
            },
            "mask": self.mask.as_canonical(),
            "source": self.source.as_canonical(),
            "temporal_policy": {
                "fingerprint": self.policy_fingerprint,
                "version": self.policy_version,
            },
        }

    @property
    def fingerprint(self) -> str:
        """A impressão SEMÂNTICA do snapshot (§140)."""
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    @property
    def identity(self) -> str:
        """A identidade legível: partida, corte, espaço e impressão (§64)."""
        return (
            f"{self.as_of.match_id}@{self.as_of.position}"
            f"/{self.space.name}@{self.space.version}#{self.fingerprint[:16]}"
        )

    def __str__(self) -> str:
        return f"{self.identity} · {self.mask}"
