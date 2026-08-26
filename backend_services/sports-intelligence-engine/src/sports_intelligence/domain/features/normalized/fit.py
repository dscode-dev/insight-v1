"""O ajuste sobre a REFERÊNCIA — em fluxo, exato, e cego para a avaliação.

O QUE ESTE MÓDULO GARANTE, e é a razão do PR:

    FitPopulation ⊆ REFERENCE          por construção — a varredura recusa
                                       uma linha de AVALIAÇÃO
    ∂ArtifactSet/∂EVALUATION = 0       porque NADA que a avaliação toca entra
                                       na identidade de artefato nenhum

A SEGUNDA EXIGE CUIDADO EM TRÊS LUGARES, e errar em qualquer um deles a quebra
sem produzir número errado nenhum:

    source_corpus_fingerprint   é a impressão da REFERÊNCIA DAQUELA COMPETIÇÃO,
                                e não a impressão crua global. A crua cobre as
                                duas metades: usá-la faria uma partida
                                acrescentada à avaliação mudar todo artefato
    population_digest           é a impressão das observações de referência
                                daquela competição naquele eixo — e nenhuma
                                observação de avaliação entra nela
    fit_corpus_fingerprint      fica VAZIO no normalizador. Ele é global, e um
                                valor global faria a referência da La Liga
                                mudar os artefatos da Premier League

A LINHAGEM NÃO SE PERDE por isso. «Este ajuste veio de qual dataset cru?» é
respondida pelo `NormalizerArtifactSet.lineage()`, que carrega a impressão crua
global; «desta competição, o que entrou?» é respondida pelo
`source_corpus_fingerprint` do próprio artefato. As duas perguntas têm
respostas, em níveis diferentes — e a de baixo não enxerga a avaliação.

A ACUMULAÇÃO NÃO GUARDA OBJETOS. Vinte e nove eixos `ROBUST` sobre noventa e
uma mil linhas de referência são dois milhões e meio de observações; guardá-las
como `FeatureObservation` custaria centenas de megabytes para responder às
cinco perguntas do ajustador. O que fica na memória é um `array('d')` por eixo,
uma máscara de disponibilidade e um SHA-256 em andamento.

A EXATIDÃO NÃO É NEGOCIADA (PR-05.4 §183). Os quantis continuam sendo os de
tipo 7 sobre a população inteira, em `Decimal`. O que foi comprimido é o
ARMAZENAMENTO das observações, e não o método.
"""

from __future__ import annotations

import hashlib
from array import array
from collections.abc import Iterator, Mapping
from decimal import Decimal
from typing import Final, final

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.definitions import FeatureDefinition
from sports_intelligence.domain.features.fitting.artifact import NormalizerFitArtifact
from sports_intelligence.domain.features.fitting.fitter import RobustNormalizerFitter
from sports_intelligence.domain.features.normalization import NormalizerDefinition
from sports_intelligence.domain.features.normalized.artifacts import (
    CompetitionNormalizerArtifactBundle,
    ReferenceContentAccumulator,
    ReferenceContentIdentity,
)
from sports_intelligence.domain.features.normalized.bridge import (
    FloatToDecimalBridge,
    float64_bytes,
)
from sports_intelligence.domain.features.normalized.ordering import (
    PartitionKey,
    PartitionOrderGuard,
    partition_of,
)
from sports_intelligence.domain.features.normalized.plan import NormalizationPlan
from sports_intelligence.domain.features.normalized.rows import (
    FITTABLE_SOURCE_STATES,
)
from sports_intelligence.domain.features.normalized.transform import RawFeatureRowView
from sports_intelligence.domain.shared.canonical import canonical_json, frame
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import CompetitionId

#: O algoritmo da impressão da população de escala de dataset. `ORDERED` no
#: nome porque a ordem é parte do método — ver o porquê no corpo da classe.
DATASET_POPULATION_DIGEST_ALGORITHM: Final[str] = "dataset-fit-population-sha256-ordered-v1"

_TAG_CABECALHO: Final[bytes] = b"sie.fitpop.head"
_TAG_OBSERVACAO: Final[bytes] = b"sie.fitpop.obs"


@final
class DatasetFeaturePopulation:
    """As observações de UM eixo em UMA competição — acumuladas em fluxo.

    ELA É ORDENADA E EXIGE ORDEM, e a diferença para `FeaturePopulation` do
    PR-05.4 é deliberada. Aquela ORDENA o que recebe, porque recebe um conjunto
    já materializado e a ordem de leitura do banco não pode decidir a
    identidade. Esta RECUSA o que chega fora de ordem, porque recebe um fluxo
    cuja ordem já é canônica — e reordenar um fluxo exigiria materializá-lo.

    A ORDEM CANÔNICA É A DE PARTIÇÃO (ordering.py), e não a da chave: as
    partidas são identificadas por `uuid5`, então as chaves de duas competições
    se intercalam no espaço de identificadores.

    A RECUSA É MAIS FORTE QUE A ORDENAÇÃO, e não mais fraca: a mesma observação
    duas vezes chega como `key <= última` e é recusada (PR-05.4 §107), e uma
    varredura fora de ordem — que é defeito do leitor — para em vez de produzir
    uma impressão que ninguém consegue reproduzir.
    """

    __slots__ = (
        "_ausentes",
        "_competition_id",
        "_feature_key",
        "_guarda",
        "_hash",
        "_ponte",
        "_total",
        "_valores",
    )

    def __init__(
        self,
        *,
        competition_id: CompetitionId,
        feature_key: str,
        feature_fingerprint: str,
        bridge: FloatToDecimalBridge,
    ) -> None:
        self._competition_id = competition_id
        self._feature_key = feature_key
        self._ponte = bridge
        self._hash = hashlib.sha256(
            frame(
                _TAG_CABECALHO,
                canonical_json(
                    {
                        "algorithm": DATASET_POPULATION_DIGEST_ALGORITHM,
                        "bridge": bridge.value,
                        "competition_id": str(competition_id),
                        "feature_fingerprint": feature_fingerprint,
                        "feature_key": feature_key,
                        "split": DatasetSplit.REFERENCE.value,
                    }
                ),
            )
        )
        # `array('d')` E NÃO `list[float]`: oito bytes por valor contra vinte e
        # quatro mais o ponteiro. Em dois milhões e meio de observações a
        # diferença é a que decide se o ajuste cabe na memória.
        self._valores = array("d")
        self._ausentes = 0
        self._total = 0
        self._guarda = PartitionOrderGuard(rotulo=f"população de {feature_key}@{competition_id}")

    def observe(
        self,
        key: HistoricalFeatureSnapshotKey,
        *,
        partition: PartitionKey,
        value: float | None,
        source_availability: str,
    ) -> None:
        """UMA observação. `None` conta e não entra na distribuição (§119)."""
        self._guarda.check(partition, key)
        disponivel = value is not None and source_availability in FITTABLE_SOURCE_STATES
        corpo = key.text.encode() + b"="
        if disponivel:
            assert value is not None
            self._valores.append(value)
            # OS BYTES IEEE-754, e não o texto do `Decimal`. A conversão para
            # `Decimal` é exata e serve para a CONTA; fazê-la dois milhões e
            # meio de vezes só para produzir texto de hash pagaria o custo do
            # ajuste inteiro de novo, e o número que identifica a observação é
            # o mesmo dos dois lados.
            corpo += float64_bytes(value)
        else:
            self._ausentes += 1
            corpo += b"\x00" + source_availability.encode()
        self._hash.update(frame(_TAG_OBSERVACAO, corpo))
        self._total += 1

    # ------------------------------------------- a superfície do ajustador --

    @property
    def competition_id(self) -> CompetitionId:
        return self._competition_id

    @property
    def feature_key(self) -> str:
        return self._feature_key

    @property
    def size(self) -> int:
        """O total, INCLUINDO as indisponíveis (PR-05.4 §120)."""
        return self._total

    @property
    def available_size(self) -> int:
        return len(self._valores)

    @property
    def digest(self) -> str:
        if not self._total:
            return ""
        copia = self._hash.copy()
        copia.update(frame(b"sie.fitpop.count", f"{self._total}:{self._ausentes}".encode()))
        return copia.hexdigest()

    def values(self) -> list[Decimal]:
        """Os valores DISPONÍVEIS em `Decimal`, materializados AGORA.

        UM EIXO POR VEZ. Os noventa e um mil `Decimal` de um eixo cabem
        confortavelmente; os de vinte e nove eixos ao mesmo tempo não caberiam,
        e é por isso que o que fica guardado são os oito bytes do `float64`.
        """
        return [self._ponte.to_decimal(v) for v in self._valores]

    def __str__(self) -> str:
        return f"{self._feature_key}@{self._competition_id}: {self.available_size}/{self._total}"


@final
class ReferenceFitScan:
    """A varredura única que alimenta o ajuste e a identidade da referência.

    UMA PASSAGEM, E NÃO DUAS. A impressão da referência e as populações saem da
    mesma leitura porque são a mesma leitura: separá-las leria o dataset duas
    vezes para responder perguntas que a mesma linha responde.

    ELA RECUSA UMA LINHA DE AVALIAÇÃO em vez de ignorá-la. Ignorar em silêncio
    faria um leitor mal configurado — um que esquecesse o filtro de partição —
    produzir um conjunto de artefatos perfeitamente plausível sobre a população
    errada, e nada no resultado diria isso.
    """

    __slots__ = ("_bridge", "_conteudo", "_linhas", "_plan", "_populacoes", "_por_codigo")

    def __init__(
        self,
        *,
        plan: NormalizationPlan,
        split_fingerprint: str,
        competitions: Mapping[str, CompetitionId],
    ) -> None:
        self._plan = plan
        self._bridge = plan.input_bridge
        self._conteudo = ReferenceContentAccumulator(
            space_fingerprint=plan.space_fingerprint,
            split_fingerprint=split_fingerprint,
        )
        self._por_codigo = dict(competitions)
        self._populacoes: dict[str, dict[str, DatasetFeaturePopulation]] = {}
        self._linhas = 0

    def observe(self, view: RawFeatureRowView) -> None:
        if view.split is not DatasetSplit.REFERENCE:
            raise ValidationError(
                f"linha de {view.split.value} entregue ao ajuste em {view.key}: o "
                "ajuste é somente sobre REFERÊNCIA, e aceitar a linha faria a escala "
                "carregar o futuro que ela deveria avaliar (PR-05.2, ADR-0039)",
                context={"key": view.key.text, "split": view.split.value},
            )
        self._conteudo.update(
            view.key,
            view.row_digest,
            competition=view.competition,
            season=view.season,
        )
        particao = partition_of(
            split=view.split.value, competition=view.competition, season=view.season
        )
        eixos = self._eixos_de(view.competition)
        for chave, populacao in eixos.items():
            populacao.observe(
                view.key,
                partition=particao,
                value=view.value_of(chave),
                source_availability=view.availability_of(chave),
            )
        self._linhas += 1

    def _eixos_de(self, competition: str) -> dict[str, DatasetFeaturePopulation]:
        pronto = self._populacoes.get(competition)
        if pronto is not None:
            return pronto
        identidade = self._por_codigo.get(competition)
        if identidade is None:
            raise ValidationError(
                f"a competição {competition!r} do dataset cru não tem identidade "
                "declarada no escopo do corpus: ajustar sem ela produziria artefatos "
                "que não se sabe a qual liga pertencem, e um artefato de liga "
                "desconhecida normaliza qualquer uma (PR-05.4 §132)",
                context={"competition": competition},
            )
        pronto = {
            transformacao.feature_key: DatasetFeaturePopulation(
                competition_id=identidade,
                feature_key=transformacao.feature_key,
                feature_fingerprint=transformacao.feature_fingerprint,
                bridge=self._bridge,
            )
            for transformacao in self._plan.transforms
            if transformacao.strategy.requires_artifact
        }
        self._populacoes[competition] = pronto
        return pronto

    # ------------------------------------------------------------ leitura --

    @property
    def rows(self) -> int:
        return self._linhas

    @property
    def competitions(self) -> tuple[str, ...]:
        return tuple(sorted(self._populacoes))

    def reference_identity(self) -> ReferenceContentIdentity:
        return self._conteudo.finalize()

    def populations_of(self, competition: str) -> Iterator[DatasetFeaturePopulation]:
        """As populações daquela competição, em ordem canônica do plano."""
        eixos = self._populacoes.get(competition, {})
        for transformacao in self._plan.transforms:
            populacao = eixos.get(transformacao.feature_key)
            if populacao is not None:
                yield populacao


def fit_bundles(
    scan: ReferenceFitScan,
    *,
    normalizer: NormalizerDefinition,
    plan: NormalizationPlan,
    definitions: Mapping[str, FeatureDefinition],
    reference: ReferenceContentIdentity,
) -> tuple[CompetitionNormalizerArtifactBundle, ...]:
    """Um pacote por competição, ajustado só com o que é da competição.

    O `source_corpus_fingerprint` DE CADA ARTEFATO É A IMPRESSÃO DA REFERÊNCIA
    DAQUELA COMPETIÇÃO. Essa escolha faz duas coisas ao mesmo tempo: tira a
    avaliação da identidade do artefato, e tira as OUTRAS competições dela — a
    referência da La Liga não aparece em lugar nenhum do que a Premier League
    afirma.
    """
    fitter = RobustNormalizerFitter(definition=normalizer)
    fitter.assert_causal_for_live_comparable()
    pacotes: list[CompetitionNormalizerArtifactBundle] = []
    for competicao in scan.competitions:
        impressao = reference.of(competicao)
        artefatos: list[NormalizerFitArtifact] = []
        identidade: CompetitionId | None = None
        for populacao in scan.populations_of(competicao):
            definicao = definitions.get(populacao.feature_key)
            if definicao is None:
                raise ValidationError(
                    f"o eixo {populacao.feature_key} está no plano e não no catálogo "
                    "de definições: ajustar sem a definição gravaria um artefato sem "
                    "a impressão da feature que ele normaliza",
                    context={"feature": populacao.feature_key},
                )
            identidade = populacao.competition_id
            artefatos.append(
                fitter.fit(
                    populacao,
                    feature=definicao,
                    source_corpus_fingerprint=impressao,
                    source_space_fingerprint=plan.space_fingerprint,
                )
            )
        if identidade is None:
            continue
        pacotes.append(
            CompetitionNormalizerArtifactBundle.of(
                competition=competicao,
                competition_id=identidade,
                reference_fingerprint=impressao,
                plan_fingerprint=plan.fingerprint,
                artifacts=artefatos,
            )
        )
    return tuple(pacotes)
