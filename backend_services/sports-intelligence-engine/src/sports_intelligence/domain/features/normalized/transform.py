"""A transformação de UMA linha — e as cinco decisões que ela toma por célula.

O CAMINHO DE UMA CÉLULA, na ordem em que as perguntas são feitas:

    a origem tinha valor?        não → SOURCE_VALUE_UNAVAILABLE
    o plano diz PASS_THROUGH?    sim → o MESMO float64, bit a bit
    a competição tem pacote?     não → ARTIFACT_NOT_AVAILABLE_FOR_COMPETITION
    o artefato ajustou?          não → ARTIFACT_INSUFFICIENT_SAMPLES
                                     ou ARTIFACT_DEGENERATE_SCALE
    ajustou                      → (x - mediana) / IQR

A PRIMEIRA PERGUNTA VEM ANTES DE TODAS, e a ordem importa: um eixo sem valor
cru numa competição sem pacote tem DUAS causas verdadeiras, e a que interessa é
a da origem — procurar o artefato de uma feature que nunca teve valor é
perseguir o problema errado.

`PASS_THROUGH` NÃO ATRAVESSA `Decimal` (§78). A tentação é uniformizar o
caminho — converter tudo para `Decimal`, transformar ou não, converter de volta
— e ela custaria a exatidão: `float → Decimal → float` volta ao mesmo número,
mas «volta ao mesmo número» é uma afirmação sobre a implementação da conversão,
e não sobre o contrato. O contrato aqui é BIT A BIT, e a única forma de
garanti-lo é não converter.

NÃO HÁ FALLBACK, E A AUSÊNCIA É O PONTO (§88, ADR-0035). Um eixo classificado
`ROBUST` cujo artefato saiu `DEGENERATE_SCALE` NÃO vira `PASS_THROUGH`. Se
virasse, a coluna teria unidades misturadas — gols normalizados numa
competição, gols crus na outra — e a distância entre duas partidas de ligas
diferentes seria calculada somando maçãs com laranjas, sem que nada no arquivo
denunciasse.

A RESOLUÇÃO POR COMPETIÇÃO É MEMOIZADA. Sem isso, cada célula de cada linha
faria uma varredura linear no plano e outra no pacote: cento e cinco por
cento e cinco por noventa e uma mil linhas é um bilhão de comparações de
`str` para responder perguntas que não mudam dentro de uma partição.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final, final

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.fitting.artifact import (
    FitStatus,
    NormalizerFitArtifact,
)
from sports_intelligence.domain.features.normalized.artifacts import (
    CompetitionNormalizerArtifactBundle,
    NormalizerArtifactSet,
)
from sports_intelligence.domain.features.normalized.bridge import NumericBridge
from sports_intelligence.domain.features.normalized.plan import (
    NormalizationPlan,
    TransformStrategy,
)
from sports_intelligence.domain.features.normalized.rows import (
    FITTABLE_SOURCE_STATES,
    NormalizationAvailability,
    NormalizedCell,
    NormalizedFeatureRow,
)
from sports_intelligence.domain.features.normalized.versions import (
    NormalizedFeatureRepresentationSpec,
)
from sports_intelligence.domain.shared.errors import ValidationError

_QUANTUM: Final[Decimal] = Decimal(1).scaleb(-12)

#: Do estado do artefato para o motivo da célula. O mapa é explícito para que
#: um estado novo em `FitStatus` quebre aqui em vez de cair num `else`.
_MOTIVO_POR_ESTADO: Final[dict[FitStatus, NormalizationAvailability]] = {
    FitStatus.INSUFFICIENT_SAMPLE: (NormalizationAvailability.ARTIFACT_INSUFFICIENT_SAMPLES),
    FitStatus.DEGENERATE_SCALE: NormalizationAvailability.ARTIFACT_DEGENERATE_SCALE,
}


@final
@dataclass(frozen=True, slots=True)
class RawFeatureRowView:
    """Uma linha CRUA como o leitor a entrega — colunas, e não objetos.

    ELA NÃO É `MaterializedFeatureRow`. Reconstruir o `FeatureSnapshot` inteiro
    a partir do Parquet para depois descartá-lo custaria a construção de cento e
    cinco `FeatureValue` por linha para ler cento e cinco números. O que a
    normalização precisa é o que está aqui: as chaves, os valores e a máscara.
    """

    key: HistoricalFeatureSnapshotKey
    split: DatasetSplit
    competition: str
    season: str
    grid_index: int
    grid_label: str
    period: str
    minute: int
    row_digest: str
    values: dict[str, float | None]
    availabilities: dict[str, str]

    def value_of(self, feature_key: str) -> float | None:
        return self.values.get(feature_key)

    def availability_of(self, feature_key: str) -> str:
        return self.availabilities.get(feature_key, "")


@final
@dataclass(frozen=True, slots=True)
class _EixoResolvido:
    """Um eixo já casado com o artefato da competição — resolvido uma vez."""

    feature_key: str
    feature_fingerprint: str
    strategy: TransformStrategy
    artifact: NormalizerFitArtifact | None
    #: O motivo pronto para quando o artefato não produz número. `None` quando
    #: ele produz.
    unavailable_reason: NormalizationAvailability | None


@final
class RowNormalizer:
    """Aplica plano e artefatos a uma linha crua. Puro, e determinístico.

    ELE NÃO LÊ NADA E NÃO ESCREVE NADA. Recebe a linha, devolve a linha
    normalizada; a leitura é do adaptador e a escrita é do materializador. É o
    que torna a invariância de ordem e de lote demonstrável por teste de
    propriedade em vez de por execução completa.
    """

    __slots__ = ("_bridge", "_plan", "_por_competicao", "_representation", "_set")

    def __init__(
        self,
        *,
        plan: NormalizationPlan,
        artifact_set: NormalizerArtifactSet,
        representation: NormalizedFeatureRepresentationSpec,
        numeric_bridge: NumericBridge | None = None,
    ) -> None:
        if artifact_set.plan_fingerprint != plan.fingerprint:
            raise ValidationError(
                "o conjunto de artefatos foi ajustado sob outro plano: normalizar com "
                "ele produziria números perfeitamente plausíveis sob decisões que "
                "ninguém tomou para este dataset",
                context={
                    "plan": plan.fingerprint,
                    "artifact_set_plan": artifact_set.plan_fingerprint,
                },
            )
        if representation.artifact_set_fingerprint != artifact_set.fingerprint:
            raise ValidationError(
                "a representação declara um conjunto de artefatos diferente do que "
                "está sendo aplicado: a impressão gravada na linha não descreveria os "
                "números dela",
                context={
                    "representation": representation.artifact_set_fingerprint,
                    "artifact_set": artifact_set.fingerprint,
                },
            )
        self._plan = plan
        self._set = artifact_set
        self._representation = representation
        self._bridge = numeric_bridge or representation.numeric_bridge
        self._por_competicao: dict[str, tuple[tuple[_EixoResolvido, ...], str]] = {}

    # ------------------------------------------------------------ resolução --

    def _resolver(self, competition: str) -> tuple[tuple[_EixoResolvido, ...], str]:
        pronto = self._por_competicao.get(competition)
        if pronto is not None:
            return pronto
        pacote: CompetitionNormalizerArtifactBundle | None
        try:
            pacote = self._set.bundle_of(competition)
        except ValidationError:
            # SEM PACOTE NÃO É DEFEITO DE CHAMADA (§87). Uma competição que
            # aparece só na avaliação nunca teve população de referência, e as
            # linhas dela continuam existindo — com os eixos ROBUST vazios e o
            # motivo dizendo exatamente isso.
            pacote = None
        # SEM PACOTE NÃO HÁ ARTEFATO NENHUM, e o mapa vazio é o que faz todo
        # eixo `ROBUST` cair no motivo certo mais abaixo.
        por_chave = {a.feature_key: a for a in pacote.artifacts} if pacote else {}
        identidade_do_pacote = pacote.competition_id if pacote else None
        eixos: list[_EixoResolvido] = []
        for transformacao in self._plan.transforms:
            if transformacao.strategy is TransformStrategy.PASS_THROUGH:
                eixos.append(
                    _EixoResolvido(
                        feature_key=transformacao.feature_key,
                        feature_fingerprint=transformacao.feature_fingerprint,
                        strategy=transformacao.strategy,
                        artifact=None,
                        unavailable_reason=None,
                    )
                )
                continue
            artefato = por_chave.get(transformacao.feature_key)
            if artefato is None:
                eixos.append(
                    _EixoResolvido(
                        feature_key=transformacao.feature_key,
                        feature_fingerprint=transformacao.feature_fingerprint,
                        strategy=transformacao.strategy,
                        artifact=None,
                        unavailable_reason=(
                            NormalizationAvailability.ARTIFACT_NOT_AVAILABLE_FOR_COMPETITION
                        ),
                    )
                )
                continue
            # A COMPETIÇÃO CONFERIDA É A DO PACOTE, e nunca a do próprio
            # artefato: passar `artefato.competition_id` faria a metade da
            # conferência que mais importa (PR-05.4 §132) virar uma
            # tautologia — um artefato sempre se aplica a si mesmo.
            assert identidade_do_pacote is not None
            artefato.assert_applies_to(
                feature_fingerprint=transformacao.feature_fingerprint,
                competition_id=identidade_do_pacote,
            )
            eixos.append(
                _EixoResolvido(
                    feature_key=transformacao.feature_key,
                    feature_fingerprint=transformacao.feature_fingerprint,
                    strategy=transformacao.strategy,
                    artifact=artefato,
                    unavailable_reason=_MOTIVO_POR_ESTADO.get(artefato.status),
                )
            )
        pronto = (
            tuple(eixos),
            "" if pacote is None else pacote.fingerprint,
        )
        self._por_competicao[competition] = pronto
        return pronto

    # ---------------------------------------------------------- a aplicação --

    def normalize(self, view: RawFeatureRowView) -> NormalizedFeatureRow:
        """A linha normalizada. Sempre uma, e sempre com todos os eixos."""
        eixos, impressao_do_pacote = self._resolver(view.competition)
        celulas = tuple(self._celula(eixo, view) for eixo in eixos)
        return NormalizedFeatureRow(
            key=view.key,
            split=view.split,
            competition=view.competition,
            season=view.season,
            grid_index=view.grid_index,
            grid_label=view.grid_label,
            period=view.period,
            minute=view.minute,
            source_row_digest=view.row_digest,
            representation_fingerprint=self._representation.fingerprint,
            plan_fingerprint=self._plan.fingerprint,
            artifact_set_fingerprint=self._set.fingerprint,
            competition_bundle_fingerprint=impressao_do_pacote,
            cells=celulas,
        )

    def _celula(self, eixo: _EixoResolvido, view: RawFeatureRowView) -> NormalizedCell:
        estado_de_origem = view.availability_of(eixo.feature_key)
        bruto = view.value_of(eixo.feature_key)
        if estado_de_origem not in FITTABLE_SOURCE_STATES or bruto is None:
            return NormalizedCell.unavailable(
                feature_key=eixo.feature_key,
                availability=NormalizationAvailability.SOURCE_VALUE_UNAVAILABLE,
                source_availability=estado_de_origem,
            )
        if eixo.strategy is TransformStrategy.PASS_THROUGH:
            # §78 — o MESMO `float64`. Nenhuma conversão no caminho.
            return NormalizedCell.available(
                feature_key=eixo.feature_key,
                value=bruto,
                source_availability=estado_de_origem,
            )
        if eixo.unavailable_reason is not None or eixo.artifact is None:
            return NormalizedCell.unavailable(
                feature_key=eixo.feature_key,
                availability=(
                    eixo.unavailable_reason
                    or NormalizationAvailability.ARTIFACT_NOT_AVAILABLE_FOR_COMPETITION
                ),
                source_availability=estado_de_origem,
            )
        artefato = eixo.artifact
        if artefato.median is None or artefato.iqr is None:
            raise ValidationError(
                f"artefato FITTED de {eixo.feature_key} sem mediana ou IQR: ele "
                "afirma ter encontrado uma escala e não a carrega",
                context={"feature": eixo.feature_key},
            )
        entrada = self._bridge.input_bridge.to_decimal(bruto)
        escalado = ((entrada - artefato.median) / artefato.iqr).quantize(_QUANTUM)
        return NormalizedCell.available(
            feature_key=eixo.feature_key,
            value=self._bridge.output_encoding.to_float(escalado),
            source_availability=estado_de_origem,
        )


@final
@dataclass(slots=True)
class NormalizationTally:
    """As contagens acumuladas durante a construção — sem segunda passagem."""

    total_cells: int = 0
    by_state: dict[str, int] = field(default_factory=dict)
    by_source_state: dict[str, int] = field(default_factory=dict)

    def update(self, row: NormalizedFeatureRow) -> None:
        for celula in row.cells:
            self.total_cells += 1
            estado = celula.availability.value
            self.by_state[estado] = self.by_state.get(estado, 0) + 1
            origem = celula.source_availability
            self.by_source_state[origem] = self.by_source_state.get(origem, 0) + 1

    @property
    def artifact_unavailable(self) -> int:
        return sum(
            contagem for estado, contagem in self.by_state.items() if estado.startswith("ARTIFACT_")
        )
