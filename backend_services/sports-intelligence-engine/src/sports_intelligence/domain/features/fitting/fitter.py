"""O ajustador — exato, puro e sem população própria.

    NormalizerFitArtifact = Fit(FeaturePopulation, Competition, Cutoff)

ELE É PURO (§115, §117). Recebe a declaração, a definição da feature, a
população e as identidades de origem; devolve o artefato. Sem banco, sem
relógio, sem sorteio.

ELE NÃO ESCOLHE A POPULAÇÃO (§118). «Quais partidas, qual grade de cortes, qual
temporada, qual divisão de avaliação» são decisões científicas que ainda não
foram tomadas — elas são o PR-05.5. O que existe aqui é a máquina que, DADA uma
população, produz o artefato de forma reproduzível.

O AJUSTE É EXATO (§183, §184). Nada de mediana aproximada nem de esboço: a
população é ordenada e indexada, `O(N log N)` de tempo e `O(N)` de memória. O
ajuste é offline, e trocar exatidão por memória agora seria pagar um custo de
precisão antes de existir a pressão que o justifique.

O QUE ELE RECUSA, e cada recusa é uma forma de a escala mentir:

    escopo global           §109, §110 — uma escala comum entre ligas apaga a
                            diferença que se quer medir
    competição misturada    a população é de uma competição só, por construção
    corte retrospectivo     §112, §114 — para espaço comparável ao vivo
    amostra insuficiente    §121, §123 — mediana de uma amostra declarada
                            inadequada é um número que nega a própria política
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, final

from sports_intelligence.domain.features.definitions import FeatureDefinition
from sports_intelligence.domain.features.fitting.artifact import (
    FitStatus,
    NormalizerFitArtifact,
    cutoff_canonical,
)
from sports_intelligence.domain.features.fitting.population import FitPopulation
from sports_intelligence.domain.features.normalization import (
    NormalizationMethod,
    NormalizationScope,
    NormalizerDefinition,
)
from sports_intelligence.domain.features.quantiles import QuantileSummary
from sports_intelligence.domain.shared.errors import ValidationError

#: Quantas observações DISPONÍVEIS o ajuste exige (§121, §122).
#:
#: TRINTA, e o número tem motivo em vez de tradição: abaixo disso o IQR de uma
#: distribuição de futebol — que é assimétrica e tem cauda — passa a variar mais
#: entre amostras que entre competições, e a escala deixa de descrever a liga
#: para descrever o acaso da amostra. Ele é sobrescrevível pela declaração do
#: normalizador, que é onde a decisão pertence.
DEFAULT_MINIMUM_AVAILABLE_SAMPLES: Final[int] = 30

#: O nome do parâmetro que a declaração usa para sobrescrever o mínimo.
MINIMUM_SAMPLES_PARAMETER: Final[str] = "minimum_available_samples"


@final
@dataclass(frozen=True, slots=True)
class RobustNormalizerFitter:
    """Ajusta mediana e IQR por competição (§98, §115).

    O MÉTODO É `MEDIAN_IQR`, e o construtor recusa qualquer outro: um ajustador
    que aceitasse `Z_SCORE` e calculasse mediana produziria um artefato cujo
    método declarado não descreve o que ele contém.
    """

    definition: NormalizerDefinition

    def __post_init__(self) -> None:
        if self.definition.method is not NormalizationMethod.MEDIAN_IQR:
            raise ValidationError(
                f"o normalizador {self.definition.key} declara "
                f"{self.definition.method.value} e este ajustador calcula mediana e "
                "IQR: o artefato diria um método e conteria outro",
                context={"method": self.definition.method.value},
            )
        if self.definition.scope is NormalizationScope.GLOBAL:
            # §109, §110 — `GLOBAL` existe no catálogo para ser recusado.
            raise ValidationError(
                f"o normalizador {self.definition.key} tem escopo GLOBAL: a V1 ajusta "
                "por competição, e uma população cruzando ligas produz uma escala que "
                "não descreve nenhuma delas (PR-05.4 §109, §110)",
                context={"scope": self.definition.scope.value},
            )

    @property
    def minimum_available_samples(self) -> int:
        """O mínimo declarado — da política, e não deste código (§122)."""
        bruto = self.definition.parameters.get(MINIMUM_SAMPLES_PARAMETER)
        if bruto is None:
            return DEFAULT_MINIMUM_AVAILABLE_SAMPLES
        if not isinstance(bruto, int) or isinstance(bruto, bool) or bruto < 1:
            raise ValidationError(
                f"{MINIMUM_SAMPLES_PARAMETER} inválido em {self.definition.key}: {bruto!r}"
            )
        return bruto

    def fit(
        self,
        population: FitPopulation,
        *,
        feature: FeatureDefinition,
        source_corpus_fingerprint: str,
        source_space_fingerprint: str,
    ) -> NormalizerFitArtifact:
        """O artefato daquela população.

        ELE NÃO LEVANTA POR AMOSTRA PEQUENA NEM POR DISPERSÃO NULA. Os dois são
        RESULTADOS: um artefato `INSUFFICIENT_SAMPLE` e um `DEGENERATE_SCALE`
        existem, explicam-se, e impedem a transformação. Levantar obrigaria
        quem ajusta dez mil features a envolver cada uma num `try`, e o
        `except` engoliria também os defeitos de verdade.
        """
        if population.feature_key != feature.key:
            raise ValidationError(
                f"população de {population.feature_key} e definição de {feature.key}"
            )
        comum = {
            "feature_key": feature.key,
            "feature_version": str(feature.version),
            "feature_fingerprint": feature.fingerprint,
            "normalizer_key": self.definition.key,
            "normalizer_fingerprint": self.definition.fingerprint,
            "competition_id": population.competition_id,
            "source_corpus_fingerprint": source_corpus_fingerprint,
            "source_space_fingerprint": source_space_fingerprint,
            "population_count": population.size,
            "available_count": population.available_size,
            "population_digest": population.digest,
            "fit_cutoff": cutoff_canonical(self.definition),
        }

        if population.available_size < self.minimum_available_samples:
            return NormalizerFitArtifact(
                **comum,  # type: ignore[arg-type]
                status=FitStatus.INSUFFICIENT_SAMPLE,
                detail=(
                    f"{population.available_size} observação(ões) disponível(is), "
                    f"abaixo do mínimo declarado de {self.minimum_available_samples}"
                ),
            )

        resumo = QuantileSummary(population.values())
        if resumo.iqr == 0:
            # §124, §126 — a mediana É publicada: ela é observação válida. O que
            # não existe é escala, e o estado diz isso em vez de um epsilon.
            return NormalizerFitArtifact(
                **comum,  # type: ignore[arg-type]
                status=FitStatus.DEGENERATE_SCALE,
                median=resumo.median,
                q1=resumo.q1,
                q3=resumo.q3,
                iqr=Decimal(0),
                detail=(
                    "IQR nulo: todos os valores entre o primeiro e o terceiro quartil "
                    "são iguais, e não há dispersão pela qual dividir"
                ),
            )

        return NormalizerFitArtifact(
            **comum,  # type: ignore[arg-type]
            status=FitStatus.FITTED,
            median=resumo.median,
            q1=resumo.q1,
            q3=resumo.q3,
            iqr=resumo.iqr,
        )

    def assert_causal_for_live_comparable(self) -> None:
        """Recusa um ajuste retrospectivo para espaço comparável ao vivo (§114)."""
        self.definition.assert_usable_for_live_comparable()
