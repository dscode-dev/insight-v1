"""A aplicação da escala — e o valor cru que sobrevive a ela.

    Normalized(x) = (x - mediana) / IQR      quando o artefato é FITTED

`RawFeatureValue ≠ NormalizedFeatureValue` (§94, §218). A transformação NÃO
muta o valor cru: ela produz um objeto NOVO que carrega os dois. Isso não é
formalidade — é o que permite auditar. Seis meses depois, «este `+1,4` veio de
que número?» tem resposta, e ela está no mesmo objeto.

ISTO NÃO É Z-SCORE (§100). A nomenclatura importa porque `z` carrega uma
expectativa: média zero, desvio um, distribuição aproximadamente normal.
`(x - mediana) / IQR` não tem nenhuma das três. Chamá-lo de z-score faria
alguém aplicar a régua de três sigmas a uma escala que não a sustenta. O nome
aqui é `robust_scaled_value`.

O QUE ESTE MÓDULO NÃO FAZ, e cada ausência é decisão:

    epsilon          §125 — `max(iqr, 1e-6)` inventaria uma escala onde não há
    fallback         §127 — trocar para média/desvio seria outro método, e
                     método é identidade
    clipping         §136 — se a transformação produz `-12,4`, o valor é `-12,4`
    winsorização     §137 — cortar caudas é decisão estatística própria
    log              §138 — idem
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Self, final

from sports_intelligence.domain.features.availability import FeatureAvailability
from sports_intelligence.domain.features.fitting.artifact import (
    FitStatus,
    NormalizerFitArtifact,
)
from sports_intelligence.domain.features.values import ComputedFeature
from sports_intelligence.domain.shared.canonical import decimal_text
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import CompetitionId

#: Quantas casas o valor escalado mantém. Fixo e declarado pelo mesmo motivo do
#: quantil: sem quantização, `1/3` produziria uma dízima de precisão arbitrária
#: e duas execuções com contextos decimais diferentes dariam textos diferentes.
SCALED_DECIMAL_PLACES: Final[int] = 12

_QUANTUM: Final[Decimal] = Decimal(1).scaleb(-SCALED_DECIMAL_PLACES)

#: O nome do método, para que um valor escalado nunca se passe por z-score.
ROBUST_SCALING_METHOD: Final[str] = "MEDIAN_IQR_ROBUST_SCALE_V1"


@final
@dataclass(frozen=True, slots=True)
class NormalizedFeatureValue:
    """Um valor escalado, com o cru e o artefato ao lado (§95, §139).

    OS TRÊS VIAJAM JUNTOS. O valor cru, porque ele continua sendo o fato; o
    escalado, porque é o que o modelo consome; e a identidade do artefato,
    porque a escala só significa alguma coisa junto com a população que a
    produziu.

    `scaled` É `None` QUANDO A ESCALA NÃO EXISTE — e o cru continua ali (§128).
    Um normalizador que não conseguiu normalizar não invalida o número: ele só
    não produziu o segundo.
    """

    feature_key: str
    feature_fingerprint: str
    artifact_fingerprint: str
    competition_id: CompetitionId
    #: O valor CRU. Ele é `None` só quando a feature de origem já era
    #: indisponível (§133) — e aí não há o que escalar.
    raw: Decimal | None
    scaled: Decimal | None
    availability: FeatureAvailability
    method: str = ROBUST_SCALING_METHOD
    detail: str = ""

    def __post_init__(self) -> None:
        if self.availability.is_available and self.scaled is None:
            raise ValidationError(
                f"valor normalizado de {self.feature_key} declarado disponível sem "
                "número: «disponível» é afirmação sobre o valor"
            )
        if not self.availability.is_available and self.scaled is not None:
            raise ValidationError(
                f"valor normalizado de {self.feature_key} indisponível carregando "
                "número: quem ler a máscara vai ignorá-lo, e quem não ler vai usá-lo"
            )

    @property
    def is_available(self) -> bool:
        return self.availability.is_available

    def as_canonical(self) -> dict[str, object]:
        return {
            "artifact_fingerprint": self.artifact_fingerprint,
            "availability": self.availability.value,
            "competition_id": str(self.competition_id),
            "feature_fingerprint": self.feature_fingerprint,
            "feature_key": self.feature_key,
            "method": self.method,
            "raw": None if self.raw is None else decimal_text(self.raw),
            "scaled": None if self.scaled is None else decimal_text(self.scaled),
        }

    @classmethod
    def unavailable(
        cls,
        *,
        feature_key: str,
        feature_fingerprint: str,
        artifact: NormalizerFitArtifact,
        raw: Decimal | None,
        availability: FeatureAvailability,
        detail: str,
    ) -> Self:
        return cls(
            feature_key=feature_key,
            feature_fingerprint=feature_fingerprint,
            artifact_fingerprint=artifact.fingerprint,
            competition_id=artifact.competition_id,
            raw=raw,
            scaled=None,
            availability=availability,
            detail=detail,
        )

    def __str__(self) -> str:
        if not self.is_available:
            return f"{self.feature_key}=∅ ({self.availability.value})"
        return f"{self.feature_key}: {self.raw} → {self.scaled}"


@final
@dataclass(frozen=True, slots=True)
class RobustNormalizerTransformer:
    """Aplica um artefato a um valor cru. Puro (§129, §130).

    AS CONFERÊNCIAS ACONTECEM ANTES DA CONTA, e as duas primeiras levantam em
    vez de devolver indisponível: normalizar a feature errada ou a competição
    errada é DEFEITO DE QUEM CHAMOU, e devolver `None` esconderia o defeito
    atrás de uma ausência que parece normal.
    """

    artifact: NormalizerFitArtifact

    def transform(
        self,
        *,
        feature_key: str,
        feature_fingerprint: str,
        competition_id: CompetitionId,
        raw: Decimal | None,
    ) -> NormalizedFeatureValue:
        """O valor escalado, ou a ausência com motivo."""
        self.artifact.assert_applies_to(
            feature_fingerprint=feature_fingerprint, competition_id=competition_id
        )
        if raw is None:
            # §133 — sem valor cru não há o que escalar. Isso NÃO é defeito: a
            # feature de origem já dizia que não sabia.
            return NormalizedFeatureValue.unavailable(
                feature_key=feature_key,
                feature_fingerprint=feature_fingerprint,
                artifact=self.artifact,
                raw=None,
                availability=FeatureAvailability.SOURCE_UNAVAILABLE,
                detail="o valor cru não está disponível",
            )
        if self.artifact.status is FitStatus.INSUFFICIENT_SAMPLE:
            return NormalizedFeatureValue.unavailable(
                feature_key=feature_key,
                feature_fingerprint=feature_fingerprint,
                artifact=self.artifact,
                raw=raw,
                availability=FeatureAvailability.INSUFFICIENT_COVERAGE,
                detail=self.artifact.detail,
            )
        if self.artifact.status is FitStatus.DEGENERATE_SCALE:
            # §124 ao §127 — sem epsilon, sem troca de método. A escala não
            # existe, e o cru continua válido (§128).
            return NormalizedFeatureValue.unavailable(
                feature_key=feature_key,
                feature_fingerprint=feature_fingerprint,
                artifact=self.artifact,
                raw=raw,
                availability=FeatureAvailability.NOT_APPLICABLE,
                detail=self.artifact.detail,
            )

        assert self.artifact.median is not None
        assert self.artifact.iqr is not None
        escalado = (
            (raw - self.artifact.median) / self.artifact.iqr
        ).quantize(_QUANTUM).normalize()
        return NormalizedFeatureValue(
            feature_key=feature_key,
            feature_fingerprint=feature_fingerprint,
            artifact_fingerprint=self.artifact.fingerprint,
            competition_id=competition_id,
            raw=raw,
            scaled=escalado,
            availability=FeatureAvailability.AVAILABLE,
        )

    def transform_computed(
        self, computed: ComputedFeature, *, competition_id: CompetitionId
    ) -> NormalizedFeatureValue:
        """A mesma coisa, a partir de um `ComputedFeature` do PR-05.3.

        ELA CONVERTE UMA VEZ, pelo texto canônico. `float` direto para
        `Decimal` traria a representação binária inteira — `0.1` viraria
        `0.1000000000000000055511151231257827…`, e a mediana comparada com ele
        deixaria de bater.
        """
        numero = computed.numeric
        return self.transform(
            feature_key=computed.definition_key,
            feature_fingerprint=computed.definition_fingerprint,
            competition_id=competition_id,
            raw=None if numero is None else Decimal(str(numero)),
        )
