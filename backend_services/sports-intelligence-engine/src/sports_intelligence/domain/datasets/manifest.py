"""O manifesto: a prova de qual entrada exata gerou um processamento.

A PERGUNTA QUE ELE EXISTE PARA RESPONDER, e que só aparece depois de o motor
estar rodando há meses: *este resultado de 2027 saiu de quais bytes?*

Sem manifesto, a resposta é uma reconstrução — consultar o banco hoje e supor
que o dataset não mudou. Ele mudou: um arquivo foi acrescentado, a licença foi
corrigida, a versão do validador subiu. A suposição não falha, ela só fica
errada, e é assim que uma investigação de regressão persegue uma diferença que
não está onde se procura.

O manifesto congela o conjunto no instante da validação: quais arquivos, quais
hashes, quantas linhas, de que fonte, sob que licença, com que validador.

O FINGERPRINT E POR QUE ELE VALE O CUSTO. Serializado canonicamente e
hasheado, o manifesto vira um identificador de 64 caracteres que responde
"é a mesma entrada?" comparando duas strings — em log, em métrica, no nome de
um artefato de saída. Sem ele a mesma pergunta exige carregar dois manifestos
e compará-los campo a campo, e ninguém faz isso no meio de um incidente.

A serialização é DETERMINÍSTICA por construção: chaves ordenadas, arquivos
ordenados por hash, separadores sem espaço, UTF-8, e nenhum campo derivado do
relógio dentro do que é hasheado. A última é a que mais escapa — incluir
`created_at` no fingerprint faria o mesmo conteúdo produzir impressões
diferentes a cada emissão, e o identificador deixaria de identificar.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final, Self, final

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.datasets.models import Dataset
from sports_intelligence.domain.datasets.validation import (
    DatasetValidationReport,
    ValidatorVersion,
)
from sports_intelligence.domain.shared.errors import ConflictError, ValidationError
from sports_intelligence.domain.shared.identity import DatasetId
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion

#: A versão do FORMATO do manifesto — não do dataset, não do validador.
#:
#: Ela existe para que um manifesto lido em 2028 diga por qual regra foi
#: escrito. Sem isso, acrescentar um campo mudaria o fingerprint de todo
#: manifesto reemitido, e a mudança pareceria mudança de conteúdo.
MANIFEST_SCHEMA_VERSION: Final[str] = "1.0"


@final
@dataclass(frozen=True, slots=True)
class ManifestFile:
    """A entrada de um arquivo no manifesto. Só o que prova identidade."""

    file_id: str
    filename: str
    format: str
    sha256: ContentHash
    size_bytes: int
    row_count: int | None
    column_count: int | None

    def as_canonical(self) -> dict[str, Any]:
        return {
            "column_count": self.column_count,
            "file_id": self.file_id,
            "filename": self.filename,
            "format": self.format,
            "row_count": self.row_count,
            "sha256": self.sha256.value,
            "size_bytes": self.size_bytes,
        }


@final
@dataclass(frozen=True, slots=True)
class DatasetManifest:
    """O conjunto congelado. Imutável, endereçável e comparável.

    NÃO CONTÉM DADO, SÓ IDENTIDADE. Nenhuma linha do dataset entra aqui — o
    manifesto é o índice remissivo do arquivo bruto, e é do arquivo bruto que
    o conteúdo é lido quando alguém precisa dele. Um manifesto que carregasse
    amostras cresceria com o dataset e deixaria de caber onde ele precisa
    caber: numa coluna de banco, num log, num cabeçalho.
    """

    dataset_id: DatasetId
    dataset_name: str
    dataset_version: DatasetVersion
    files: tuple[ManifestFile, ...]
    source_name: str
    source_type: str
    license_class: str
    source_url: str | None
    retrieved_at: Instant
    declared_competitions: tuple[str, ...]
    declared_seasons: tuple[str, ...]
    validation_id: str
    validation_status: str
    validator_version: ValidatorVersion
    rows_observed: int
    issue_count: int
    created_at: Instant
    schema_version: str = MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.files:
            raise ValidationError(
                "manifesto sem arquivo: ele existe para provar qual entrada foi usada, "
                "e um conjunto vazio não prova nada"
            )
        hashes = [f.sha256.value for f in self.files]
        if len(set(hashes)) != len(hashes):
            raise ValidationError("manifesto com conteúdo repetido")
        # Ordem canônica garantida na construção, e conferida aqui: um
        # manifesto construído por outro caminho com a ordem trocada teria
        # outro fingerprint para o mesmo conteúdo.
        if hashes != sorted(hashes):
            raise ValidationError("arquivos do manifesto fora da ordem canônica (por sha256)")

    @classmethod
    def build(
        cls,
        *,
        dataset: Dataset,
        report: DatasetValidationReport,
        created_at: Instant,
    ) -> Self:
        """Congela o dataset validado.

        SÓ ARQUIVOS COM BYTES CONFIRMADOS ENTRAM. `stored_files` e não
        `files`: um arquivo em `PENDING` é uma promessa, e um manifesto que
        listasse promessas afirmaria ter provado o que não provou.
        """
        if report.dataset_id != dataset.id:
            raise ConflictError(
                "o relatório é de outro dataset",
                context={"report": str(report.dataset_id), "dataset": str(dataset.id)},
            )
        if report.dataset_version != dataset.version:
            raise ConflictError(
                f"o relatório é da versão {report.dataset_version} e o dataset está em "
                f"{dataset.version} — o manifesto descreveria um conteúdo que não foi validado"
            )
        armazenados = dataset.stored_files
        if not armazenados:
            raise ConflictError("nenhum arquivo com bytes confirmados para manifestar")

        entradas = tuple(
            sorted(
                (
                    ManifestFile(
                        file_id=str(arquivo.id),
                        filename=arquivo.safe_filename,
                        format=arquivo.format.value,
                        sha256=arquivo.content_hash,
                        size_bytes=arquivo.size_bytes,
                        row_count=arquivo.row_count,
                        column_count=arquivo.column_count,
                    )
                    for arquivo in armazenados
                ),
                key=lambda f: f.sha256.value,
            )
        )
        return cls(
            dataset_id=dataset.id,
            dataset_name=dataset.name,
            dataset_version=dataset.version,
            files=entradas,
            source_name=dataset.source.source_name,
            source_type=dataset.source.source_type.value,
            license_class=dataset.source.license_class.value,
            source_url=dataset.source.source_url,
            retrieved_at=dataset.source.retrieved_at,
            declared_competitions=tuple(
                sorted(c.value for c in dataset.declared_competitions)
            ),
            declared_seasons=tuple(sorted(dataset.declared_seasons)),
            validation_id=report.id,
            validation_status=report.status.value,
            validator_version=report.validator_version,
            rows_observed=report.rows_observed,
            issue_count=report.issue_count,
            created_at=created_at,
        )

    # ------------------------------------------------------- serialização --

    def as_canonical(self) -> dict[str, Any]:
        """A forma que é hasheada. O que ENTRA e o que FICA DE FORA.

        FICAM DE FORA `created_at` e o id do próprio manifesto. Os dois mudam
        a cada emissão sem que nada do conteúdo mude, e incluí-los faria dois
        manifestos do mesmo conjunto terem impressões diferentes — que é
        exatamente o contrário do que uma impressão serve para fazer.

        ENTRA `validation_id`, e a escolha é deliberada na direção oposta:
        duas validações do mesmo conteúdo pela mesma versão do validador
        produzem manifestos distintos. É o que se quer — o manifesto prova
        qual EXECUÇÃO gerou o resultado, e duas execuções são duas coisas.
        """
        return {
            "dataset": {
                "declared_competitions": list(self.declared_competitions),
                "declared_seasons": list(self.declared_seasons),
                "id": str(self.dataset_id),
                "name": self.dataset_name,
                "version": str(self.dataset_version),
            },
            "files": [f.as_canonical() for f in self.files],
            "schema_version": self.schema_version,
            "source": {
                "license_class": self.license_class,
                "name": self.source_name,
                "retrieved_at": self.retrieved_at.isoformat(),
                "type": self.source_type,
                "url": self.source_url,
            },
            "validation": {
                "id": self.validation_id,
                "issue_count": self.issue_count,
                "rows_observed": self.rows_observed,
                "status": self.validation_status,
                "validator_version": str(self.validator_version),
            },
        }

    def canonical_bytes(self) -> bytes:
        """A serialização determinística, em bytes.

        `sort_keys` porque a ordem de inserção de um dicionário Python é
        estável e a ordem de reconstrução a partir do banco não é.
        `separators` sem espaço porque um espaço a mais muda o hash.
        `ensure_ascii=False` porque nome de fonte tem acento, e escapá-lo
        produziria impressões diferentes conforme a versão do serializador.
        """
        return json.dumps(
            self.as_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @property
    def fingerprint(self) -> ContentHash:
        """SHA-256 da serialização canônica. A impressão do conjunto."""
        return ContentHash(hashlib.sha256(self.canonical_bytes()).hexdigest())

    def describes_same_input_as(self, other: DatasetManifest) -> bool:
        """Se os dois descrevem exatamente a mesma entrada.

        COMPARA OS ARQUIVOS, NÃO O FINGERPRINT. O fingerprint inclui a
        execução de validação, então dois manifestos do mesmo conteúdo
        validado duas vezes têm impressões diferentes e a MESMA entrada. As
        duas perguntas são legítimas e são perguntas diferentes; esta responde
        a segunda.
        """
        meus = tuple(f.sha256.value for f in self.files)
        seus = tuple(f.sha256.value for f in other.files)
        return meus == seus and self.dataset_id == other.dataset_id

    @property
    def total_bytes(self) -> int:
        return sum(f.size_bytes for f in self.files)

    def __str__(self) -> str:
        return (
            f"manifesto {self.dataset_name}@{self.dataset_version} · "
            f"{len(self.files)} arquivo(s) · {self.fingerprint.short}"
        )


def competition_codes(raw: tuple[str, ...]) -> frozenset[CompetitionCode]:
    """Traduz códigos textuais do manifesto de volta para o catálogo fechado.

    RECUSA O DESCONHECIDO em vez de ignorá-lo. Um manifesto que cita uma
    competição fora do catálogo foi escrito por uma versão que conhecia mais
    do que esta, e seguir em frente descartando o que não se entende produz um
    conjunto menor que passa por completo.
    """
    conhecidos = {c.value: c for c in CompetitionCode}
    faltando = [c for c in raw if c not in conhecidos]
    if faltando:
        raise ValidationError(
            f"competição fora do catálogo no manifesto: {faltando}",
            context={"unknown": faltando},
        )
    return frozenset(conhecidos[c] for c in raw)
