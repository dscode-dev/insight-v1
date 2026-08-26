"""O artefato de ajuste — os parâmetros da escala, com tudo que os explica.

    NormalizerFitArtifact = Fit(FeaturePopulation, Competition, Cutoff)

O QUE ELE CARREGA E POR QUÊ (§102). Um artefato é, no fundo, dois números:
mediana e IQR. Se ele carregasse só isso, seria impossível responder às
perguntas que aparecem seis meses depois — «este `+1,4` foi calculado contra
qual liga?», «o ajuste enxergou a temporada inteira?», «qual corpus?». Cada
campo aqui existe para que uma dessas perguntas tenha resposta.

O QUE NÃO ENTRA NA IDENTIDADE (§103): carimbo de criação, id de execução, id de
processo. Eles mudam entre dois ajustes do MESMO conteúdo, e um artefato que
mudasse de identidade por ter sido recalculado não serviria para comparar nada.

`DEGENERATE_SCALE` É UM ESTADO, E NÃO UM ERRO (§124, §126). Uma população em
que todos os valores são iguais tem IQR zero — o que é uma observação legítima
sobre aquela distribuição. O artefato existe, é válido, registra a mediana, e
declara que NÃO PODE ESCALAR. A alternativa seria dividir por zero, ou —
pior — somar um epsilon escondido (§125) e inventar uma escala.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.features.normalization import NormalizerDefinition
from sports_intelligence.domain.shared.canonical import canonical_json, decimal_text
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import CompetitionId

#: O algoritmo da impressão do artefato.
FIT_ARTIFACT_FINGERPRINT_ALGORITHM: Final[str] = "normalizer-fit-sha256-v1"


@final
class FitStatus(StrEnum):
    """O que o ajuste conseguiu afirmar. Catálogo FECHADO.

    TRÊS ESTADOS, e os três são resultados legítimos do ajuste — nenhum é
    exceção. `INSUFFICIENT_SAMPLE` e `DEGENERATE_SCALE` produzem artefatos que
    existem, explicam por que não escalam, e impedem a transformação de
    acontecer sem que ninguém decida.
    """

    #: Mediana e IQR afirmáveis; a transformação funciona.
    FITTED = "FITTED"
    #: Menos observações disponíveis que o mínimo declarado (§121, §123). Não
    #: há mediana publicada: calculá-la sobre uma amostra declarada inadequada
    #: seria produzir o número e negar a declaração.
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    #: Amostra suficiente e `IQR = 0` (§124, §126). A mediana É publicada — ela
    #: é observação válida —, e a escala não existe.
    DEGENERATE_SCALE = "DEGENERATE_SCALE"

    @property
    def can_transform(self) -> bool:
        return self is FitStatus.FITTED


@final
@dataclass(frozen=True, slots=True)
class NormalizerFitArtifact:
    """Os parâmetros de escala de UMA feature, em UMA competição. Imutável.

    ELE É O ÚNICO OBJETO DESTE PR QUE CARREGA ESTATÍSTICA CALCULADA. O PR-05.1
    entregou a DECLARAÇÃO do normalizador; este entrega o resultado do ajuste —
    e a separação continua: `NormalizerDefinition` diz COMO ajustar,
    `NormalizerFitArtifact` diz o que o ajuste ENCONTROU.
    """

    #: A feature ajustada — chave, versão e impressão. A impressão é o que
    #: impede um artefato de `shots_home_5m` normalizar `xg_home_5m` (§131).
    feature_key: str
    feature_version: str
    feature_fingerprint: str
    #: A declaração sob a qual o ajuste foi feito.
    normalizer_key: str
    normalizer_fingerprint: str
    #: A população: escopo e de onde ela veio.
    competition_id: CompetitionId
    source_corpus_fingerprint: str
    source_space_fingerprint: str
    population_count: int
    available_count: int
    population_digest: str
    #: O corte de ajuste, na forma canônica da declaração.
    fit_cutoff: dict[str, object]
    status: FitStatus
    #: Os parâmetros. `None` quando o estado não os afirma.
    median: Decimal | None = None
    q1: Decimal | None = None
    q3: Decimal | None = None
    iqr: Decimal | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.available_count > self.population_count:
            raise ValidationError(
                f"{self.available_count} disponíveis de {self.population_count} — o "
                "subconjunto é maior que o conjunto"
            )
        if self.status is FitStatus.FITTED:
            faltando = [
                nome
                for nome, valor in (
                    ("median", self.median),
                    ("q1", self.q1),
                    ("q3", self.q3),
                    ("iqr", self.iqr),
                )
                if valor is None
            ]
            if faltando:
                raise ValidationError(
                    f"artefato FITTED sem {faltando}: «ajustado» é uma afirmação "
                    "sobre os parâmetros, e não sobre a intenção de calculá-los"
                )
            assert self.iqr is not None
            if self.iqr <= 0:
                raise ValidationError(
                    f"artefato FITTED com IQR {self.iqr}: dispersão nula é "
                    f"{FitStatus.DEGENERATE_SCALE.value}, e não um ajuste válido"
                )
        if self.status is FitStatus.INSUFFICIENT_SAMPLE and self.median is not None:
            raise ValidationError(
                "artefato com amostra insuficiente publicando mediana: ou a amostra "
                "serve, ou o número não deveria existir (§123)"
            )
        if self.status is FitStatus.DEGENERATE_SCALE and self.iqr not in (
            None,
            Decimal(0),
        ):
            raise ValidationError(
                f"artefato DEGENERATE_SCALE com IQR {self.iqr}: o estado afirma dispersão nula"
            )

    @property
    def is_usable(self) -> bool:
        return self.status.can_transform

    def as_canonical(self) -> dict[str, object]:
        """A forma canônica — sem nada que mude entre dois ajustes iguais (§103)."""
        return {
            "algorithm": FIT_ARTIFACT_FINGERPRINT_ALGORITHM,
            "available_count": self.available_count,
            "competition_id": str(self.competition_id),
            "feature": {
                "fingerprint": self.feature_fingerprint,
                "key": self.feature_key,
                "version": self.feature_version,
            },
            "fit_cutoff": self.fit_cutoff,
            "iqr": None if self.iqr is None else decimal_text(self.iqr),
            "median": None if self.median is None else decimal_text(self.median),
            "normalizer": {
                "fingerprint": self.normalizer_fingerprint,
                "key": self.normalizer_key,
            },
            "population_count": self.population_count,
            "population_digest": self.population_digest,
            "q1": None if self.q1 is None else decimal_text(self.q1),
            "q3": None if self.q3 is None else decimal_text(self.q3),
            "source_corpus_fingerprint": self.source_corpus_fingerprint,
            "source_space_fingerprint": self.source_space_fingerprint,
            "status": self.status.value,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    @property
    def identity(self) -> str:
        return (
            f"{self.feature_key}@{self.competition_id}"
            f"/{self.normalizer_key}#{self.fingerprint[:16]}"
        )

    def assert_applies_to(self, *, feature_fingerprint: str, competition_id: CompetitionId) -> None:
        """Recusa o artefato errado — as duas confusões que importam.

        §131: um artefato de `shots_home_5m` não normaliza `xg_home_5m`. A
        comparação é por IMPRESSÃO, e não por chave: duas versões da mesma
        feature têm a mesma chave e escalas diferentes.

        §132: um artefato da Premier League não normaliza La Liga. Fail-closed,
        porque o valor resultante pareceria perfeitamente plausível.
        """
        if feature_fingerprint != self.feature_fingerprint:
            raise ValidationError(
                f"o artefato foi ajustado para {self.feature_key} "
                f"({self.feature_fingerprint[:12]}) e recebeu uma feature de "
                f"impressão {feature_fingerprint[:12]}: são features diferentes, e a "
                "escala de uma não descreve a outra (PR-05.4 §131)",
                context={"artifact_feature": self.feature_key},
            )
        if competition_id != self.competition_id:
            raise ValidationError(
                f"o artefato é da competição {self.competition_id} e recebeu um valor "
                f"de {competition_id}: ligas diferentes jogam futebol diferente, e uma "
                "escala comum apaga a diferença que se quer medir (§132)",
                context={"artifact_competition": str(self.competition_id)},
            )

    def __str__(self) -> str:
        if self.status is not FitStatus.FITTED:
            return f"{self.identity} · {self.status.value}"
        return f"{self.identity} · mediana {self.median} IQR {self.iqr}"


def cutoff_canonical(definition: NormalizerDefinition) -> dict[str, object]:
    """O corte na forma canônica — o mesmo que a declaração publica."""
    return definition.fit_cutoff.as_canonical()
