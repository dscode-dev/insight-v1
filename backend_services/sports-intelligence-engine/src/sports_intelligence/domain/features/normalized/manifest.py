"""O manifesto do dataset normalizado — e o mapa que ele carrega.

O QUE ELE RESPONDE ALÉM DO QUE O MANIFESTO CRU JÁ RESPONDIA:

    qual eixo foi transformado como     o plano inteiro, eixo a eixo
    com quais números                   `(competição, eixo) → impressão do artefato`
    o que ficou sem escala, e por quê   as contagens de disponibilidade da
                                        NORMALIZAÇÃO, separadas das de origem
    é a mesma base de comparação?       a impressão de REFERÊNCIA, sozinha

O MAPA `(competição, eixo) → artefato` MORA AQUI, e não na linha (§96). Gravar
cento e cinco impressões de artefato em cada uma das noventa e uma mil linhas
multiplicaria o arquivo para repetir noventa e um mil vezes o mesmo mapa de
algumas dezenas de entradas. A linha carrega a impressão do PACOTE da
competição dela; o manifesto abre o pacote.

O PLANO ENTRA POR EXTENSO, E NÃO SÓ PELA IMPRESSÃO. «Este eixo foi
reescalado?» é a primeira pergunta de quem lê o dataset seis meses depois, e a
impressão só responde «é o mesmo plano de antes» — o que não ajuda quem nunca
viu o de antes. O plano por extenso custa algumas centenas de linhas de JSON e
dispensa o código do motor para ser lido.

AS DUAS FAMÍLIAS DE DISPONIBILIDADE SÃO CONTADAS SEPARADAS, pela razão do §62:
um eixo sem valor cru e um eixo com valor cru e sem escala exigem ações opostas
— procurar a fonte, ou aceitar que aquela liga não tem dispersão. Um contador só
apagaria a diferença exatamente onde ela decide o que fazer.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, final

from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.features.dataset.split import DatasetSplit, SplitCounts
from sports_intelligence.domain.features.normalized.artifacts import (
    CompetitionNormalizerArtifactBundle,
)
from sports_intelligence.domain.features.normalized.plan import NormalizationPlan
from sports_intelligence.domain.features.normalized.rows import (
    NORMALIZED_CONTENT_FINGERPRINT_ALGORITHM,
    NORMALIZED_ROW_DIGEST_ALGORITHM,
    NormalizationAvailability,
)
from sports_intelligence.domain.features.normalized.versions import (
    NormalizedFeatureRepresentationSpec,
)
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion

#: A versão do FORMATO. Separada da versão do dataset pelo motivo de sempre: o
#: dataset muda quando o conteúdo muda; o schema, quando a forma de descrevê-lo
#: muda.
NORMALIZED_MANIFEST_SCHEMA_VERSION: Final[str] = "1.0"


@final
@dataclass(frozen=True, slots=True)
class NormalizedObjectRef:
    """Um Parquet normalizado, com o que prova que ele é aquele.

    ELE CARREGA A CONTAGEM DA PARTIÇÃO CRUA CORRESPONDENTE. O contrato 1:1 vale
    globalmente e vale por partição, e conferir só o total deixaria passar o
    caso em que uma partição perdeu linhas e outra ganhou.
    """

    object_key: str
    split: DatasetSplit
    competition: str
    season: str
    sha256: ContentHash
    size_bytes: int
    row_count: int
    match_count: int = 0
    source_object_key: str = ""
    content_type: str = "application/vnd.apache.parquet"

    def __post_init__(self) -> None:
        if self.size_bytes < 0 or self.row_count < 0 or self.match_count < 0:
            raise ValidationError(f"{self.object_key}: tamanho ou contagem negativa")
        if not self.object_key.strip():
            raise ValidationError("objeto normalizado sem chave")

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
            "source_object_key": self.source_object_key,
            "split": self.split.value,
        }


@final
@dataclass(frozen=True, slots=True)
class ArtifactMapEntry:
    """Uma entrada do mapa `(competição, eixo) → artefato`.

    O STATUS VIAJA JUNTO DA IMPRESSÃO porque «este eixo não foi normalizado
    nesta competição» é uma resposta legítima, e ela precisa ser lida sem abrir
    o banco de artefatos.
    """

    competition: str
    feature_key: str
    strategy: str
    status: str
    artifact_fingerprint: str = ""
    sample_size: int = 0

    def as_canonical(self) -> dict[str, object]:
        return {
            "artifact_fingerprint": self.artifact_fingerprint,
            "competition": self.competition,
            "feature_key": self.feature_key,
            "sample_size": self.sample_size,
            "status": self.status,
            "strategy": self.strategy,
        }


@final
@dataclass(frozen=True, slots=True)
class NormalizationAvailabilitySummary:
    """Quantas células em cada estado da NORMALIZAÇÃO.

    ELA NÃO É UM PERCENTUAL DE QUALIDADE. Um dataset com 40% das células em
    `SOURCE_VALUE_UNAVAILABLE` no minuto 1 é normal — quase nenhuma janela
    móvel fechou ainda. Um com 40% em `ARTIFACT_DEGENERATE_SCALE` diz que o
    ajuste não encontrou dispersão, e é um problema de outro tipo. Colapsá-los
    num número apagaria justamente a distinção que decide o que fazer.
    """

    total_cells: int = 0
    by_state: Mapping[str, int] = field(default_factory=dict)
    by_source_state: Mapping[str, int] = field(default_factory=dict)

    @property
    def available(self) -> int:
        return self.by_state.get(NormalizationAvailability.AVAILABLE.value, 0)

    @property
    def coverage(self) -> float:
        return 0.0 if not self.total_cells else self.available / self.total_cells

    @property
    def artifact_unavailable(self) -> int:
        """As células perdidas pelo AJUSTE — e não pela origem."""
        return sum(
            self.by_state.get(estado.value, 0)
            for estado in NormalizationAvailability
            if estado.value.startswith("ARTIFACT_")
        )

    def as_canonical(self) -> dict[str, object]:
        return {
            "by_source_state": dict(sorted(self.by_source_state.items())),
            "by_state": dict(sorted(self.by_state.items())),
            "total_cells": self.total_cells,
        }


@final
@dataclass(frozen=True, slots=True)
class NormalizedFeatureDatasetManifest:
    """A descrição completa e determinística de uma versão normalizada."""

    id: str
    schema_version: str
    dataset_id: str
    dataset_name: str
    dataset_version: DatasetVersion
    dataset_version_id: str
    source_dataset_version_id: str
    source_version: DatasetVersion
    source_raw_content_fingerprint: ContentHash
    source_row_count: int
    representation: NormalizedFeatureRepresentationSpec
    plan: NormalizationPlan
    counts: SplitCounts
    match_count: int
    row_count: int
    availability: NormalizationAvailabilitySummary
    normalized_content_fingerprint: ContentHash
    normalized_reference_content_fingerprint: ContentHash
    normalized_evaluation_content_fingerprint: ContentHash
    reference_end_exclusive: Instant
    created_at: Instant
    row_digest_algorithm: str = NORMALIZED_ROW_DIGEST_ALGORITHM
    content_fingerprint_algorithm: str = NORMALIZED_CONTENT_FINGERPRINT_ALGORITHM
    objects: tuple[NormalizedObjectRef, ...] = ()
    artifact_map: tuple[ArtifactMapEntry, ...] = ()
    rows_by_partition: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != NORMALIZED_MANIFEST_SCHEMA_VERSION:
            raise ValidationError(
                f"manifesto normalizado com schema {self.schema_version!r}: este motor "
                f"escreve e lê {NORMALIZED_MANIFEST_SCHEMA_VERSION!r}, e aceitar outro "
                "faria um documento de forma desconhecida passar por conferido"
            )
        gravadas = sum(o.row_count for o in self.objects)
        if self.objects and gravadas != self.row_count:
            raise ValidationError(
                f"o manifesto declara {self.row_count} linhas e os objetos somam "
                f"{gravadas}: a reconciliação existe para pegar exatamente isto",
                context={"declared": self.row_count, "in_objects": gravadas},
            )
        if self.source_row_count and self.row_count != self.source_row_count:
            raise ValidationError(
                f"manifesto normalizado com {self.row_count} linhas contra "
                f"{self.source_row_count} do cru: a normalização é 1:1, e um manifesto "
                "que já publica a diferença nunca chegaria a ser conferido",
                context={"normalized": self.row_count, "raw": self.source_row_count},
            )
        chaves = [(e.competition, e.feature_key) for e in self.artifact_map]
        if len(set(chaves)) != len(chaves):
            raise ValidationError(
                "mapa de artefatos com entrada repetida: dois artefatos para o mesmo "
                "par (competição, eixo) fariam o segundo decidir em silêncio"
            )

    # ------------------------------------------------------------ leitura --

    def entry_of(self, competition: str, feature_key: str) -> ArtifactMapEntry:
        for entrada in self.artifact_map:
            if entrada.competition == competition and entrada.feature_key == feature_key:
                return entrada
        raise ValidationError(
            f"o manifesto não descreve o par ({competition!r}, {feature_key!r})",
            context={"competition": competition, "feature": feature_key},
        )

    @property
    def competitions(self) -> tuple[str, ...]:
        return tuple(sorted({e.competition for e in self.artifact_map}))

    # -------------------------------------------------------------- forma --

    def as_canonical(self) -> dict[str, object]:
        """O DOCUMENTO inteiro — é ele que vira `manifest.json`."""
        return {
            "artifact_map": [e.as_canonical() for e in self.artifact_map],
            "availability": self.availability.as_canonical(),
            "content_fingerprint_algorithm": self.content_fingerprint_algorithm,
            "counts": self.counts.as_canonical(),
            "created_at": self.created_at.isoformat(),
            "dataset_id": self.dataset_id,
            "dataset_name": self.dataset_name,
            "dataset_version": str(self.dataset_version),
            "dataset_version_id": self.dataset_version_id,
            "fit": {
                "reference_end_exclusive": self.reference_end_exclusive.isoformat(),
                "split": "REFERENCE",
            },
            "fingerprints": {
                "evaluation": self.normalized_evaluation_content_fingerprint.value,
                "normalized": self.normalized_content_fingerprint.value,
                "reference": self.normalized_reference_content_fingerprint.value,
            },
            "id": self.id,
            "match_count": self.match_count,
            "objects": [o.as_canonical() for o in self.objects],
            "plan": self.plan.as_canonical(),
            "representation": {
                **self.representation.as_document(),
                "fingerprint": self.representation.fingerprint,
            },
            "row_count": self.row_count,
            "row_digest_algorithm": self.row_digest_algorithm,
            "rows_by_partition": dict(sorted(self.rows_by_partition.items())),
            "schema_version": self.schema_version,
            "source": {
                "raw_content_fingerprint": self.source_raw_content_fingerprint.value,
                "row_count": self.source_row_count,
                "version": str(self.source_version),
                "version_id": self.source_dataset_version_id,
            },
        }

    def to_json(self) -> bytes:
        """A serialização canônica que vai para o object store."""
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
            f"manifesto normalizado {self.dataset_name} {self.dataset_version} "
            f"({self.row_count} linhas)"
        )


def artifact_map_of(
    bundles: Sequence[CompetitionNormalizerArtifactBundle],
    plan: NormalizationPlan,
) -> tuple[ArtifactMapEntry, ...]:
    """O mapa montado a partir dos pacotes por competição.

    ELE COBRE SÓ OS EIXOS COM ARTEFATO. Os `PASS_THROUGH` não têm artefato
    nenhum — inventar uma entrada vazia para eles faria o mapa insinuar que
    houve um ajuste que não houve. O plano, que está no mesmo manifesto, já diz
    quais eixos passam direto.
    """
    entradas = [
        ArtifactMapEntry(
            competition=pacote.competition,
            feature_key=artefato.feature_key,
            strategy=plan.strategy_of(artefato.feature_key).value,
            status=artefato.status.value,
            artifact_fingerprint=artefato.fingerprint,
            sample_size=artefato.available_count,
        )
        for pacote in bundles
        for artefato in pacote.artifacts
    ]
    return tuple(sorted(entradas, key=lambda e: (e.competition, e.feature_key)))
