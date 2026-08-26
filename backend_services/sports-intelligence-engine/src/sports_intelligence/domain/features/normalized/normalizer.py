"""O normalizador CAUSAL deste PR — e por que ele não é o `DEFAULT_V1`.

HÁ DOIS CORTES CAUSAIS DIFERENTES, e confundi-los produziria ou um vazamento ou
um custo impossível:

    BEFORE_EVALUATED_MATCH   um ajuste POR PARTIDA avaliada. Máxima precisão
                             causal, e N ajustes para N partidas
    BEFORE_INSTANT           UM ajuste, cortado no instante que separa as duas
                             metades. Um conjunto de artefatos para o dataset

O `DEFAULT_V1_NORMALIZER` DECLARA O PRIMEIRO (PR-05.1 §85), e ele continua sendo
o contrato do caminho AO VIVO: quando um jogo é avaliado em tempo real, «antes
desta partida» é conhecível e é o corte certo.

ESTE PR PRECISA DO SEGUNDO, e a razão é a estrutura do dataset. A divisão já é
temporal e atômica por partida (ADR-0036): TODA linha de REFERÊNCIA vem de uma
partida iniciada antes de `reference_end_exclusive`, e TODA linha de AVALIAÇÃO
vem de uma iniciada em ou depois. Um corte em `reference_end_exclusive` é então
EXATAMENTE a população de referência — nem uma linha a mais.

    FitPopulation ⊆ REFERENCE     e é ⊆ por construção, não por conferência

E ELE É MAIS CONSERVADOR QUE O PRIMEIRO, e não menos. `BEFORE_EVALUATED_MATCH`
deixaria o ajuste da última partida da avaliação enxergar as anteriores DA
AVALIAÇÃO; `BEFORE_INSTANT` na fronteira não deixa nenhuma linha de avaliação
entrar em ajuste nenhum. É essa propriedade — e só ela — que torna
`∂ArtifactSet/∂EVALUATION = 0` demonstrável em vez de plausível.

O ESCOPO CONTINUA `COMPETITION`, pelo motivo de sempre (PR-05.1 §85, §86): uma
escala comum entre ligas apaga a diferença que se quer medir.
"""

from __future__ import annotations

from typing import Final

from sports_intelligence.domain.features.normalization import (
    FitCutoffKind,
    NormalizationMethod,
    NormalizationScope,
    NormalizerDefinition,
    NormalizerFitCutoff,
)
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import NormalizerVersion

#: A chave do normalizador deste PR. Ela é DIFERENTE da do `DEFAULT_V1`
#: («competition_median_iqr») de propósito: dois normalizadores com cortes
#: diferentes sob a mesma chave seriam comparados como se fossem a mesma medida.
DATASET_NORMALIZER_KEY: Final[str] = "competition_median_iqr_reference"

DATASET_NORMALIZER_VERSION: Final[NormalizerVersion] = NormalizerVersion(major=1, minor=0)


def causal_dataset_normalizer(
    *,
    reference_end_exclusive: Instant,
    fit_corpus_fingerprint: str | None = None,
) -> NormalizerDefinition:
    """O normalizador do dataset, cortado na fronteira das duas metades.

    A IMPRESSÃO DELE MUDA COM A FRONTEIRA, e isso é o comportamento desejado:
    dois conjuntos de artefatos ajustados até datas diferentes NÃO são a mesma
    medida, e a impressão é o que impede que sejam confundidos.

    A IMPRESSÃO DO CORPUS ENTRA QUANDO EXISTE (PR-05.1 §90). Ela responde «este
    normalizador foi ajustado sobre o quê» depois que o corpus avançou — e
    passá-la aqui é o que amarra o artefato à versão crua que o alimentou.
    """
    return NormalizerDefinition(
        key=DATASET_NORMALIZER_KEY,
        version=DATASET_NORMALIZER_VERSION,
        method=NormalizationMethod.MEDIAN_IQR,
        scope=NormalizationScope.COMPETITION,
        fit_cutoff=NormalizerFitCutoff(
            kind=FitCutoffKind.BEFORE_INSTANT,
            instant=reference_end_exclusive,
            fit_corpus_fingerprint=fit_corpus_fingerprint,
        ),
        description=(
            "mediana e intervalo interquartil, por competição, ajustado somente "
            "sobre a metade de REFERÊNCIA — as partidas iniciadas antes da "
            "fronteira temporal do dataset"
        ),
    )


def assert_fit_boundary_matches_split(
    normalizer: NormalizerDefinition,
    *,
    reference_end_exclusive: Instant,
) -> None:
    """A conferência que amarra o normalizador à divisão do dataset (§30).

    ELA EXISTE PORQUE AS DUAS FRONTEIRAS SÃO INDEPENDENTES NO CÓDIGO e têm de
    ser a mesma no domínio. Um normalizador cortado uma semana DEPOIS da
    fronteira produziria artefatos com algumas partidas de avaliação dentro — e
    o vazamento não apareceria em número nenhum: as medianas continuariam
    plausíveis, e a invariância sob mutação da avaliação simplesmente deixaria
    de valer, em silêncio.
    """
    corte = normalizer.fit_cutoff
    if corte.kind is not FitCutoffKind.BEFORE_INSTANT:
        raise ValidationError(
            f"o ajuste do dataset exige corte BEFORE_INSTANT e o normalizador "
            f"{normalizer.key} declara {corte.kind.value}: um corte relativo à "
            "partida avaliada não define UM conjunto de artefatos para o dataset",
            context={"normalizer": normalizer.key, "cutoff": corte.kind.value},
        )
    if corte.instant != reference_end_exclusive:
        raise ValidationError(
            f"o normalizador corta em {corte.instant} e a divisão do dataset em "
            f"{reference_end_exclusive}: a diferença entre as duas datas é "
            "exatamente o conjunto de partidas que vazaria da avaliação para a "
            "escala, sem aparecer em número nenhum",
            context={
                "normalizer_cutoff": str(corte.instant),
                "split_boundary": str(reference_end_exclusive),
            },
        )
    normalizer.assert_usable_for_live_comparable()
