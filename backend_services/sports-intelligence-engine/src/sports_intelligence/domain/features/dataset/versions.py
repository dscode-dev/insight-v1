"""A identidade e o ciclo de vida do dataset histórico de features.

DUAS COISAS, E SEPARÁ-LAS É A DECISÃO (o mesmo desenho do corpus, ADR-0026):

    HistoricalFeatureDataset          a identidade LÓGICA. Não tem conteúdo,
                                      não tem escopo, não tem contagem
    HistoricalFeatureDatasetVersion   o conteúdo congelado. Escopo, políticas,
                                      contagens e impressão moram aqui

Um dataset que soubesse quantas linhas contém teria de mudar quando a v1.1
acrescentasse partidas — e deixaria de ser identidade estável.

O CICLO DE VIDA É O MESMO DO CORPUS, E ISSO É REUSO E NÃO COINCIDÊNCIA. As
perguntas são as mesmas — «está sendo escrito?», «já foi conferido?», «pode ser
lido?» —, e um segundo grafo de transições com os mesmos nomes divergiria do
primeiro na primeira correção feita num só dos dois.

    DRAFT → BUILDING → VALIDATING → READY → SUPERSEDED
      ↓        ↓            ↓
    FAILED   FAILED       FAILED

`DRAFT → READY` NÃO EXISTE, e a ausência é o ponto: um dataset publicado sem
passar por construção e validação seria um nome apontando para nada.

A VERSÃO CARREGA AS POLÍTICAS PELA IMPRESSÃO, E NÃO PELO OBJETO. Duas versões
construídas sob grades diferentes NÃO são comparáveis, e a impressão é o que
permite descobrir isso sem reconstruir política nenhuma seis meses depois.

A VERSÃO APONTA PARA A VERSÃO DO CORPUS, e não para o dataset canônico. «As
features da 1.0» é uma afirmação verificável; «as features do corpus» mudaria
de significado toda vez que o corpus publicasse uma versão nova.
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
from sports_intelligence.domain.features.dataset.grid import SnapshotGridPolicy
from sports_intelligence.domain.features.dataset.split import (
    FeatureDatasetSplitPolicy,
    SplitCounts,
)
from sports_intelligence.domain.features.space import FeatureSpaceDefinition
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion

#: O nome do dataset de produção. Ele é o prefixo no object store e a chave nas
#: consultas administrativas, e por isso não tem barra nem espaço.
DEFAULT_FEATURE_DATASET_NAME: Final[str] = "match-state-raw"

#: Quem publica. O mesmo papel do corpus, com sujeito próprio: publicar corpus
#: e publicar features são autorizações diferentes.
FEATURE_DATASET_PUBLISHER: Final[str] = "feature-dataset-publisher"


@final
@dataclass(frozen=True, slots=True)
class FeatureDatasetSpec:
    """As decisões sob as quais uma versão foi construída — POR EXTENSO.

    ELA CARREGA AS POLÍTICAS INTEIRAS, e não só as impressões delas. A forma
    anterior guardava `(nome, versão, impressão)` de cada uma, e parecia
    suficiente: a impressão prova identidade, e o nome permite reconstruir.

    NÃO PERMITE. `SnapshotGridPolicy(name=…, version=…)` traz os limites
    PADRÃO — uma grade de cinco cortes voltaria com noventa e um, e a
    conferência de impressão acusaria sem conseguir consertar. Uma política com
    parâmetros só é reconstrutível a partir dos parâmetros.

    A IMPRESSÃO CONTINUA SENDO O CONTRATO DE COMPARABILIDADE. Duas versões com
    o mesmo `spec` são comparáveis linha a linha; duas com specs diferentes não
    são, mesmo contendo as mesmas partidas.
    """

    space_name: str
    space_version: str
    space_fingerprint: str
    grid: SnapshotGridPolicy
    split: FeatureDatasetSplitPolicy

    def __post_init__(self) -> None:
        if len(self.space_fingerprint) != 64:
            raise ValidationError(
                f"space_fingerprint com {len(self.space_fingerprint)} caracteres: uma "
                "impressão de SHA-256 tem 64, e um valor truncado passaria a comparar "
                "prefixos"
            )

    @classmethod
    def of(
        cls,
        *,
        space: FeatureSpaceDefinition,
        grid: SnapshotGridPolicy,
        split: FeatureDatasetSplitPolicy,
    ) -> Self:
        return cls(
            space_name=space.name,
            space_version=str(space.version),
            space_fingerprint=space.fingerprint,
            grid=grid,
            split=split,
        )

    # ------------------------------------------------------- as impressões --

    @property
    def grid_name(self) -> str:
        return self.grid.name

    @property
    def grid_version(self) -> int:
        return self.grid.version

    @property
    def grid_fingerprint(self) -> str:
        return self.grid.fingerprint

    @property
    def split_name(self) -> str:
        return self.split.name

    @property
    def split_version(self) -> int:
        return self.split.version

    @property
    def split_fingerprint(self) -> str:
        return self.split.fingerprint

    @property
    def reference_end_exclusive(self) -> Instant:
        return self.split.reference_end_exclusive

    # ------------------------------------------------------------- a forma --

    def as_canonical(self) -> dict[str, object]:
        """A forma completa — com os PARÂMETROS e as impressões.

        A IMPRESSÃO DE CADA POLÍTICA ENTRA NO DOCUMENTO junto dos parâmetros,
        ainda que seja derivada deles. Ela é o que se compara sem reconstruir
        objeto nenhum, e tirá-la obrigaria quem lê o manifesto a recalcular um
        hash para responder «é a mesma grade?».
        """
        return {
            "grid": {**self.grid.as_canonical(), "fingerprint": self.grid.fingerprint},
            "space": {
                "fingerprint": self.space_fingerprint,
                "name": self.space_name,
                "version": self.space_version,
            },
            "split": {
                **self.split.as_canonical(),
                "fingerprint": self.split.fingerprint,
            },
        }

    @classmethod
    def from_canonical(cls, forma: Mapping[str, Any]) -> Self:
        """A especificação de volta, com as políticas inteiras.

        AS IMPRESSÕES GRAVADAS SÃO CONFERIDAS contra as recalculadas. Se um
        documento trouxesse parâmetros adulterados, a impressão dele não fecharia
        — e reconstruir em silêncio produziria uma política que ninguém declarou.
        """
        grade = SnapshotGridPolicy.from_canonical(forma["grid"])
        divisao = FeatureDatasetSplitPolicy.from_canonical(forma["split"])
        _conferir(forma["grid"], grade.fingerprint, "grade")
        _conferir(forma["split"], divisao.fingerprint, "divisão")
        espaco = forma["space"]
        return cls(
            space_name=str(espaco["name"]),
            space_version=str(espaco["version"]),
            space_fingerprint=str(espaco["fingerprint"]),
            grid=grade,
            split=divisao,
        )

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def is_comparable_with(self, other: FeatureDatasetSpec) -> bool:
        """Se duas versões podem ser comparadas linha a linha."""
        return self.fingerprint == other.fingerprint

    def __str__(self) -> str:
        return f"{self.space_name}@{self.space_version}/{self.grid.name}"


def _conferir(forma: Mapping[str, Any], recalculada: str, rotulo: str) -> None:
    gravada = forma.get("fingerprint")
    if gravada is not None and str(gravada) != recalculada:
        raise ValidationError(
            f"a {rotulo} reconstruída tem impressão diferente da gravada: os "
            "parâmetros do documento não são os que produziram aquela impressão",
            context={"stored": str(gravada), "rebuilt": recalculada},
        )


@final
@dataclass(frozen=True, slots=True)
class HistoricalFeatureDataset:
    """A identidade lógica. Sem conteúdo, sem escopo, sem contagem."""

    id: str
    name: str
    created_at: Instant
    created_by: Actor
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("dataset de features sem nome")
        if "/" in self.name or " " in self.name:
            raise ValidationError(
                f"nome de dataset {self.name!r} inválido: ele vira caminho no object "
                "store e chave de manifesto, então barra e espaço estão fora"
            )

    @classmethod
    def create(
        cls,
        *,
        name: str,
        at: Instant,
        created_by: Actor,
        description: str | None = None,
    ) -> Self:
        return cls(
            id=str(uuid.uuid4()),
            name=name.strip(),
            created_at=at,
            created_by=created_by,
            description=description,
        )

    def __str__(self) -> str:
        return f"dataset de features {self.name}"


@final
@dataclass(frozen=True, slots=True)
class HistoricalFeatureDatasetVersion:
    """Uma versão do dataset de features. Imutável a partir de `READY`."""

    id: str
    dataset_id: str
    version: DatasetVersion
    #: A VERSÃO DO CORPUS que a alimentou, com a impressão dela. Sem a
    #: impressão, «veio da 1.0» não é verificável.
    source_version_id: str
    source_version: DatasetVersion
    source_corpus_fingerprint: ContentHash
    spec: FeatureDatasetSpec
    status: DatasetVersionStatus
    created_at: Instant
    created_by: Actor
    #: A impressão do conteúdo CRU materializado. `None` até a construção
    #: terminar — uma versão em `DRAFT` não tem conteúdo para imprimir.
    raw_content_fingerprint: ContentHash | None = None
    manifest_id: str | None = None
    match_count: int = 0
    row_count: int = 0
    counts: SplitCounts = field(default_factory=SplitCounts)
    completed_at: Instant | None = None
    failure_reason: str | None = None
    superseded_by: str | None = None

    def __post_init__(self) -> None:
        if self.status is DatasetVersionStatus.READY:
            if self.raw_content_fingerprint is None:
                raise ValidationError(
                    f"versão de features {self.version} em READY sem impressão de "
                    "conteúdo — ela afirmaria estar publicada sem nada que prove o "
                    "que publicou"
                )
            if self.manifest_id is None:
                raise ValidationError(
                    f"versão de features {self.version} em READY sem manifesto: o "
                    "dataset não teria descrição nenhuma do que contém"
                )
            if self.row_count <= 0:
                raise ValidationError(
                    f"versão de features {self.version} publicada com {self.row_count} "
                    "linhas: um dataset vazio publicado é um nome apontando para nada, "
                    "e quem o consultasse receberia «sem vizinhos» em vez de um erro"
                )
        if self.status is DatasetVersionStatus.FAILED and not (self.failure_reason or "").strip():
            raise ValidationError("versão de features FAILED sem motivo")
        if (
            self.status is DatasetVersionStatus.SUPERSEDED
            and not (self.superseded_by or "").strip()
        ):
            raise ValidationError(
                "versão de features SUPERSEDED sem dizer por qual — «foi substituída» "
                "sem o sucessor não permite achar o dataset atual"
            )
        if self.status.is_terminal and self.completed_at is None:
            raise ValidationError(f"versão de features em {self.status} sem conclusão")
        if self.counts.rows and self.counts.rows != self.row_count:
            raise ValidationError(
                f"contagem por metade soma {self.counts.rows} e a versão declara "
                f"{self.row_count}: uma das duas está errada, e publicar as duas juntas "
                "faria o manifesto se contradizer"
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
        source_corpus_fingerprint: ContentHash,
        spec: FeatureDatasetSpec,
        at: Instant,
        created_by: Actor,
    ) -> Self:
        return cls(
            id=str(uuid.uuid4()),
            dataset_id=dataset_id,
            version=version,
            source_version_id=source_version_id,
            source_version=source_version,
            source_corpus_fingerprint=source_corpus_fingerprint,
            spec=spec,
            status=DatasetVersionStatus.DRAFT,
            created_at=at,
            created_by=created_by,
        )

    # ------------------------------------------------------------ leitura --

    @property
    def is_readable(self) -> bool:
        """Se esta versão pode alimentar ajuste, comparação ou avaliação."""
        return self.status.is_readable_corpus

    @property
    def rows_per_match(self) -> float:
        """A média. Ela é DIAGNÓSTICO, e não contrato: uma partida com
        prorrogação contribui 121 linhas, e a média deixa de ser inteira."""
        return 0.0 if not self.match_count else self.row_count / self.match_count

    def can_move_to(self, target: DatasetVersionStatus) -> bool:
        return can_transition(self.status, target)

    def require_transition(self, target: DatasetVersionStatus) -> None:
        if not self.can_move_to(target):
            raise ValidationError(
                f"a versão de features {self.version} está em {self.status} e não pode "
                f"ir para {target}: o grafo de transições é explícito justamente para "
                "que «publicar sem validar» não seja alcançável por engano",
                context={"from": self.status.value, "to": target.value},
            )

    def as_canonical(self) -> dict[str, object]:
        """A forma que entra no manifesto (COM ids) — ver `semantic_form`."""
        forma = dict(self.semantic_form())
        forma["source_version_id"] = self.source_version_id
        forma["version"] = str(self.version)
        return forma

    def semantic_form(self) -> dict[str, object]:
        """O que entra na IMPRESSÃO — sem id de execução nem carimbo.

        DUAS CONSTRUÇÕES INDEPENDENTES DO MESMO CONTEÚDO têm ids diferentes e
        são o mesmo dataset. Incluir os ids faria a impressão dizer «diferente»
        sobre conteúdo idêntico.
        """
        return {
            "counts": self.counts.as_canonical(),
            "match_count": self.match_count,
            "row_count": self.row_count,
            "source_corpus_fingerprint": self.source_corpus_fingerprint.value,
            "source_version": str(self.source_version),
            "spec": self.spec.as_canonical(),
        }

    def __str__(self) -> str:
        return f"features {self.version} ({self.status}, {self.row_count} linhas)"


@final
@dataclass(frozen=True, slots=True)
class FeatureDatasetBuildRun:
    """Uma execução de construção. Ela é o rastro, e não o conteúdo.

    O CONTEÚDO É DA VERSÃO; a execução diz QUANDO e POR QUEM, e quanto custou.
    Duas execuções sobre a mesma versão — a segunda depois de uma falha — são
    dois rastros e um conteúdo.
    """

    id: str
    version_id: str
    started_at: Instant
    started_by: Actor
    status: DatasetVersionStatus = DatasetVersionStatus.BUILDING
    finished_at: Instant | None = None
    matches_processed: int = 0
    rows_written: int = 0
    objects_written: int = 0
    bytes_written: int = 0
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
        return f"build de features {self.id[:8]} ({self.status})"
