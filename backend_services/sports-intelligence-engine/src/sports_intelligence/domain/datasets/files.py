"""Um arquivo dentro de um dataset, e o estado que impede um STAGED falso.

`FileStagingState` É O CORAÇÃO DESTE MÓDULO, e ele existe por causa de uma
verdade operacional simples: o object store e o PostgreSQL não commitam
juntos. Não existe transação distribuída entre os dois, e qualquer desenho que
finja o contrário produz, mais cedo ou mais tarde, um destes dois estados:

    linha no banco, bytes ausentes    →  o dataset "tem" um arquivo vazio
    bytes no store, linha ausente     →  bytes órfãos, invisíveis ao registro

O primeiro é o perigoso. Um dataset com uma linha de arquivo sem bytes passa
por qualquer contagem — `len(files) == 3` — e chega a `STAGED` afirmando que
três arquivos foram preservados quando só dois foram. O relatório fecha, o
manifesto lista os três, e a falha só aparece no PR-03, ao tentar ler o
terceiro.

A saída é não deixar a contagem mentir: um arquivo em `PENDING` NÃO CONTA. Ele
não entra em validação, não entra no manifesto e não deixa o dataset sair de
`UPLOADING`. O estado é a diferença entre "prometemos guardar" e "guardamos".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Self, final

from sports_intelligence.domain.datasets.content import ContentHash, build_object_key
from sports_intelligence.domain.datasets.formats import (
    DatasetFormat,
    sanitize_filename,
)
from sports_intelligence.domain.shared.errors import ConflictError, ValidationError
from sports_intelligence.domain.shared.identity import (
    ROOT_NAMESPACE,
    DatasetId,
    EntityId,
)
from sports_intelligence.domain.shared.provenance import DataProvenance
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion


@final
@dataclass(frozen=True, slots=True)
class DatasetFileId(EntityId):
    """Identidade do arquivo dentro do registro.

    DERIVADA DE (dataset, versão, hash), e não sorteada. É o que torna o
    reenvio dos mesmos bytes reconhecível antes de qualquer consulta: a
    segunda tentativa calcula o mesmo id, encontra a mesma linha, e retoma de
    onde parou em vez de criar um segundo registro do mesmo arquivo.
    """

    NAMESPACE: ClassVar[uuid.UUID] = uuid.uuid5(ROOT_NAMESPACE, "dataset_file")

    @classmethod
    def for_content(
        cls, *, dataset_id: DatasetId, version: DatasetVersion, content_hash: ContentHash
    ) -> Self:
        return cls.derive(str(dataset_id), str(version), content_hash.value)


class FileStagingState(StrEnum):
    """Onde os bytes deste arquivo estão de fato."""

    #: Metadados registrados, bytes ainda não confirmados no arquivo bruto.
    #: NÃO CONTA para nada: nem validação, nem manifesto, nem staging.
    PENDING = "PENDING"
    #: Bytes gravados e conferidos: tamanho e hash confirmados na leitura.
    STORED = "STORED"
    #: A gravação falhou de forma que não se resolve sozinha. Fica registrado
    #: em vez de sumir — um arquivo que desaparece do registro depois de
    #: falhar leva junto a informação de que alguém tentou enviá-lo.
    FAILED = "FAILED"

    @property
    def counts_as_present(self) -> bool:
        return self is FileStagingState.STORED


@final
@dataclass(frozen=True, slots=True)
class DatasetFile:
    """Um arquivo recebido: o que ele é, onde está e se está mesmo lá.

    IMUTÁVEL, COMO TUDO QUE DESCREVE EVIDÊNCIA. Mudanças produzem outra
    instância; o que muda de verdade — o estado de gravação e a contagem de
    linhas descoberta na inspeção — passa por métodos que dizem o nome do que
    fazem.
    """

    id: DatasetFileId
    dataset_id: DatasetId
    dataset_version: DatasetVersion
    original_filename: str
    safe_filename: str
    media_type: str
    format: DatasetFormat
    content_hash: ContentHash
    size_bytes: int
    object_key: str
    staging_state: FileStagingState
    uploaded_at: Instant
    uploaded_by: str
    provenance: DataProvenance
    #: Descobertos na INSPEÇÃO, não declarados. Ausentes até a validação
    #: rodar — e ausente aqui é `None`, nunca 0: um arquivo cujo número de
    #: linhas ainda não foi medido não é um arquivo de zero linhas.
    row_count: int | None = None
    column_count: int | None = None

    def __post_init__(self) -> None:
        if self.size_bytes < 0:
            raise ValidationError(f"tamanho negativo: {self.size_bytes}")
        if not self.uploaded_by.strip():
            raise ValidationError("uploaded_by vazio: toda operação administrativa tem autor")
        if not self.object_key.startswith("datasets/raw/"):
            raise ValidationError(
                f"object_key {self.object_key!r} fora do prefixo do arquivo bruto"
            )
        for nome, valor in (("row_count", self.row_count), ("column_count", self.column_count)):
            if valor is not None and valor < 0:
                raise ValidationError(f"{nome} negativo: {valor}")

    @classmethod
    def intent(
        cls,
        *,
        dataset_id: DatasetId,
        version: DatasetVersion,
        original_filename: str,
        file_format: DatasetFormat,
        content_hash: ContentHash,
        size_bytes: int,
        uploaded_at: Instant,
        uploaded_by: str,
        provenance: DataProvenance,
    ) -> Self:
        """A INTENÇÃO de gravar: metadados prontos, bytes ainda não.

        A primeira das três fases do ADR-0017. O que ela produz é uma linha
        que já sabe onde os bytes vão morar — porque a chave vem do hash, que
        já foi calculado durante a leitura — e que declara, no próprio estado,
        que eles ainda não estão lá.

        O nome é sanitizado AQUI e o original é preservado ao lado: o limpo
        decide o armazenamento, o original é o que o operador reconhece.
        """
        limpo = sanitize_filename(original_filename)
        return cls(
            id=DatasetFileId.for_content(
                dataset_id=dataset_id, version=version, content_hash=content_hash
            ),
            dataset_id=dataset_id,
            dataset_version=version,
            original_filename=original_filename[:512],
            safe_filename=limpo,
            media_type=file_format.media_type,
            format=file_format,
            content_hash=content_hash,
            size_bytes=size_bytes,
            object_key=build_object_key(
                dataset_id=dataset_id,
                version=version,
                content_hash=content_hash,
                safe_filename=limpo,
            ),
            staging_state=FileStagingState.PENDING,
            uploaded_at=uploaded_at,
            uploaded_by=uploaded_by,
            provenance=provenance,
        )

    def confirm_stored(self) -> Self:
        """Os bytes estão no arquivo bruto, conferidos. Terceira fase."""
        if self.staging_state is FileStagingState.STORED:
            # Não é erro: é o retry chegando depois de a gravação ter dado
            # certo e a confirmação ter se perdido. Tratar isso como conflito
            # transformaria a convergência normal em alarme.
            return self
        return self._with_state(FileStagingState.STORED)

    def mark_failed(self) -> Self:
        return self._with_state(FileStagingState.FAILED)

    def with_inspection(self, *, row_count: int, column_count: int) -> Self:
        """O que a inspeção mediu. Só faz sentido em arquivo gravado."""
        if not self.staging_state.counts_as_present:
            raise ConflictError(
                f"inspeção de arquivo em {self.staging_state}: "
                "não há bytes confirmados para medir",
                context={"file_id": str(self.id)},
            )
        return type(self)(
            id=self.id,
            dataset_id=self.dataset_id,
            dataset_version=self.dataset_version,
            original_filename=self.original_filename,
            safe_filename=self.safe_filename,
            media_type=self.media_type,
            format=self.format,
            content_hash=self.content_hash,
            size_bytes=self.size_bytes,
            object_key=self.object_key,
            staging_state=self.staging_state,
            uploaded_at=self.uploaded_at,
            uploaded_by=self.uploaded_by,
            provenance=self.provenance,
            row_count=row_count,
            column_count=column_count,
        )

    def _with_state(self, state: FileStagingState) -> Self:
        return type(self)(
            id=self.id,
            dataset_id=self.dataset_id,
            dataset_version=self.dataset_version,
            original_filename=self.original_filename,
            safe_filename=self.safe_filename,
            media_type=self.media_type,
            format=self.format,
            content_hash=self.content_hash,
            size_bytes=self.size_bytes,
            object_key=self.object_key,
            staging_state=state,
            uploaded_at=self.uploaded_at,
            uploaded_by=self.uploaded_by,
            provenance=self.provenance,
            row_count=self.row_count,
            column_count=self.column_count,
        )

    @property
    def is_empty(self) -> bool:
        return self.size_bytes == 0

    def __str__(self) -> str:
        return f"{self.safe_filename} [{self.format}] {self.content_hash.short} {self.size_bytes}B"


def assert_no_duplicate_content(files: tuple[DatasetFile, ...]) -> None:
    """Nenhum conteúdo repetido dentro da mesma versão.

    O MESMO ARQUIVO COM DOIS NOMES é o caso que isto pega, e ele é comum na
    operação manual: `E0.csv` e `premier_2019.csv` baixados do mesmo lugar em
    dias diferentes. Sem esta guarda, cada linha do arquivo entraria duas
    vezes no que vier depois — e nada falharia, o histórico só ficaria com o
    dobro dos jogos daquela temporada.

    Em produção quem impõe isto é uma constraint UNIQUE, não esta função:
    lógica Python não protege contra dois processos concorrentes. Aqui é a
    mesma regra dita onde ela pode ser testada sem banco.
    """
    vistos: dict[str, DatasetFile] = {}
    for arquivo in files:
        anterior = vistos.get(arquivo.content_hash.value)
        if anterior is not None:
            raise ConflictError(
                f"conteúdo duplicado na versão: {arquivo.safe_filename!r} e "
                f"{anterior.safe_filename!r} têm o mesmo SHA-256 "
                f"({arquivo.content_hash.short})",
                context={"sha256": arquivo.content_hash.value},
            )
        vistos[arquivo.content_hash.value] = arquivo
