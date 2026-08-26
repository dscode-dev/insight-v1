"""A identidade e o ciclo de vida do dataset NORMALIZADO.

ELE É UMA PROJEÇÃO INDEPENDENTE, e não um campo a mais na versão crua (§53). A
tentação é gravar `normalized_content_fingerprint` em
`HistoricalFeatureDatasetVersion` e pronto — mas isso faria o dataset cru mudar
de identidade quando o AJUSTE mudasse, e o cru não tem nada a ver com ajuste. Um
mesmo dataset cru alimenta N representações normalizadas: refinar o plano, ou
reajustar sobre uma referência estendida, produz uma representação nova sobre
exatamente as mesmas linhas cruas.

    HistoricalFeatureDatasetVersion       os números como foram extraídos
        └── NormalizedFeatureDatasetVersion (plano P, artefatos A)
        └── NormalizedFeatureDatasetVersion (plano P, artefatos A')

A REPRESENTAÇÃO TEM IDENTIDADE PRÓPRIA — `NormalizedFeatureRepresentationSpec`
— e ela amarra QUATRO coisas (§58):

    espaço de features    quais eixos, em que ordem
    plano                 qual eixo recebe qual transformação
    conjunto de artefatos quais medianas e IQRs
    codificação de saída  como o `Decimal` escalado virou `float64`

TROCAR QUALQUER UMA DAS QUATRO TORNA OS NÚMEROS INCOMPARÁVEIS, e é por isso que
as quatro entram na mesma impressão. Comparar uma distância calculada sob os
artefatos A com outra sob A' é comparar centímetros com polegadas: os dois
números existem, os dois são plausíveis, e a comparação é falsa. A impressão é o
que faz essa pergunta ser respondível sem arqueologia.

O CICLO DE VIDA É O MESMO DO CORPUS E DO DATASET CRU, pelo terceiro motivo
idêntico: as perguntas são as mesmas, e um quarto grafo com os mesmos nomes
divergiria dos outros três na primeira correção feita num só.

    DRAFT → BUILDING → VALIDATING → READY → SUPERSEDED

A VERSÃO GRAVA AS TRÊS IMPRESSÕES DE CONTEÚDO, e não só a global. A do meio —
`normalized_reference_content_fingerprint` — é a que permite AFIRMAR, olhando
duas versões publicadas, que a base de comparação não mudou entre elas. Sem ela
sobra a global, que muda quando a avaliação cresce, e a afirmação vira opinião.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Self, final

from sports_intelligence.domain.corpus.versions import (
    DatasetVersionStatus,
    can_transition,
)
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.features.dataset.split import SplitCounts
from sports_intelligence.domain.features.normalized.bridge import NumericBridge
from sports_intelligence.domain.features.normalized.plan import NormalizationPlan
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion

#: O nome do dataset normalizado de produção. Ele é irmão de
#: `match-state-raw`, e o sufixo diz qual das duas representações é.
DEFAULT_NORMALIZED_DATASET_NAME: Final[str] = "match-state-normalized"

#: Quem publica. Papel próprio: publicar a representação normalizada é uma
#: autorização diferente de publicar as features cruas — a normalizada é a que
#: a busca por similaridade vai consumir.
NORMALIZED_DATASET_PUBLISHER: Final[str] = "normalized-dataset-publisher"

#: O algoritmo da identidade da representação.
REPRESENTATION_FINGERPRINT_ALGORITHM: Final[str] = "normalized-representation-sha256-v1"


@final
@dataclass(frozen=True, slots=True)
class NormalizedFeatureRepresentationSpec:
    """As quatro decisões que tornam dois números comparáveis — ou não.

    ELA GUARDA IMPRESSÕES, E NÃO OS OBJETOS. É o oposto da escolha feita em
    `FeatureDatasetSpec`, e a diferença tem motivo: a grade e a divisão são
    políticas com PARÂMETROS que precisam ser reconstruídos (uma grade de cinco
    cortes tem de voltar com cinco cortes). O conjunto de artefatos não é uma
    política — é um CONTEÚDO de milhares de números, persistido em tabela
    própria, e embuti-lo aqui duplicaria o banco dentro do manifesto.

    O PLANO VIAJA COM NOME E VERSÃO ALÉM DA IMPRESSÃO, porque ele é
    reconstrutível a partir do catálogo: `normalization_plan_v1()` produz o
    mesmo plano de novo, e a impressão confere se produziu.
    """

    space_name: str
    space_version: str
    space_fingerprint: str
    plan_name: str
    plan_version: str
    plan_fingerprint: str
    artifact_set_id: str
    artifact_set_fingerprint: str
    numeric_bridge: NumericBridge = field(default_factory=NumericBridge)

    def __post_init__(self) -> None:
        for rotulo, valor in (
            ("space_fingerprint", self.space_fingerprint),
            ("plan_fingerprint", self.plan_fingerprint),
            ("artifact_set_fingerprint", self.artifact_set_fingerprint),
        ):
            if len(valor) != 64:
                raise ValidationError(
                    f"{rotulo} com {len(valor)} caracteres: uma impressão de SHA-256 "
                    "tem 64, e um valor truncado passaria a comparar prefixos",
                    context={"field": rotulo, "value": valor},
                )
        if not self.artifact_set_id.strip():
            raise ValidationError(
                "representação sem id de conjunto de artefatos: a impressão diz «são "
                "os mesmos números», e o id diz ONDE eles estão — sem ele, normalizar "
                "uma linha nova exigiria procurar o conjunto por hash"
            )

    @classmethod
    def of(
        cls,
        *,
        plan: NormalizationPlan,
        artifact_set_id: str,
        artifact_set_fingerprint: str,
        numeric_bridge: NumericBridge | None = None,
    ) -> Self:
        return cls(
            space_name=plan.space_name,
            space_version=plan.space_version,
            space_fingerprint=plan.space_fingerprint,
            plan_name=plan.name,
            plan_version=plan.version,
            plan_fingerprint=plan.fingerprint,
            artifact_set_id=artifact_set_id,
            artifact_set_fingerprint=artifact_set_fingerprint,
            numeric_bridge=numeric_bridge or NumericBridge(),
        )

    # ------------------------------------------------------------- a forma --

    def as_canonical(self) -> dict[str, object]:
        """A identidade da representação — SEM o id do conjunto (§59).

        O ID NÃO ENTRA, e a impressão dele entra. Dois ajustes independentes que
        chegam aos mesmos artefatos sobre a mesma referência produzem a mesma
        representação com ids diferentes; incluir o id faria a impressão dizer
        «incomparável» sobre números idênticos.
        """
        return {
            "algorithm": REPRESENTATION_FINGERPRINT_ALGORITHM,
            "artifact_set_fingerprint": self.artifact_set_fingerprint,
            "numeric_bridge": self.numeric_bridge.as_canonical(),
            "plan": {
                "fingerprint": self.plan_fingerprint,
                "name": self.plan_name,
                "version": self.plan_version,
            },
            "space": {
                "fingerprint": self.space_fingerprint,
                "name": self.space_name,
                "version": self.space_version,
            },
        }

    def as_document(self) -> dict[str, object]:
        """A forma PERSISTIDA — a identidade mais a linhagem (o id)."""
        return {**self.as_canonical(), "artifact_set_id": self.artifact_set_id}

    @classmethod
    def from_canonical(cls, forma: Mapping[str, Any]) -> Self:
        plano = forma["plan"]
        espaco = forma["space"]
        return cls(
            space_name=str(espaco["name"]),
            space_version=str(espaco["version"]),
            space_fingerprint=str(espaco["fingerprint"]),
            plan_name=str(plano["name"]),
            plan_version=str(plano["version"]),
            plan_fingerprint=str(plano["fingerprint"]),
            artifact_set_id=str(forma.get("artifact_set_id", "")),
            artifact_set_fingerprint=str(forma["artifact_set_fingerprint"]),
            numeric_bridge=NumericBridge(),
        )

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def is_comparable_with(self, other: NormalizedFeatureRepresentationSpec) -> bool:
        """Se duas linhas normalizadas podem ser comparadas número a número."""
        return self.fingerprint == other.fingerprint

    def assert_comparable_with(self, other: NormalizedFeatureRepresentationSpec) -> None:
        if self.is_comparable_with(other):
            return
        divergencias = [
            rotulo
            for rotulo, esquerda, direita in (
                ("espaço", self.space_fingerprint, other.space_fingerprint),
                ("plano", self.plan_fingerprint, other.plan_fingerprint),
                (
                    "artefatos",
                    self.artifact_set_fingerprint,
                    other.artifact_set_fingerprint,
                ),
            )
            if esquerda != direita
        ]
        raise ValidationError(
            "representações incomparáveis: divergem em "
            f"{divergencias or ['codificação numérica']}. Comparar números destas duas "
            "produziria uma distância plausível e sem significado",
            context={"left": self.fingerprint, "right": other.fingerprint},
        )

    def __str__(self) -> str:
        return f"{self.plan_name}@{self.plan_version}/{self.artifact_set_fingerprint[:12]}"


@final
@dataclass(frozen=True, slots=True)
class NormalizedHistoricalFeatureDataset:
    """A identidade lógica da representação normalizada. Sem conteúdo.

    ELA APONTA PARA O DATASET CRU, e não para uma versão dele. «O normalizado do
    match-state-raw» continua verdadeiro quando o cru publica a 1.1; é a VERSÃO
    normalizada que aponta para a VERSÃO crua.
    """

    id: str
    name: str
    source_dataset_id: str
    created_at: Instant
    created_by: Actor
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("dataset normalizado sem nome")
        if "/" in self.name or " " in self.name:
            raise ValidationError(
                f"nome de dataset normalizado {self.name!r} inválido: ele vira caminho "
                "no object store e chave de manifesto, então barra e espaço estão fora"
            )
        if not self.source_dataset_id.strip():
            raise ValidationError(
                "dataset normalizado sem dataset de origem: uma representação sem o "
                "que ela representa não é verificável contra nada"
            )

    @classmethod
    def create(
        cls,
        *,
        name: str,
        source_dataset_id: str,
        at: Instant,
        created_by: Actor,
        description: str | None = None,
    ) -> Self:
        return cls(
            id=str(uuid.uuid4()),
            name=name.strip(),
            source_dataset_id=source_dataset_id,
            created_at=at,
            created_by=created_by,
            description=description,
        )

    def __str__(self) -> str:
        return f"dataset normalizado {self.name}"


@final
@dataclass(frozen=True, slots=True)
class NormalizedHistoricalFeatureDatasetVersion:
    """Uma versão normalizada. Imutável a partir de `READY`.

    ELA CARREGA A CONTAGEM CRUA ao lado da própria (§94). O contrato 1:1 é
    verificável exatamente porque os dois números estão no mesmo registro: uma
    versão normalizada com menos linhas do que a crua está afirmando, no próprio
    corpo, que alguma linha desapareceu — e desaparecer é a forma silenciosa de
    apagar uma partida inteira do conjunto de comparação.
    """

    id: str
    dataset_id: str
    version: DatasetVersion
    #: A VERSÃO CRUA de origem, com a impressão dela. «Veio da 1.0» só é
    #: verificável com a impressão junto.
    source_version_id: str
    source_version: DatasetVersion
    source_raw_content_fingerprint: ContentHash
    #: Quantas linhas a versão crua declarava. O outro lado do contrato 1:1.
    source_row_count: int
    representation: NormalizedFeatureRepresentationSpec
    status: DatasetVersionStatus
    created_at: Instant
    created_by: Actor
    #: AS TRÊS IMPRESSÕES. `None` até a construção terminar.
    normalized_content_fingerprint: ContentHash | None = None
    normalized_reference_content_fingerprint: ContentHash | None = None
    normalized_evaluation_content_fingerprint: ContentHash | None = None
    manifest_id: str | None = None
    match_count: int = 0
    row_count: int = 0
    counts: SplitCounts = field(default_factory=SplitCounts)
    completed_at: Instant | None = None
    failure_reason: str | None = None
    superseded_by: str | None = None

    def __post_init__(self) -> None:
        if self.source_row_count < 0:
            raise ValidationError("contagem crua negativa")
        if self.status is DatasetVersionStatus.READY:
            self._exigir_publicavel()
        if self.status is DatasetVersionStatus.FAILED and not (self.failure_reason or "").strip():
            raise ValidationError("versão normalizada FAILED sem motivo")
        if (
            self.status is DatasetVersionStatus.SUPERSEDED
            and not (self.superseded_by or "").strip()
        ):
            raise ValidationError(
                "versão normalizada SUPERSEDED sem dizer por qual — «foi substituída» "
                "sem o sucessor não permite achar a representação atual"
            )
        if self.status.is_terminal and self.completed_at is None:
            raise ValidationError(f"versão normalizada em {self.status} sem conclusão")
        if self.counts.rows and self.counts.rows != self.row_count:
            raise ValidationError(
                f"contagem por metade soma {self.counts.rows} e a versão declara "
                f"{self.row_count}: uma das duas está errada, e publicar as duas juntas "
                "faria o manifesto se contradizer"
            )

    def _exigir_publicavel(self) -> None:
        if self.normalized_content_fingerprint is None:
            raise ValidationError(
                f"versão normalizada {self.version} em READY sem impressão de "
                "conteúdo — ela afirmaria estar publicada sem nada que prove o que "
                "publicou"
            )
        if self.normalized_reference_content_fingerprint is None:
            raise ValidationError(
                f"versão normalizada {self.version} em READY sem impressão de "
                "REFERÊNCIA: sem ela, «a base de comparação não mudou» deixa de ser "
                "uma afirmação verificável e vira uma opinião sobre a impressão global"
            )
        if self.manifest_id is None:
            raise ValidationError(
                f"versão normalizada {self.version} em READY sem manifesto: o dataset "
                "não teria descrição nenhuma do que contém"
            )
        if self.row_count <= 0:
            raise ValidationError(
                f"versão normalizada {self.version} publicada com {self.row_count} "
                "linhas: um dataset vazio publicado é um nome apontando para nada"
            )
        if self.source_row_count and self.row_count != self.source_row_count:
            raise ValidationError(
                f"versão normalizada {self.version} com {self.row_count} linhas contra "
                f"{self.source_row_count} do dataset cru: a normalização não filtra. "
                "Uma linha a menos é uma partida silenciosamente fora do conjunto de "
                "comparação, e não um dataset «mais limpo»",
                context={
                    "normalized": self.row_count,
                    "raw": self.source_row_count,
                },
            )

    # -------------------------------------------------------- construtores --

    @classmethod
    def draft(
        cls,
        *,
        dataset_id: str,
        version: DatasetVersion,
        source_version_id: str,
        source_version: DatasetVersion,
        source_raw_content_fingerprint: ContentHash,
        source_row_count: int,
        representation: NormalizedFeatureRepresentationSpec,
        at: Instant,
        created_by: Actor,
    ) -> Self:
        return cls(
            id=str(uuid.uuid4()),
            dataset_id=dataset_id,
            version=version,
            source_version_id=source_version_id,
            source_version=source_version,
            source_raw_content_fingerprint=source_raw_content_fingerprint,
            source_row_count=source_row_count,
            representation=representation,
            status=DatasetVersionStatus.DRAFT,
            created_at=at,
            created_by=created_by,
        )

    # ------------------------------------------------------------ leitura --

    @property
    def is_readable(self) -> bool:
        return self.status.is_readable_corpus

    @property
    def artifact_set_fingerprint(self) -> str:
        return self.representation.artifact_set_fingerprint

    @property
    def plan_fingerprint(self) -> str:
        return self.representation.plan_fingerprint

    @property
    def representation_fingerprint(self) -> str:
        return self.representation.fingerprint

    def has_same_reference_as(self, other: NormalizedHistoricalFeatureDatasetVersion) -> bool:
        """A pergunta central do PR, respondida em uma linha (§152).

        DUAS VERSÕES COM A MESMA IMPRESSÃO DE REFERÊNCIA foram normalizadas sob
        a mesma base estatística e sobre as mesmas linhas de referência — ainda
        que a avaliação de uma tenha o dobro de partidas da outra.
        """
        minha = self.normalized_reference_content_fingerprint
        dela = other.normalized_reference_content_fingerprint
        return (
            minha is not None
            and dela is not None
            and minha.value == dela.value
            and self.artifact_set_fingerprint == other.artifact_set_fingerprint
        )

    def can_move_to(self, target: DatasetVersionStatus) -> bool:
        return can_transition(self.status, target)

    def require_transition(self, target: DatasetVersionStatus) -> None:
        if not self.can_move_to(target):
            raise ValidationError(
                f"a versão normalizada {self.version} está em {self.status} e não pode "
                f"ir para {target}: o grafo de transições é explícito justamente para "
                "que «publicar sem validar» não seja alcançável por engano",
                context={"from": self.status.value, "to": target.value},
            )

    # -------------------------------------------------------------- forma --

    def as_canonical(self) -> dict[str, object]:
        """A forma que entra no manifesto (COM ids) — ver `semantic_form`."""
        forma = dict(self.semantic_form())
        forma["source_version_id"] = self.source_version_id
        forma["version"] = str(self.version)
        return forma

    def semantic_form(self) -> dict[str, object]:
        """O que entra na impressão — sem id de execução nem carimbo."""
        return {
            "counts": self.counts.as_canonical(),
            "match_count": self.match_count,
            "representation": self.representation.as_canonical(),
            "row_count": self.row_count,
            "source_raw_content_fingerprint": self.source_raw_content_fingerprint.value,
            "source_row_count": self.source_row_count,
            "source_version": str(self.source_version),
        }

    def __str__(self) -> str:
        return f"normalizado {self.version} ({self.status}, {self.row_count} linhas)"


@final
@dataclass(frozen=True, slots=True)
class NormalizedFeatureDatasetBuildRun:
    """Uma execução de construção normalizada. O rastro, e não o conteúdo."""

    id: str
    version_id: str
    started_at: Instant
    started_by: Actor
    status: DatasetVersionStatus = DatasetVersionStatus.BUILDING
    finished_at: Instant | None = None
    rows_read: int = 0
    rows_written: int = 0
    objects_written: int = 0
    bytes_written: int = 0
    #: Quantas células saíram indisponíveis por causa do ARTEFATO — e não da
    #: origem. Ela é a métrica de saúde do AJUSTE: um salto aqui entre duas
    #: execuções diz que uma competição perdeu escala, e não que a coleta caiu.
    artifact_unavailable_cells: int = 0
    failure_reason: str | None = None

    @classmethod
    def start(cls, *, version_id: str, at: Instant, started_by: Actor) -> Self:
        return cls(
            id=str(uuid.uuid4()),
            version_id=version_id,
            started_at=at,
            started_by=started_by,
        )

    def __str__(self) -> str:
        return f"build normalizado {self.id[:8]} ({self.status})"
