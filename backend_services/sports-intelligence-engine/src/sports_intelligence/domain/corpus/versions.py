"""O dataset histórico e suas versões — identidade lógica contra conteúdo.

DUAS COISAS, E JUNTÁ-LAS APAGA A MAIS ÚTIL (§6, §7):

    HistoricalCanonicalDataset          «o corpus histórico principal»
                                        um nome estável, que dura anos

    HistoricalCanonicalDatasetVersion   «o que exatamente estava nele em 1.0»
                                        um conteúdo imutável, que nunca muda

Com uma entidade só, «o corpus» seria um alvo móvel: cada reprocessamento
mudaria o que a v1.0 significa, e nenhum resultado calculado sobre ela seria
reproduzível. Com duas, o nome continua sendo um ponteiro e a versão continua
sendo um fato.

UMA VERSÃO NÃO É UMA EXECUÇÃO DE BUILD (§8). Um `CanonicalBuildRun` constrói
fatos; uma versão DECLARA quais fatos formam o corpus. Uma versão pode ser
composta por vários builds:

    BuildRun Premier League 2023/24
    BuildRun Premier League 2024/25   →   HistoricalCanonicalDatasetVersion 1.0
    BuildRun La Liga      2024/25

DEPOIS DE `READY`, NADA MUDA (§10). Nem ganha partida, nem perde, nem troca
política, nem recalcula impressão. Qualquer mudança produz uma versão NOVA — e
a anterior continua consultável, marcada como superada.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final, Self, final

from sports_intelligence.domain.corpus.scope import CorpusScope
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.resolution.versions import PolicyVersion
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.errors import ConflictError, ValidationError
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion

#: O ator de serviço da publicação. Nomeado pelo que ele É (PR-04.2 §75).
CORPUS_PUBLISHER: Final[str] = "historical-corpus-publisher"

#: O nome de dataset que o motor usa por padrão. Nomeado porque ele aparece em
#: caminho de object store e em manifesto — um literal espalhado divergiria.
DEFAULT_DATASET_NAME: Final[str] = "historical-core"


class DatasetVersionStatus(StrEnum):
    """Onde uma versão do corpus está. Fechado, e nunca um booleano.

    `published = true` PARECE BASTAR E NÃO BASTA (§11). Ele não distingue «foi
    construída e está sendo conferida» de «falhou na materialização» de «foi
    substituída por uma versão nova» — e as três exigem ações diferentes de
    quem opera. Pior: um booleano não tem como recusar a transição que este
    PR existe para recusar, que é publicar sem ter conferido.
    """

    #: Declarada, sem conteúdo. Só o escopo e os inputs pretendidos.
    DRAFT = "DRAFT"
    #: Materializando: membership sendo gravada, objetos sendo escritos.
    BUILDING = "BUILDING"
    #: Conteúdo pronto, conferindo — contagens, impressão, linhagem.
    VALIDATING = "VALIDATING"
    #: Conferida e imutável. É esta que o PR-05 pode ler.
    READY = "READY"
    #: Falhou em qualquer etapa. NÃO é `READY` com ressalva (§53).
    FAILED = "FAILED"
    #: Uma versão mais nova a substituiu. Continua consultável (§79).
    SUPERSEDED = "SUPERSEDED"

    @property
    def is_terminal(self) -> bool:
        return self in (
            DatasetVersionStatus.READY,
            DatasetVersionStatus.FAILED,
            DatasetVersionStatus.SUPERSEDED,
        )

    @property
    def is_readable_corpus(self) -> bool:
        """Se o PR-05 pode consumir esta versão.

        `SUPERSEDED` PODE. Ela continua sendo um corpus válido e imutável — o
        que mudou é que existe uma mais nova. Impedir a leitura tornaria
        irreprodutível todo resultado já calculado sobre ela, que é o oposto
        do motivo de as versões existirem.
        """
        return self in (DatasetVersionStatus.READY, DatasetVersionStatus.SUPERSEDED)

    @property
    def is_frozen(self) -> bool:
        """Se a composição desta versão já não pode mudar (§115)."""
        return self in (DatasetVersionStatus.READY, DatasetVersionStatus.SUPERSEDED)


#: O grafo, escrito por extenso — como o `RunStatus` do PR-03. Regra derivada
#: permitiria uma aresta nova aparecer sem ninguém decidi-la, e a aresta que
#: mais importa é justamente a que NÃO existe: `DRAFT → READY` (§12).
_TRANSICOES: Final[dict[DatasetVersionStatus, frozenset[DatasetVersionStatus]]] = {
    DatasetVersionStatus.DRAFT: frozenset(
        {DatasetVersionStatus.BUILDING, DatasetVersionStatus.FAILED}
    ),
    DatasetVersionStatus.BUILDING: frozenset(
        {DatasetVersionStatus.VALIDATING, DatasetVersionStatus.FAILED}
    ),
    DatasetVersionStatus.VALIDATING: frozenset(
        {DatasetVersionStatus.READY, DatasetVersionStatus.FAILED}
    ),
    DatasetVersionStatus.READY: frozenset({DatasetVersionStatus.SUPERSEDED}),
    DatasetVersionStatus.FAILED: frozenset(),
    DatasetVersionStatus.SUPERSEDED: frozenset(),
}


def can_transition(current: DatasetVersionStatus, target: DatasetVersionStatus) -> bool:
    return target in _TRANSICOES[current]


@final
@dataclass(frozen=True, slots=True)
class HistoricalCanonicalDataset:
    """A identidade LÓGICA do corpus. Não tem conteúdo.

    ELE NÃO CARREGA ESCOPO NEM CONTAGEM, e a ausência é o ponto: escopo e
    conteúdo pertencem à VERSÃO. Um dataset que soubesse quais competições
    contém teria de mudar quando a v1.1 acrescentasse uma — e aí ele deixaria
    de ser identidade estável.
    """

    id: str
    name: str
    created_at: Instant
    created_by: Actor
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("dataset histórico sem nome")
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
        return f"dataset histórico {self.name}"


@final
@dataclass(frozen=True, slots=True)
class VersionInputs:
    """As execuções que compõem uma versão, com as impressões delas.

    OS IDS E AS IMPRESSÕES, e não só os ids (§20, §140). O id diz QUAL
    execução; a impressão diz O QUE ela produziu. Uma versão que guardasse só
    ids seria reproduzível apenas enquanto as execuções existissem — e o que
    se quer provar é o conteúdo, não a existência da linha.
    """

    build_run_ids: tuple[str, ...]
    quality_run_ids: tuple[str, ...]
    #: Impressões da SAÍDA de cada build, ordenadas. Elas entram na impressão
    #: semântica do corpus; os ids não (§31).
    build_output_fingerprints: tuple[ContentHash, ...] = ()
    quality_policy_versions: tuple[PolicyVersion, ...] = ()
    quality_policy_fingerprints: tuple[ContentHash, ...] = ()
    build_policy_versions: tuple[PolicyVersion, ...] = ()
    build_policy_fingerprints: tuple[ContentHash, ...] = ()
    #: A linhagem para trás: fusões e resoluções que alimentaram os builds.
    fusion_run_ids: tuple[str, ...] = ()
    resolution_run_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.build_run_ids:
            raise ValidationError(
                "versão de corpus sem execução de construção: ela seria composta por quais fatos?"
            )
        for nome, valores in (
            ("build_run_ids", self.build_run_ids),
            ("quality_run_ids", self.quality_run_ids),
        ):
            if len(set(valores)) != len(valores):
                raise ValidationError(
                    f"{nome} com repetição — os fatos entrariam em dobro nas contagens"
                )

    def as_canonical(self) -> dict[str, object]:
        """A forma completa, para o manifesto — COM os ids (traversal)."""
        return {
            "build_output_fingerprints": sorted(f.value for f in self.build_output_fingerprints),
            "build_policy_fingerprints": sorted(f.value for f in self.build_policy_fingerprints),
            "build_policy_versions": sorted(str(v) for v in self.build_policy_versions),
            "build_run_ids": sorted(self.build_run_ids),
            "fusion_run_ids": sorted(self.fusion_run_ids),
            "quality_policy_fingerprints": sorted(
                f.value for f in self.quality_policy_fingerprints
            ),
            "quality_policy_versions": sorted(str(v) for v in self.quality_policy_versions),
            "quality_run_ids": sorted(self.quality_run_ids),
            "resolution_run_ids": sorted(self.resolution_run_ids),
        }

    def semantic_form(self) -> dict[str, object]:
        """O que entra na IMPRESSÃO — sem os identificadores de execução (§31).

        DUAS PUBLICAÇÕES INDEPENDENTES DOS MESMOS FATOS têm ids diferentes e
        são o mesmo corpus. Incluir os ids faria a impressão dizer «diferente»
        sobre conteúdo idêntico, e ela deixaria de servir para o §89.

        AS IMPRESSÕES FICAM, e são elas que carregam a semântica: se a saída
        de um build mudou, a impressão dele mudou, e a do corpus muda junto.
        """
        return {
            "build_output_fingerprints": sorted(f.value for f in self.build_output_fingerprints),
            "build_policy_fingerprints": sorted(f.value for f in self.build_policy_fingerprints),
            "build_policy_versions": sorted(str(v) for v in self.build_policy_versions),
            "quality_policy_fingerprints": sorted(
                f.value for f in self.quality_policy_fingerprints
            ),
            "quality_policy_versions": sorted(str(v) for v in self.quality_policy_versions),
        }


@final
@dataclass(frozen=True, slots=True)
class HistoricalCanonicalDatasetVersion:
    """Uma versão do corpus. Imutável a partir de `READY`."""

    id: str
    dataset_id: str
    version: DatasetVersion
    scope: CorpusScope
    inputs: VersionInputs
    status: DatasetVersionStatus
    created_at: Instant
    created_by: Actor
    #: A impressão SEMÂNTICA do corpus. `None` até a materialização terminar —
    #: uma versão em `DRAFT` não tem conteúdo para imprimir.
    corpus_fingerprint: ContentHash | None = None
    manifest_id: str | None = None
    #: Quantas partidas a versão contém. Contadas, nunca estimadas (§67).
    match_count: int = 0
    completed_at: Instant | None = None
    failure_reason: str | None = None
    #: A versão que substituiu esta, quando houver (§79).
    superseded_by: str | None = None

    def __post_init__(self) -> None:
        if self.status is DatasetVersionStatus.READY:
            if self.corpus_fingerprint is None:
                raise ValidationError(
                    f"versão {self.version} em READY sem impressão do corpus — ela "
                    "afirmaria estar publicada sem nada que prove o que publicou"
                )
            if self.manifest_id is None:
                raise ValidationError(
                    f"versão {self.version} em READY sem manifesto: o corpus não "
                    "teria descrição nenhuma do que contém (§12)"
                )
        if self.status is DatasetVersionStatus.FAILED and not (self.failure_reason or "").strip():
            raise ValidationError("versão FAILED sem motivo")
        if (
            self.status is DatasetVersionStatus.SUPERSEDED
            and not (self.superseded_by or "").strip()
        ):
            raise ValidationError(
                "versão SUPERSEDED sem dizer por qual — «foi substituída» sem o "
                "sucessor não permite achar o corpus atual"
            )
        if self.status.is_terminal and self.completed_at is None:
            raise ValidationError(f"versão em {self.status} sem instante de conclusão")

    @classmethod
    def draft(
        cls,
        *,
        dataset_id: str,
        version: DatasetVersion,
        scope: CorpusScope,
        inputs: VersionInputs,
        at: Instant,
        created_by: Actor,
    ) -> Self:
        return cls(
            id=str(uuid.uuid4()),
            dataset_id=dataset_id,
            version=version,
            scope=scope,
            inputs=inputs,
            status=DatasetVersionStatus.DRAFT,
            created_at=at,
            created_by=created_by,
        )

    # ------------------------------------------------------- transições --

    def start_building(self) -> Self:
        self._assert_pode_ir_para(DatasetVersionStatus.BUILDING)
        return replace(self, status=DatasetVersionStatus.BUILDING)

    def start_validating(self, *, match_count: int, corpus_fingerprint: ContentHash) -> Self:
        """A materialização terminou; agora se confere o que ela produziu.

        A IMPRESSÃO ENTRA AQUI E NÃO EM `READY`, e a ordem importa: `READY`
        precisa poder COMPARAR o que foi materializado com o que o manifesto
        diz, e para comparar é preciso já ter os dois lados.
        """
        self._assert_pode_ir_para(DatasetVersionStatus.VALIDATING)
        if match_count < 0:
            raise ValidationError(f"contagem negativa de partidas: {match_count}")
        return replace(
            self,
            status=DatasetVersionStatus.VALIDATING,
            match_count=match_count,
            corpus_fingerprint=corpus_fingerprint,
        )

    def publish(self, *, manifest_id: str, at: Instant) -> Self:
        """`READY`. A partir daqui a composição é congelada (§10, §115).

        NÃO ACEITA VIR DE `DRAFT` (§12). A ausência da aresta é o gate: uma
        versão que nunca materializou nem conferiu não pode se declarar
        publicada, e o grafo é onde essa recusa mora.
        """
        self._assert_pode_ir_para(DatasetVersionStatus.READY)
        if not manifest_id.strip():
            raise ValidationError("publicação sem manifesto")
        return replace(
            self,
            status=DatasetVersionStatus.READY,
            manifest_id=manifest_id,
            completed_at=at,
        )

    def fail(self, *, reason: str, at: Instant) -> Self:
        self._assert_pode_ir_para(DatasetVersionStatus.FAILED)
        return replace(
            self,
            status=DatasetVersionStatus.FAILED,
            failure_reason=reason[:500],
            completed_at=at,
        )

    def supersede(self, *, by_version_id: str, at: Instant) -> Self:
        """Marca como substituída. O conteúdo continua lá (§79).

        NÃO APAGA NADA. Um resultado calculado sobre a v1.0 continua
        explicável pela v1.0 — e seria irreproduzível se ela sumisse.
        """
        self._assert_pode_ir_para(DatasetVersionStatus.SUPERSEDED)
        if not by_version_id.strip():
            raise ValidationError("supersessão sem a versão sucessora")
        if by_version_id == self.id:
            raise ValidationError("uma versão não pode substituir a si mesma")
        return replace(
            self,
            status=DatasetVersionStatus.SUPERSEDED,
            superseded_by=by_version_id,
            completed_at=at,
        )

    def _assert_pode_ir_para(self, target: DatasetVersionStatus) -> None:
        if not can_transition(self.status, target):
            raise ConflictError(
                f"transição {self.status} → {target} não existe no ciclo de vida do "
                "corpus. Uma versão publicada é imutável; mudança de composição "
                "produz uma versão NOVA (ADR-0026)",
                context={"version_id": self.id, "status": self.status.value},
            )

    # ---------------------------------------------------------- leitura --

    @property
    def usage(self) -> UsageScope:
        return self.scope.usage

    @property
    def is_frozen(self) -> bool:
        return self.status.is_frozen

    def assert_mutable(self) -> None:
        """Recusa alterar a composição de uma versão congelada (§115)."""
        if self.is_frozen:
            raise ConflictError(
                f"a versão {self.version} está em {self.status} e sua composição é "
                "imutável — acrescentar ou remover um fato agora faria um corpus já "
                "publicado mudar de conteúdo sem mudar de nome (§10)",
                context={"version_id": self.id},
            )

    def __str__(self) -> str:
        return f"corpus {self.version} [{self.status}] {self.scope.usage}"


def assert_not_vector_active(version: HistoricalCanonicalDatasetVersion) -> None:
    """A guarda do limite DESTA fase. Recusa sempre (§4).

        HISTORICAL_CANONICAL_READY  ≠  HISTORICAL_VECTOR_ACTIVE

    Um corpus pronto é um corpus que o PR-05 pode LER. Ele não tem feature, não
    tem `MatchStateVector`, não tem vetor em lugar nenhum — e a distância entre
    uma coisa e outra é o PR-05 inteiro.

    Existe para ser chamada por qualquer caminho futuro que trate uma versão
    publicada como espaço vetorial ativo.
    """
    from sports_intelligence.domain.shared.errors import InvariantViolationError

    raise InvariantViolationError(
        f"a versão {version.version} do corpus está pronta para ser LIDA, e não é um "
        "espaço vetorial ativo. Faltam o espaço de features, o MatchStateVector e a "
        "indexação — que são o PR-05 (ADR-0007, ADR-0026).",
        context={"version_id": version.id, "status": version.status.value},
    )
