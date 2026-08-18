"""O manifesto do corpus — a descrição completa e determinística de uma versão.

O QUE ELE RESPONDE, e nada mais responde sem arqueologia:

    o que está aqui dentro         contagens, por família e por partição
    de onde veio                   builds, avaliações, fusões, resoluções
    sob quais regras               versões E impressões das políticas
    o que ficou de fora, e por quê famílias excluídas com motivo e licença
    é o mesmo corpus de ontem?     uma impressão de 64 caracteres

DUAS IMPRESSÕES DIFERENTES, E CONFUNDI-LAS É CARO (§57):

    manifest_sha256          o hash dos BYTES do arquivo `manifest.json`
    corpus_fingerprint       o hash do CONTEÚDO SEMÂNTICO do corpus

O primeiro muda quando o instante de criação muda. O segundo NÃO — ele existe
justamente para responder «duas publicações produziram o mesmo corpus?», e um
carimbo de tempo faria a resposta ser sempre «não».

O MANIFESTO NÃO RECALCULA NADA (§133, §134, §135). O resumo de qualidade vem
das avaliações persistidas; o de cobertura, dos mesmos assessments; o de
licença, das decisões que o build já emitiu. Recalcular aqui criaria uma
segunda opinião sobre perguntas que já foram respondidas — e as duas
divergiriam no primeiro ajuste.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Final, final

from sports_intelligence.domain.corpus.fingerprint import (
    FINGERPRINT_ALGORITHM,
    FINGERPRINT_SCHEMA_VERSION,
)
from sports_intelligence.domain.corpus.membership import MembershipCounts
from sports_intelligence.domain.corpus.scope import CorpusScope
from sports_intelligence.domain.corpus.versions import VersionInputs
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.quality.coverage import CoverageState
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion

#: A versão do FORMATO do manifesto — separada da versão do dataset (§102).
#:
#: Elas mudam por motivos diferentes: o dataset muda quando o CONTEÚDO muda; o
#: schema, quando a FORMA de descrevê-lo muda. Um número só faria acrescentar
#: um campo ao manifesto parecer um corpus novo.
MANIFEST_SCHEMA_VERSION: Final[str] = "1.0"

#: Teto de exemplos por categoria de problema (§27). O manifesto descreve o
#: corpus; despejar um milhão de issues nele o transformaria no corpus.
MAX_ISSUE_EXAMPLES: Final[int] = 10


@final
@dataclass(frozen=True, slots=True)
class FamilyCoverageSummary:
    """A cobertura de uma família, agregada sobre os assessments (§134).

    `NOT_DECLARED` SOBREVIVE À AGREGAÇÃO, e é o ponto mais fácil de perder.
    Somar contagens de dez mil partidas e reportar `0%` para eventos apagaria a
    diferença entre «as fontes não trabalham com eventos» e «as fontes
    prometeram eventos e não vieram» — que continuam exigindo ações opostas.
    """

    family: str
    state: str
    matches_with_data: int = 0
    matches_total: int = 0
    available_total: int = 0
    expected_total: int | None = None

    def __post_init__(self) -> None:
        if self.matches_with_data > self.matches_total:
            raise ValidationError(
                f"{self.family}: {self.matches_with_data} partidas com dado de "
                f"{self.matches_total} — o subconjunto é maior que o conjunto"
            )

    @property
    def ratio(self) -> float | None:
        """A fração de partidas com dado, ou `None` quando não há denominador.

        `None` E NÃO `0.0`, pela mesma razão de sempre: um corpus sem partida
        nenhuma não tem 0% de cobertura, tem cobertura indefinida.
        """
        if self.state == CoverageState.NOT_DECLARED.value or not self.matches_total:
            return None
        return self.matches_with_data / self.matches_total

    def as_canonical(self) -> dict[str, object]:
        return {
            "available_total": self.available_total,
            "expected_total": self.expected_total,
            "family": self.family,
            "matches_total": self.matches_total,
            "matches_with_data": self.matches_with_data,
            "ratio": None if self.ratio is None else round(self.ratio, 6),
            "state": self.state,
        }


@final
@dataclass(frozen=True, slots=True)
class QualitySummary:
    """Os seis eixos, agregados pelo PIOR caso — nunca pela média (§25).

    O ELO MAIS FRACO OUTRA VEZ. Uma média sobre dez mil partidas faria cem de
    linhagem quebrada desaparecerem no terceiro decimal, e são justamente elas
    que precisam aparecer. O manifesto reporta o pior de cada eixo e as
    contagens por veredito; os assessments individuais continuam sendo a
    autoridade e não são substituídos por este resumo.
    """

    worst_integrity: float = 1.0
    worst_consistency: float = 1.0
    worst_completeness: float = 1.0
    worst_identity_confidence: float = 1.0
    worst_temporal_integrity: float = 1.0
    worst_provenance_quality: float = 1.0
    eligible: int = 0
    review_required: int = 0
    ineligible: int = 0

    def as_canonical(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "ineligible": self.ineligible,
            "review_required": self.review_required,
            "worst_completeness": round(self.worst_completeness, 6),
            "worst_consistency": round(self.worst_consistency, 6),
            "worst_identity_confidence": round(self.worst_identity_confidence, 6),
            "worst_integrity": round(self.worst_integrity, 6),
            "worst_provenance_quality": round(self.worst_provenance_quality, 6),
            "worst_temporal_integrity": round(self.worst_temporal_integrity, 6),
        }


@final
@dataclass(frozen=True, slots=True)
class LicenseSummary:
    """O que entrou, o que saiu, e sob qual licença (§26).

    «ODDS EXCLUÍDA» NÃO RESPONDE NADA. A pergunta de uma auditoria jurídica é
    «este corpus comercial descartou o quê, e por causa de qual licença» — e
    ela precisa ter resposta no manifesto, sem diff externo contra outro corpus.
    """

    usage_scope: str
    #: TODA licença que alimentou alguma família incluída — inclusive a que
    #: apenas CONFIRMOU um fato que outra fonte já sustentava sozinha.
    licenses_present: tuple[str, ...] = ()
    #: As licenças que sustentam alguma família incluída SOZINHAS (PR-04.2.1
    #: §42, ADR-0025).
    #:
    #: POR QUE AS DUAS LISTAS, e por que a segunda não é redundante: uma fonte
    #: `RESEARCH_ONLY` que apenas confirma um placar de domínio público APARECE
    #: em `licenses_present` — ela de fato alimentou a família — e o fato
    #: continua comercialmente livre, porque a fonte pública o sustenta
    #: sozinha. Com uma lista só, o manifesto de um corpus comercial
    #: perfeitamente publicável diria «contém RESEARCH_ONLY» sem qualificação,
    #: e a auditoria pararia ali.
    independent_support: tuple[str, ...] = ()
    families_included: tuple[str, ...] = ()
    families_excluded: tuple[str, ...] = ()
    #: `família → motivo → quantas partidas`. Contagem, e não lista de ids.
    exclusion_reasons: dict[str, dict[str, int]] = field(default_factory=dict)
    #: `família → licença` que causou a exclusão, quando foi licença.
    exclusion_licenses: dict[str, str] = field(default_factory=dict)
    requires_attribution: bool = False

    def as_canonical(self) -> dict[str, object]:
        return {
            "exclusion_licenses": dict(sorted(self.exclusion_licenses.items())),
            "exclusion_reasons": {
                familia: dict(sorted(motivos.items()))
                for familia, motivos in sorted(self.exclusion_reasons.items())
            },
            "families_excluded": sorted(self.families_excluded),
            "families_included": sorted(self.families_included),
            "independent_support": sorted(self.independent_support),
            "licenses_present": sorted(self.licenses_present),
            "requires_attribution": self.requires_attribution,
            "usage_scope": self.usage_scope,
        }


@final
@dataclass(frozen=True, slots=True)
class IssueSummary:
    """Contagens e exemplos limitados (§27)."""

    by_code: dict[str, int] = field(default_factory=dict)
    by_severity: dict[str, int] = field(default_factory=dict)
    records_skipped: int = 0
    records_review_required: int = 0
    families_excluded: int = 0
    examples: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.examples) > MAX_ISSUE_EXAMPLES:
            raise ValidationError(
                f"{len(self.examples)} exemplos de problema no manifesto, acima de "
                f"{MAX_ISSUE_EXAMPLES} — o manifesto descreve o corpus, não o contém"
            )

    def as_canonical(self) -> dict[str, object]:
        return {
            "by_code": dict(sorted(self.by_code.items())),
            "by_severity": dict(sorted(self.by_severity.items())),
            "examples": list(self.examples),
            "families_excluded": self.families_excluded,
            "records_review_required": self.records_review_required,
            "records_skipped": self.records_skipped,
        }


@final
@dataclass(frozen=True, slots=True)
class CorpusObjectRef:
    """Um objeto materializado, com o que prova que ele é aquele (§55, §118)."""

    object_key: str
    family: str
    competition: str
    season: str
    sha256: ContentHash
    size_bytes: int
    row_count: int
    content_type: str = "application/vnd.apache.parquet"

    def __post_init__(self) -> None:
        if self.size_bytes < 0 or self.row_count < 0:
            raise ValidationError(f"{self.object_key}: tamanho ou contagem negativa")
        if not self.object_key.strip():
            raise ValidationError("objeto de corpus sem chave")

    def as_canonical(self) -> dict[str, object]:
        return {
            "competition": self.competition,
            "content_type": self.content_type,
            "family": self.family,
            "object_key": self.object_key,
            "row_count": self.row_count,
            "season": self.season,
            "sha256": self.sha256.value,
            "size_bytes": self.size_bytes,
        }


@final
@dataclass(frozen=True, slots=True)
class HistoricalCanonicalManifest:
    """A descrição completa e determinística de uma versão do corpus."""

    id: str
    schema_version: str
    dataset_id: str
    dataset_name: str
    dataset_version: DatasetVersion
    dataset_version_id: str
    scope: CorpusScope
    inputs: VersionInputs
    counts: MembershipCounts
    coverage: tuple[FamilyCoverageSummary, ...]
    quality: QualitySummary
    license: LicenseSummary
    issues: IssueSummary
    #: A impressão SEMÂNTICA do corpus. É ela que o §34 e o §89 comparam.
    corpus_fingerprint: ContentHash
    created_at: Instant
    #: QUAL construção produziu a impressão (PR-04.3.1 §20, §62). Sem isto,
    #: uma impressão do XOR-fold do PR-04.3 e uma da serialização ordenada são
    #: dois hex de 64 caracteres indistinguíveis — e compará-los produziria
    #: «corpus diferente» sobre o mesmo conteúdo, sem explicação nenhuma.
    fingerprint_algorithm: str = FINGERPRINT_ALGORITHM
    fingerprint_schema_version: str = FINGERPRINT_SCHEMA_VERSION
    objects: tuple[CorpusObjectRef, ...] = ()
    #: Cobertura por partição, para quem lê competição a competição (§24).
    coverage_by_partition: dict[str, list[dict[str, object]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != MANIFEST_SCHEMA_VERSION:
            raise ValidationError(
                f"manifesto com schema {self.schema_version!r}: este motor escreve e "
                f"lê {MANIFEST_SCHEMA_VERSION!r}, e aceitar outro faria um documento "
                "de forma desconhecida passar por conferido"
            )

    def as_canonical(self) -> dict[str, object]:
        """O DOCUMENTO inteiro — é ele que vira `manifest.json`.

        INCLUI `created_at` E OS IDS DE EXECUÇÃO. Eles servem à travessia de
        linhagem e à auditoria; o que eles NÃO fazem é entrar na impressão
        semântica, que é outra função (§19, §31).
        """
        return {
            "corpus_fingerprint": self.corpus_fingerprint.value,
            "counts": self.counts.as_canonical(),
            "coverage": [c.as_canonical() for c in self.coverage],
            "coverage_by_partition": {
                particao: sorted(linhas, key=lambda linha: str(linha.get("family")))
                for particao, linhas in sorted(self.coverage_by_partition.items())
            },
            "created_at": self.created_at.isoformat(),
            "fingerprint_algorithm": self.fingerprint_algorithm,
            "fingerprint_schema_version": self.fingerprint_schema_version,
            "dataset_id": self.dataset_id,
            "dataset_name": self.dataset_name,
            "dataset_version": str(self.dataset_version),
            "dataset_version_id": self.dataset_version_id,
            # O `id` ENTRA NO DOCUMENTO. Ele não entra na impressão SEMÂNTICA
            # — essa é outra função (§31) —, mas o documento é o que volta do
            # banco, e um manifesto relido com id novo apontaria para uma linha
            # que não é a dele.
            "id": self.id,
            "inputs": self.inputs.as_canonical(),
            "issues": self.issues.as_canonical(),
            "license": self.license.as_canonical(),
            "objects": [o.as_canonical() for o in self.objects],
            "quality": self.quality.as_canonical(),
            "schema_version": self.schema_version,
            "scope": self.scope.as_canonical(),
        }

    def to_json(self) -> bytes:
        """A serialização canônica que vai para o object store (§56).

        DETERMINÍSTICA POR CONSTRUÇÃO: chaves ordenadas, separador fixo,
        `ensure_ascii=False`. Dois manifestos do mesmo corpus produzem os
        mesmos bytes, e é isso que torna `manifest_sha256` comparável.
        """
        return json.dumps(
            self.as_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @property
    def manifest_sha256(self) -> ContentHash:
        """O hash dos BYTES do documento — diferente da impressão do corpus."""
        return ContentHash(hashlib.sha256(self.to_json()).hexdigest())

    def __str__(self) -> str:
        return (
            f"manifesto {self.dataset_name} {self.dataset_version} "
            f"[{self.scope.usage}] · {self.counts.matches} partida(s)"
        )
