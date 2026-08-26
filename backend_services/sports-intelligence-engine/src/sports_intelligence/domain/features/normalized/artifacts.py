"""O conjunto de artefatos — e a identidade que NÃO enxerga a avaliação.

A PROPRIEDADE QUE ESTE MÓDULO EXISTE PARA GARANTIR é uma só, e ela é a razão de
o PR inteiro existir:

    mudar QUALQUER coisa que pertence exclusivamente à AVALIAÇÃO
    não pode mudar NADA na base estatística usada para comparar

A forma executável disso é uma decisão sobre IDENTIDADE. O dataset cru tem uma
impressão de conteúdo — `raw_content_fingerprint` — e ela cobre as duas
metades. Se o conjunto de artefatos dependesse dela, acrescentar uma partida à
avaliação mudaria a impressão do conjunto, e portanto os artefatos «seriam
outros» sem que nenhum número tivesse mudado.

    raw_content_fingerprint          REFERÊNCIA + AVALIAÇÃO   ← NÃO entra
    reference_content_fingerprint    só REFERÊNCIA            ← entra

E O MESMO RACIOCÍNIO DESCE UM NÍVEL. A normalização é POR COMPETIÇÃO, então
mexer na La Liga não pode mexer no que a Premier League afirma. Por isso existe
também a identidade por competição, e o pacote de cada uma depende só dela.

    competition_reference_content_fingerprint(C)   só REFERÊNCIA, só C

O QUE FICA DE FORA DA IDENTIDADE SEMÂNTICA, e é deliberado:

    id da versão crua        duas publicações do mesmo conteúdo têm ids
                             diferentes e são o mesmo ajuste
    id da execução           idem
    instante de criação      idem
    chave de objeto          idem
    impressão CRUA global    contém a avaliação — é o defeito central

Todos eles continuam PERSISTIDOS, como LINHAGEM. A distinção é o ponto: linhagem
responde «de onde veio»; identidade responde «é o mesmo ajuste».
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Self, final

from sports_intelligence.domain.corpus.versions import (
    DatasetVersionStatus,
    can_transition,
)
from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.fitting.artifact import (
    FitStatus,
    NormalizerFitArtifact,
)
from sports_intelligence.domain.features.normalized.ordering import (
    PartitionOrderGuard,
    partition_of,
)
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.canonical import (
    canonical_json,
    frame,
    instant_text,
)
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import CompetitionId
from sports_intelligence.domain.shared.temporal import Instant

#: O algoritmo da identidade da população de referência. `ORDERED` no nome pelo
#: mesmo motivo do dataset cru: a ordem é parte do método.
REFERENCE_FINGERPRINT_ALGORITHM: Final[str] = "reference-content-sha256-ordered-v1"

#: O algoritmo do conjunto de artefatos.
ARTIFACT_SET_FINGERPRINT_ALGORITHM: Final[str] = "normalizer-artifact-set-sha256-v1"

#: O algoritmo do pacote por competição.
BUNDLE_FINGERPRINT_ALGORITHM: Final[str] = "competition-artifact-bundle-sha256-v1"

_TAG_LINHA: Final[bytes] = b"sie.reference.row"
_TAG_CABECALHO: Final[bytes] = b"sie.reference.head"


@final
class ReferenceContentAccumulator:
    """A impressão da população de REFERÊNCIA, em fluxo e em ordem.

    ELA É CALCULADA DURANTE A VARREDURA DO AJUSTE, e não numa passagem extra: o
    ajuste já lê exatamente as linhas de referência, então a identidade delas
    sai de graça.

    A ORDEM É EXIGIDA, e é a ordem CANÔNICA DE PARTIÇÃO (ordering.py): as
    partições em ordem de `(metade, competição, temporada)`, e as chaves em
    ordem dentro de cada uma. Uma impressão comutativa aceitaria duas linhas
    trocadas e diria «igual» — e permutação é um dos defeitos que ela existe
    para pegar.
    """

    __slots__ = ("_global", "_guarda", "_linhas", "_por_competicao")

    def __init__(self, *, space_fingerprint: str, split_fingerprint: str) -> None:
        cabecalho = frame(
            _TAG_CABECALHO,
            canonical_json(
                {
                    "algorithm": REFERENCE_FINGERPRINT_ALGORITHM,
                    "space_fingerprint": space_fingerprint,
                    "split": "REFERENCE",
                    "split_fingerprint": split_fingerprint,
                }
            ),
        )
        self._global = hashlib.sha256(cabecalho)
        self._por_competicao: dict[str, Any] = {}
        self._guarda = PartitionOrderGuard(rotulo="população de referência")
        self._linhas = 0

    def update(
        self,
        key: HistoricalFeatureSnapshotKey,
        digest: str,
        *,
        competition: str,
        season: str,
    ) -> None:
        self._guarda.check(
            partition_of(
                split=DatasetSplit.REFERENCE.value,
                competition=competition,
                season=season,
            ),
            key,
        )
        bloco = frame(_TAG_LINHA, f"{key.text}:{digest}".encode())
        self._global.update(bloco)
        acumulador = self._por_competicao.get(competition)
        if acumulador is None:
            acumulador = hashlib.sha256(
                frame(_TAG_CABECALHO, canonical_json({"competition": competition}))
            )
            self._por_competicao[competition] = acumulador
        acumulador.update(bloco)
        self._linhas += 1

    @property
    def rows(self) -> int:
        return self._linhas

    def finalize(self) -> ReferenceContentIdentity:
        global_hash = self._global.copy()
        global_hash.update(frame(b"sie.reference.count", str(self._linhas).encode()))
        por_competicao = {
            competicao: acumulador.copy().hexdigest()
            for competicao, acumulador in sorted(self._por_competicao.items())
        }
        return ReferenceContentIdentity(
            fingerprint=global_hash.hexdigest(),
            by_competition=por_competicao,
            rows=self._linhas,
        )


@final
@dataclass(frozen=True, slots=True)
class ReferenceContentIdentity:
    """A identidade da população de referência — global e por competição.

    ELA É O INSUMO DA IDENTIDADE DO AJUSTE, e substitui a impressão crua global
    exatamente porque não enxerga a avaliação.
    """

    fingerprint: str
    by_competition: Mapping[str, str] = field(default_factory=dict)
    rows: int = 0

    def of(self, competition: str) -> str:
        impressao = self.by_competition.get(competition)
        if impressao is None:
            raise ValidationError(
                f"a população de referência não contém a competição {competition!r}: "
                "um pacote de artefatos sem população é um pacote sobre nada",
                context={"competition": competition},
            )
        return impressao

    @property
    def competitions(self) -> tuple[str, ...]:
        return tuple(sorted(self.by_competition))

    def as_canonical(self) -> dict[str, object]:
        return {
            "algorithm": REFERENCE_FINGERPRINT_ALGORITHM,
            "by_competition": dict(sorted(self.by_competition.items())),
            "fingerprint": self.fingerprint,
            "rows": self.rows,
        }


@final
@dataclass(frozen=True, slots=True)
class CompetitionNormalizerArtifactBundle:
    """Os artefatos de UMA competição, com identidade própria.

    ELE DEPENDE SÓ DA COMPETIÇÃO DELE. Essa é a propriedade do §8: mexer na
    referência da La Liga não pode mudar a impressão do pacote da Premier
    League — nem por dependência direta, nem por um agregado compartilhado.
    """

    competition: str
    competition_id: CompetitionId
    reference_fingerprint: str
    plan_fingerprint: str
    artifacts: tuple[NormalizerFitArtifact, ...] = ()

    def __post_init__(self) -> None:
        chaves = [a.feature_key for a in self.artifacts]
        if len(set(chaves)) != len(chaves):
            repetidas = sorted({k for k in chaves if chaves.count(k) > 1})
            raise ValidationError(
                f"pacote de {self.competition} com artefato repetido: {repetidas}. "
                "Dois artefatos para o mesmo eixo fariam o segundo decidir em silêncio"
            )
        if list(chaves) != sorted(chaves):
            raise ValidationError(
                f"pacote de {self.competition} fora de ordem — use `of()`: a ordem "
                "entra na impressão, e a do banco não pode decidi-la"
            )
        forasteiros = [
            a.feature_key for a in self.artifacts if a.competition_id != self.competition_id
        ]
        if forasteiros:
            raise ValidationError(
                f"pacote de {self.competition} carregando artefato de outra "
                f"competição: {forasteiros[:3]}. Uma escala de outra liga produziria "
                "um número perfeitamente plausível e errado (PR-05.4 §132)"
            )

    @classmethod
    def of(
        cls,
        *,
        competition: str,
        competition_id: CompetitionId,
        reference_fingerprint: str,
        plan_fingerprint: str,
        artifacts: Iterable[NormalizerFitArtifact],
    ) -> Self:
        return cls(
            competition=competition,
            competition_id=competition_id,
            reference_fingerprint=reference_fingerprint,
            plan_fingerprint=plan_fingerprint,
            artifacts=tuple(sorted(artifacts, key=lambda a: a.feature_key)),
        )

    def artifact_of(self, feature_key: str) -> NormalizerFitArtifact:
        for artefato in self.artifacts:
            if artefato.feature_key == feature_key:
                return artefato
        raise ValidationError(
            f"a competição {self.competition} não tem artefato para {feature_key!r}: "
            "o plano exige um, e transformar sem ele seria inventar uma escala",
            context={"competition": self.competition, "feature": feature_key},
        )

    def counts(self) -> Mapping[str, int]:
        contagem: dict[str, int] = {estado.value: 0 for estado in FitStatus}
        for artefato in self.artifacts:
            contagem[artefato.status.value] += 1
        return contagem

    def as_canonical(self) -> dict[str, object]:
        return {
            "algorithm": BUNDLE_FINGERPRINT_ALGORITHM,
            "artifacts": [
                {"feature_key": a.feature_key, "fingerprint": a.fingerprint} for a in self.artifacts
            ],
            "competition": self.competition,
            "competition_id": str(self.competition_id),
            "plan_fingerprint": self.plan_fingerprint,
            "reference_fingerprint": self.reference_fingerprint,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def __str__(self) -> str:
        return f"{self.competition} · {len(self.artifacts)} artefatos"


@final
@dataclass(frozen=True, slots=True)
class NormalizerArtifactSet:
    """O conjunto completo — imutável a partir de `READY`.

    A IMPRESSÃO SEMÂNTICA COBRE: o plano, a política de divisão, a fronteira do
    ajuste e os pacotes por competição, em ordem. NÃO cobre: a impressão crua
    global, o id da versão crua, o id da execução nem o carimbo — todos eles
    mudam sem o ajuste mudar, e dois deles carregam a avaliação dentro.
    """

    id: str
    plan_fingerprint: str
    split_fingerprint: str
    reference_end_exclusive: Instant
    reference_fingerprint: str
    status: DatasetVersionStatus
    created_at: Instant
    created_by: Actor
    bundles: tuple[CompetitionNormalizerArtifactBundle, ...] = ()
    #: LINHAGEM — persistida, e fora da identidade semântica.
    source_version_id: str = ""
    source_raw_content_fingerprint: str = ""
    reference_rows: int = 0
    completed_at: Instant | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        competicoes = [b.competition for b in self.bundles]
        if len(set(competicoes)) != len(competicoes):
            raise ValidationError(
                f"conjunto com competição repetida: "
                f"{sorted({c for c in competicoes if competicoes.count(c) > 1})}"
            )
        if list(competicoes) != sorted(competicoes):
            raise ValidationError("pacotes fora de ordem — use `of()`: a ordem entra na impressão")
        divergentes = [
            b.competition for b in self.bundles if b.plan_fingerprint != self.plan_fingerprint
        ]
        if divergentes:
            raise ValidationError(
                f"pacote(s) {divergentes[:3]} ajustado(s) sob outro plano: o conjunto "
                "afirmaria um plano que os artefatos dele não seguiram"
            )
        if self.status is DatasetVersionStatus.READY and not self.bundles:
            raise ValidationError(
                "conjunto de artefatos publicado sem pacote nenhum: ele normalizaria o quê?"
            )
        if self.status is DatasetVersionStatus.FAILED and not (self.failure_reason or "").strip():
            raise ValidationError("conjunto de artefatos FAILED sem motivo")
        if self.status.is_terminal and self.completed_at is None:
            raise ValidationError(f"conjunto em {self.status} sem instante de conclusão")

    @classmethod
    def draft(
        cls,
        *,
        plan_fingerprint: str,
        split_fingerprint: str,
        reference_end_exclusive: Instant,
        reference_fingerprint: str,
        at: Instant,
        created_by: Actor,
        source_version_id: str = "",
        source_raw_content_fingerprint: str = "",
    ) -> Self:
        return cls(
            id=str(uuid.uuid4()),
            plan_fingerprint=plan_fingerprint,
            split_fingerprint=split_fingerprint,
            reference_end_exclusive=reference_end_exclusive,
            reference_fingerprint=reference_fingerprint,
            status=DatasetVersionStatus.DRAFT,
            created_at=at,
            created_by=created_by,
            source_version_id=source_version_id,
            source_raw_content_fingerprint=source_raw_content_fingerprint,
        )

    # ------------------------------------------------------------ leitura --

    @property
    def is_readable(self) -> bool:
        return self.status.is_readable_corpus

    @property
    def competitions(self) -> tuple[str, ...]:
        return tuple(b.competition for b in self.bundles)

    @property
    def artifact_count(self) -> int:
        return sum(len(b.artifacts) for b in self.bundles)

    def bundle_of(self, competition: str) -> CompetitionNormalizerArtifactBundle:
        for pacote in self.bundles:
            if pacote.competition == competition:
                return pacote
        raise ValidationError(
            f"o conjunto não tem pacote para a competição {competition!r}: "
            "normalizar linhas dela exigiria uma escala que ninguém ajustou",
            context={"competition": competition},
        )

    def counts(self) -> Mapping[str, int]:
        contagem: dict[str, int] = {estado.value: 0 for estado in FitStatus}
        for pacote in self.bundles:
            for chave, valor in pacote.counts().items():
                contagem[chave] += valor
        return contagem

    def can_move_to(self, target: DatasetVersionStatus) -> bool:
        return can_transition(self.status, target)

    def require_transition(self, target: DatasetVersionStatus) -> None:
        if not self.can_move_to(target):
            raise ValidationError(
                f"o conjunto de artefatos está em {self.status} e não pode ir para "
                f"{target}: o grafo é explícito para que «publicar sem conferir» não "
                "seja alcançável por engano",
                context={"from": self.status.value, "to": target.value},
            )

    # -------------------------------------------------------------- forma --

    def as_canonical(self) -> dict[str, object]:
        """A identidade SEMÂNTICA — sem linhagem, e sem a avaliação (§46)."""
        return {
            "algorithm": ARTIFACT_SET_FINGERPRINT_ALGORITHM,
            "bundles": [
                {"competition": b.competition, "fingerprint": b.fingerprint} for b in self.bundles
            ],
            "plan_fingerprint": self.plan_fingerprint,
            "reference_end_exclusive": instant_text(self.reference_end_exclusive),
            "reference_fingerprint": self.reference_fingerprint,
            "split_fingerprint": self.split_fingerprint,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def lineage(self) -> dict[str, object]:
        """De ONDE ele veio — persistido, e FORA da identidade (§47).

        A IMPRESSÃO CRUA GLOBAL ESTÁ AQUI, e só aqui. Ela é a resposta a «qual
        dataset cru alimentou este ajuste»; colocá-la na identidade faria uma
        partida acrescentada à AVALIAÇÃO mudar o conjunto de artefatos.
        """
        return {
            "reference_rows": self.reference_rows,
            "source_raw_content_fingerprint": self.source_raw_content_fingerprint,
            "source_version_id": self.source_version_id,
        }

    def __str__(self) -> str:
        return (
            f"artefatos {self.fingerprint[:16]} · {len(self.bundles)} competições · "
            f"{self.artifact_count} artefatos ({self.status})"
        )


def build_artifact_set(
    *,
    plan_fingerprint: str,
    split_fingerprint: str,
    reference_end_exclusive: Instant,
    reference: ReferenceContentIdentity,
    bundles: Iterable[CompetitionNormalizerArtifactBundle],
    at: Instant,
    created_by: Actor,
    source_version_id: str = "",
    source_raw_content_fingerprint: str = "",
    identifier: str | None = None,
) -> NormalizerArtifactSet:
    """O conjunto montado — com os pacotes em ordem canônica."""
    return NormalizerArtifactSet(
        id=identifier or str(uuid.uuid4()),
        plan_fingerprint=plan_fingerprint,
        split_fingerprint=split_fingerprint,
        reference_end_exclusive=reference_end_exclusive,
        reference_fingerprint=reference.fingerprint,
        status=DatasetVersionStatus.DRAFT,
        created_at=at,
        created_by=created_by,
        bundles=tuple(sorted(bundles, key=lambda b: b.competition)),
        source_version_id=source_version_id,
        source_raw_content_fingerprint=source_raw_content_fingerprint,
        reference_rows=reference.rows,
    )


def artifact_status_summary(
    bundles: Sequence[CompetitionNormalizerArtifactBundle],
) -> Mapping[str, int]:
    contagem: dict[str, int] = {estado.value: 0 for estado in FitStatus}
    for pacote in bundles:
        for chave, valor in pacote.counts().items():
            contagem[chave] += valor
    return dict(sorted(contagem.items()))
