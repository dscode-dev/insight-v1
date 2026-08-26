"""O manifesto do dataset de features — o que está lá dentro, e sob quais regras.

O QUE ELE RESPONDE, e nada mais responde sem arqueologia:

    o que está aqui dentro     linhas e partidas, por metade e por partição
    de onde veio               a VERSÃO do corpus, com a impressão dela
    sob quais regras           espaço, grade e divisão — versões E impressões
    o que ficou de fora        o catálogo de exclusões da grade, com motivo
    quanto está disponível     as contagens por estado de disponibilidade
    é o mesmo dataset?         uma impressão de 64 caracteres

DUAS IMPRESSÕES DIFERENTES, pelo mesmo motivo do corpus (§99):

    manifest_sha256           o hash dos BYTES do `manifest.json`
    raw_content_fingerprint   o hash do CONTEÚDO das linhas materializadas

O primeiro muda quando o instante de criação muda. O segundo não — ele existe
para responder «duas construções produziram o mesmo dataset?», e um carimbo de
tempo faria a resposta ser sempre «não».

O MANIFESTO NÃO RECALCULA NADA. As contagens vêm da construção, as impressões
das políticas vêm das políticas, e a impressão de conteúdo vem da cadeia
ordenada. Recalcular aqui criaria uma segunda opinião sobre perguntas já
respondidas — e as duas divergiriam no primeiro ajuste.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Final, final

from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.features.dataset.grid import GRID_EXCLUSIONS_V1
from sports_intelligence.domain.features.dataset.rows import (
    CONTENT_FINGERPRINT_ALGORITHM,
    ROW_DIGEST_ALGORITHM,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit, SplitCounts
from sports_intelligence.domain.features.dataset.versions import FeatureDatasetSpec
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion

#: A versão do FORMATO do manifesto — separada da versão do dataset. Elas mudam
#: por motivos diferentes: o dataset muda quando o CONTEÚDO muda; o schema,
#: quando a FORMA de descrevê-lo muda.
FEATURE_MANIFEST_SCHEMA_VERSION: Final[str] = "1.0"


@final
@dataclass(frozen=True, slots=True)
class FeatureObjectRef:
    """Um Parquet materializado, com o que prova que ele é aquele.

    `split`, `competition` E `season` SÃO A PARTIÇÃO, e estão aqui repetidos do
    caminho de propósito: reconciliar manifesto com banco não pode depender de
    fazer análise sintática de chave de objeto.
    """

    object_key: str
    split: DatasetSplit
    competition: str
    season: str
    sha256: ContentHash
    size_bytes: int
    row_count: int
    match_count: int = 0
    content_type: str = "application/vnd.apache.parquet"

    def __post_init__(self) -> None:
        if self.size_bytes < 0 or self.row_count < 0 or self.match_count < 0:
            raise ValidationError(f"{self.object_key}: tamanho ou contagem negativa")
        if not self.object_key.strip():
            raise ValidationError("objeto de features sem chave")

    def as_canonical(self) -> dict[str, object]:
        return {
            "competition": self.competition,
            "content_type": self.content_type,
            "match_count": self.match_count,
            "object_key": self.object_key,
            "row_count": self.row_count,
            "season": self.season,
            "sha256": self.sha256.value,
            "size_bytes": self.size_bytes,
            "split": self.split.value,
        }


@final
@dataclass(frozen=True, slots=True)
class AvailabilitySummary:
    """Quantos valores em cada estado — a saúde do dataset, contada.

    ELA NÃO É UMA MÉDIA DE QUALIDADE. Um dataset em que 30% dos valores estão
    `TEMPORALLY_UNAVAILABLE` no minuto 1 é normal; um em que 30% estão
    `SOURCE_UNAVAILABLE` é um problema de cobertura. Colapsá-los num único
    percentual apagaria a diferença.
    """

    total_values: int = 0
    by_state: dict[str, int] = field(default_factory=dict)

    @property
    def available(self) -> int:
        return self.by_state.get("AVAILABLE", 0)

    @property
    def coverage(self) -> float:
        return 0.0 if not self.total_values else self.available / self.total_values

    def as_canonical(self) -> dict[str, object]:
        return {
            "by_state": dict(sorted(self.by_state.items())),
            "total_values": self.total_values,
        }


@final
@dataclass(frozen=True, slots=True)
class HistoricalFeatureDatasetManifest:
    """A descrição completa e determinística de uma versão do dataset."""

    id: str
    schema_version: str
    dataset_id: str
    dataset_name: str
    dataset_version: DatasetVersion
    dataset_version_id: str
    source_version_id: str
    source_version: DatasetVersion
    source_corpus_fingerprint: ContentHash
    spec: FeatureDatasetSpec
    counts: SplitCounts
    match_count: int
    row_count: int
    availability: AvailabilitySummary
    raw_content_fingerprint: ContentHash
    created_at: Instant
    row_digest_algorithm: str = ROW_DIGEST_ALGORITHM
    content_fingerprint_algorithm: str = CONTENT_FINGERPRINT_ALGORITHM
    objects: tuple[FeatureObjectRef, ...] = ()
    #: Linhas por partição, para quem lê competição a competição.
    rows_by_partition: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != FEATURE_MANIFEST_SCHEMA_VERSION:
            raise ValidationError(
                f"manifesto de features com schema {self.schema_version!r}: este motor "
                f"escreve e lê {FEATURE_MANIFEST_SCHEMA_VERSION!r}, e aceitar outro "
                "faria um documento de forma desconhecida passar por conferido"
            )
        gravadas = sum(o.row_count for o in self.objects)
        if self.objects and gravadas != self.row_count:
            raise ValidationError(
                f"o manifesto declara {self.row_count} linhas e os objetos somam "
                f"{gravadas}: a reconciliação existe para pegar exatamente isto, e um "
                "manifesto que já se contradiz nunca chegaria a ser conferido",
                context={"declared": self.row_count, "in_objects": gravadas},
            )

    def as_canonical(self) -> dict[str, object]:
        """O DOCUMENTO inteiro — é ele que vira `manifest.json`."""
        return {
            "availability": self.availability.as_canonical(),
            "content_fingerprint_algorithm": self.content_fingerprint_algorithm,
            "counts": self.counts.as_canonical(),
            "created_at": self.created_at.isoformat(),
            "dataset_id": self.dataset_id,
            "dataset_name": self.dataset_name,
            "dataset_version": str(self.dataset_version),
            "dataset_version_id": self.dataset_version_id,
            "grid_exclusions": [e.as_canonical() for e in GRID_EXCLUSIONS_V1],
            "id": self.id,
            "match_count": self.match_count,
            "objects": [o.as_canonical() for o in self.objects],
            "raw_content_fingerprint": self.raw_content_fingerprint.value,
            "row_count": self.row_count,
            "row_digest_algorithm": self.row_digest_algorithm,
            "rows_by_partition": dict(sorted(self.rows_by_partition.items())),
            "schema_version": self.schema_version,
            "source": {
                "corpus_fingerprint": self.source_corpus_fingerprint.value,
                "version": str(self.source_version),
                "version_id": self.source_version_id,
            },
            "spec": self.spec.as_canonical(),
        }

    def to_json(self) -> bytes:
        """A serialização canônica que vai para o object store.

        DETERMINÍSTICA POR CONSTRUÇÃO: chaves ordenadas, separador fixo,
        `ensure_ascii=False`. Dois manifestos do mesmo dataset produzem os
        mesmos bytes, e é isso que torna `manifest_sha256` comparável.
        """
        return json.dumps(
            self.as_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @property
    def manifest_sha256(self) -> str:
        """O hash dos BYTES do documento — e NÃO do conteúdo do dataset."""
        return hashlib.sha256(self.to_json()).hexdigest()

    def __str__(self) -> str:
        return (
            f"manifesto de features {self.dataset_name} {self.dataset_version} "
            f"({self.row_count} linhas)"
        )
