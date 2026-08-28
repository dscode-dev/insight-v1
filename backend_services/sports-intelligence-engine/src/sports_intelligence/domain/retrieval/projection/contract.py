"""A identidade de uma projeção de recuperação — e o que ela NÃO cobre.

O PROJEÇÃO É UMA PROJEÇÃO DERIVADA (§18), e nunca a autoridade histórica. A
cadeia tem um sentido só:

    Normalized Historical Dataset          a autoridade
            |
            v
    Retrieval Index Projection             derivada, e verificável
            |
            v
    pgvector / HNSW                        física, e descartável

Se as duas divergirem, **o dataset normalizado ganha** — e a projeção é
reconstruído. Nada aqui pode ser lido como fonte primária.

A DISTINÇÃO QUE DÁ NOME AO MÓDULO: conteúdo SEMÂNTICO contra grafo FÍSICO
(§19, §57). O HNSW é um grafo construído com aleatoriedade e ordem de inserção;
reconstruí-lo produz páginas diferentes, arestas diferentes e um `pg_relation_size`
diferente. Isso NÃO significa que o conteúdo indexado mudou.

    entra na impressão        chave semântica, payload exato, linhagem, políticas
    NÃO entra na impressão    OID, layout de página, arestas do HNSW, carimbo
                              de construção, ordem de inserção

Sem essa separação, todo `REINDEX` pareceria uma mudança de conteúdo — e a
impressão deixaria de significar «o mesmo dado» para significar «a mesma
build», que é uma coisa muito menos útil.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError

PROJECTION_FINGERPRINT_ALGORITHM: Final[str] = "historical-retrieval-projection-sha256-v1"
PROJECTION_CONTENT_ALGORITHM: Final[str] = "historical-retrieval-projection-content-sha256-v1"


@final
class RetrievalProjectionKind(StrEnum):
    """Os dois projeçãos, e a separação é científica (§11, §12).

    UM PROJEÇÃO ÚNICO COM `[estado | trajetória]` SERIA MAIS BARATO E ESTARIA
    ERRADO. Estado mede NÍVEL e trajetória mede MOVIMENTO; concatená-los num
    vetor faria o L2 somar as duas grandezas e produzir uma ordem que não
    corresponde a nenhuma das duas perguntas — e a separação que o PR-06.3
    defendeu no domínio se perderia na infraestrutura.
    """

    STATE = "STATE"
    TRAJECTORY = "TRAJECTORY"


@final
class RetrievalProjectionStatus(StrEnum):
    """O ciclo de vida (§23). Só `READY` responde consulta.

    `VALIDATING` EXISTE SEPARADO DE `BUILDING` de propósito: construir é
    escrever linhas, validar é reconferir o que foi escrito contra a origem, e
    uma projeção que falhou na validação não é uma projeção incompleto — é uma projeção
    completo e errado, que é um estado pior e merece nome próprio.
    """

    DRAFT = "DRAFT"
    BUILDING = "BUILDING"
    VALIDATING = "VALIDATING"
    READY = "READY"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"

    @property
    def is_queryable(self) -> bool:
        """Só um. E a ausência de `VALIDATING` aqui é o ponto (§154)."""
        return self is RetrievalProjectionStatus.READY

    @property
    def is_terminal(self) -> bool:
        return self in (RetrievalProjectionStatus.FAILED, RetrievalProjectionStatus.SUPERSEDED)


@final
@dataclass(frozen=True, slots=True)
class RetrievalProjectionBinding:
    """A QUE este projeção está preso (§22). Toda divergência aqui é fail-closed.

    SÃO SETE AMARRAS, e nenhuma é decorativa. Cada uma responde a uma pergunta
    que, se ficasse sem resposta, permitiria uma consulta silenciosamente errada:

        dataset            o projeção é daquele conjunto, e não de outro
        referência         o ajuste é aquele — mudar a AVALIAÇÃO não conta
        plano              os eixos significam a mesma coisa
        artefatos          a escala é a mesma
        universo           quem é candidato não mudou
        payload            o rerank reconstrói o mesmo `float64`
        payload            o rerank reconstrói o mesmo `float64`
    """

    source_dataset_version_id: str
    source_dataset_version: str
    source_reference_fingerprint: str
    normalization_plan_fingerprint: str
    artifact_set_fingerprint: str
    candidate_policy_fingerprint: str
    exact_payload_encoding: str
    #: Só na trajetória: as TRÊS políticas do PR-06.3.
    #:
    #: A DE COBERTURA ENTRA JUNTO das outras duas porque ela decide QUEM é
    #: elegível: uma projeção construída sob um piso e consultada sob outro
    #: produziria um conjunto de vizinhos que nenhuma das duas políticas
    #: autoriza.
    trajectory_window_fingerprint: str = ""
    trajectory_profile_fingerprint: str = ""
    trajectory_coverage_fingerprint: str = ""

    def __post_init__(self) -> None:
        for rotulo, valor in (
            ("source_dataset_version_id", self.source_dataset_version_id),
            ("source_reference_fingerprint", self.source_reference_fingerprint),
            ("normalization_plan_fingerprint", self.normalization_plan_fingerprint),
            ("artifact_set_fingerprint", self.artifact_set_fingerprint),
            ("candidate_policy_fingerprint", self.candidate_policy_fingerprint),
        ):
            if not valor.strip():
                raise ValidationError(
                    f"amarra {rotulo} vazia: uma projeção sem ela aceitaria uma query de "
                    "outra origem sem ter como perceber"
                )

    def as_canonical(self) -> dict[str, object]:
        return {
            "artifact_set_fingerprint": self.artifact_set_fingerprint,
            "candidate_policy_fingerprint": self.candidate_policy_fingerprint,
            "exact_payload_encoding": self.exact_payload_encoding,
            "normalization_plan_fingerprint": self.normalization_plan_fingerprint,
            "source_dataset_version": self.source_dataset_version,
            "source_dataset_version_id": self.source_dataset_version_id,
            "source_reference_fingerprint": self.source_reference_fingerprint,
            "trajectory_coverage_fingerprint": self.trajectory_coverage_fingerprint,
            "trajectory_profile_fingerprint": self.trajectory_profile_fingerprint,
            "trajectory_window_fingerprint": self.trajectory_window_fingerprint,
        }


@final
@dataclass(frozen=True, slots=True)
class HistoricalRetrievalProjectionVersion:
    """Uma versão de projeção — semântica primeiro, física à parte.

    `content_fingerprint` É O QUE IMPORTA. Ele cobre as linhas indexadas, em
    ordem canônica, e é reconstruível a partir do dataset normalizado sozinho.
    Duas construções físicas do mesmo conteúdo têm o MESMO valor aqui e podem
    ter tamanhos de projeção diferentes — e as duas coisas estão certas.
    """

    #: O id DESTA versão — a chave que as linhas indexadas referenciam.
    #:
    #: ELE É SEPARADO DE `projection_id` porque são duas coisas: `projection_id` é o
    #: projeção lógico («o projeção de estado do dataset X»), e este é a build
    #: concreta. As linhas apontam para a build, e não para o nome — é o que
    #: permite duas versões coexistirem enquanto uma é construída e a outra
    #: continua servindo (§153).
    version_id: str
    projection_id: str
    kind: RetrievalProjectionKind
    name: str
    version: int
    binding: RetrievalProjectionBinding
    status: RetrievalProjectionStatus = RetrievalProjectionStatus.DRAFT
    axis_count: int = 0
    row_count: int = 0
    #: A impressão do CONTEÚDO indexado. Vazia enquanto não há conteúdo.
    content_fingerprint: str = ""
    #: Contagens por competição — diagnóstico, e fora da impressão.
    rows_by_competition: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.axis_count < 1:
            raise ValidationError("uma projeção sem eixos não reconstrói representação nenhuma")
        if self.kind is RetrievalProjectionKind.TRAJECTORY and not (
            self.binding.trajectory_window_fingerprint
            and self.binding.trajectory_profile_fingerprint
        ):
            raise ValidationError(
                "projeção de TRAJETÓRIA sem impressão de janela ou de perfil: sem elas "
                "uma projeção construído sob outros horizontes seria aceito por uma query "
                "que espera 1/3/5, e os deslocamentos mediriam outros intervalos"
            )
        if self.status.is_queryable and not self.content_fingerprint:
            raise ValidationError(
                "projeção READY sem impressão de conteúdo: publicá-lo assim tornaria a "
                "validação impossível de refazer"
            )

    @property
    def identity(self) -> str:
        return f"{self.name}@{self.version}/{self.kind.value}"

    @property
    def axis_keys(self) -> tuple[str, ...]:
        """Os eixos canônicos que ESTA projeção persistiu, em ordem.

        ELES VÊM DO PLANO, e não de uma coluna: o plano de normalização é
        determinístico e a projeção guarda a impressão dele, logo reconstruir a
        lista aqui é seguro — e a conferência de `axis_count` recusa qualquer
        divergência antes que uma posição seja lida errado.
        """
        from sports_intelligence.domain.features.normalized.plan import (
            normalization_plan_v1,
        )

        chaves = normalization_plan_v1().robust_keys
        if len(chaves) != self.axis_count:
            raise ValidationError(
                f"a projeção guardou {self.axis_count} eixos e o plano atual tem "
                f"{len(chaves)}: decodificar assim atribuiria números a eixos errados",
                context={"actual": len(chaves), "expected": self.axis_count},
            )
        return chaves

    @property
    def row_scope(self) -> str:
        """O id que as linhas indexadas carregam. Nome explícito de propósito.

        AS CONSULTAS FILTRAM POR ELE, SEMPRE. Uma que filtrasse por `projection_id`
        misturaria builds — e uma lista curta com linhas de duas versões teria
        vetores de proxies possivelmente diferentes na mesma ordenação.
        """
        return self.version_id

    @property
    def is_queryable(self) -> bool:
        return self.status.is_queryable

    def assert_queryable(self) -> None:
        """§24, §154 — só `READY` responde, e a recusa diz o estado real."""
        if not self.is_queryable:
            raise ProjectionNotReadyError(projection=self.identity, status=self.status)

    def assert_serves(
        self,
        *,
        dataset_version_id: str,
        plan_fingerprint: str,
        artifact_set_fingerprint: str,
        kind: RetrievalProjectionKind,
    ) -> None:
        """As amarras conferidas UMA a UMA, com o motivo dito (§25, §26).

        A ORDEM VAI DO MAIS GROSSO AO MAIS FINO — primeiro o tipo de projeção,
        depois a origem, por último a representação. Um erro de tipo reportado
        como «codificação divergente» mandaria quem lê procurar no lugar
        errado.
        """
        if kind is not self.kind:
            raise ProjectionKindMismatchError(expected=kind, actual=self.kind)
        if dataset_version_id != self.binding.source_dataset_version_id:
            raise ProjectionSourceMismatchError(
                projection=self.identity,
                expected=self.binding.source_dataset_version_id,
                actual=dataset_version_id,
                what="dataset normalizado",
            )
        if plan_fingerprint != self.binding.normalization_plan_fingerprint:
            raise ProjectionSourceMismatchError(
                projection=self.identity,
                expected=self.binding.normalization_plan_fingerprint,
                actual=plan_fingerprint,
                what="plano de normalização",
            )
        if artifact_set_fingerprint != self.binding.artifact_set_fingerprint:
            raise ProjectionSourceMismatchError(
                projection=self.identity,
                expected=self.binding.artifact_set_fingerprint,
                actual=artifact_set_fingerprint,
                what="conjunto de artefatos",
            )

    def as_canonical(self) -> dict[str, object]:
        """A identidade SEMÂNTICA. Sem uma palavra sobre o grafo físico (§57)."""
        return {
            # O `version_id` NÃO entra: ele é um uuid sorteado na criação, e
            # duas builds do mesmo conteúdo teriam impressões diferentes só por
            # causa dele — que é exatamente o que a impressão semântica não pode
            # depender (§19).
            "algorithm": PROJECTION_FINGERPRINT_ALGORITHM,
            "binding": self.binding.as_canonical(),
            "axis_count": self.axis_count,
            "content_fingerprint": self.content_fingerprint,
            "kind": self.kind.value,
            "name": self.name,
            "row_count": self.row_count,
            "version": self.version,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def diagnostics(self) -> Mapping[str, object]:
        return {
            "axis_count": self.axis_count,
            "content_fingerprint": self.content_fingerprint,
            "kind": self.kind.value,
            "row_count": self.row_count,
            "rows_by_competition": dict(self.rows_by_competition),
            "status": self.status.value,
        }

    def __str__(self) -> str:
        return (
            f"{self.identity} {self.status.value} · {self.row_count:_} linhas "
            f"x {self.axis_count} eixos [{self.fingerprint[:12]}]"
        )


# ============================================================ os erros ==


@final
class ProjectionNotReadyError(ValidationError):
    """§223 — e a recusa é TIPADA, e não uma queda silenciosa para o exato.

    O FALLBACK SILENCIOSO SERIA PIOR QUE O ERRO. Se uma projeção ausente fizesse a
    consulta cair no caminho exato sem dizer nada, a latência de produção
    passaria a depender de um estado invisível — e ninguém saberia distinguir
    «o projeção está saudável» de «o projeção sumiu e estamos pagando a varredura».
    """

    def __init__(self, *, projection: str, status: RetrievalProjectionStatus) -> None:
        super().__init__(
            f"PROJECTION_NOT_READY: a projeção {projection} está {status.value}, e só READY "
            "responde consulta. A alternativa — cair para o caminho exato em "
            "silêncio — esconderia a diferença entre uma projeção saudável e um ausente",
            context={
                "projection": projection,
                "reason": "PROJECTION_NOT_READY",
                "status": status.value,
            },
        )
        self.status = status


@final
class ProjectionKindMismatchError(ValidationError):
    """§204 — uma projeção de trajetória não responde pergunta de estado."""

    def __init__(
        self, *, expected: RetrievalProjectionKind, actual: RetrievalProjectionKind
    ) -> None:
        super().__init__(
            f"PROJECTION_KIND_MISMATCH: pedido {expected.value} e a projeção é {actual.value}. "
            "Os dois vetores têm dimensões e significados diferentes, e cruzá-los "
            "devolveria vizinhos calculados sobre outra grandeza",
            context={
                "actual": actual.value,
                "expected": expected.value,
                "reason": "PROJECTION_KIND_MISMATCH",
            },
        )


@final
class ProjectionSourceMismatchError(ValidationError):
    """§25, §26, §203, §205, §206 — a amarra que divergiu, nomeada."""

    def __init__(self, *, projection: str, expected: str, actual: str, what: str) -> None:
        super().__init__(
            f"PROJECTION_SOURCE_MISMATCH: a projeção {projection} foi construído sobre {what} "
            f"{expected[:16]} e a consulta traz {actual[:16]}. Responder assim daria "
            "vizinhos medidos numa escala que a query não usa",
            context={
                "actual": actual,
                "expected": expected,
                "projection": projection,
                "reason": "PROJECTION_SOURCE_MISMATCH",
                "what": what,
            },
        )
        self.what = what
