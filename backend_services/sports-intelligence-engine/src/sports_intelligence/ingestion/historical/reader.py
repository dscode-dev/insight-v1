"""A leitura de um dataset STAGED em registros com papéis semânticos.

O QUE MUDA EM RELAÇÃO AO PR-02. Lá o arquivo foi lido para VALIDAR — contar
linhas, conferir cabeçalho, medir tipos. Aqui ele é lido para EXTRAIR, e a
diferença é o mapeamento: cada coluna vira um papel semântico declarado, e o
resto do pipeline nunca mais vê o nome da coluna.

EM LOTES, E O LOTE É A UNIDADE DE TUDO (§41, §42). O leitor devolve
`SourceBatch`, não linhas soltas, porque é o lote que permite carregar
candidatos em massa e matar o N+1. Um leitor que devolvesse linha a linha
empurraria todo consumidor de volta para o laço com consulta por linha.

MEMÓRIA CONSTANTE, como no PR-02. O CSV e o JSONL são percorridos linha a
linha; o Parquet é lido por row group. O pico é o do lote, não o do arquivo —
e o tamanho do lote é configuração.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, final

from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.datasets.formats import DatasetFormat
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import DatasetId
from sports_intelligence.domain.shared.provenance import DataProvenance
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.domain.sources.mapping import SourceMappingDefinition
from sports_intelligence.domain.sources.records import (
    DatasetRecordRef,
    SourceBatch,
    SourceRecord,
)
from sports_intelligence.domain.sources.semantics import SemanticRole

#: Quantas linhas o Parquet entrega por vez ao iterador. Independente do
#: tamanho do lote lógico: um controla I/O, o outro controla quantos
#: registros a resolução processa junto.
_PARQUET_CHUNK: Final[int] = 8_192


@final
@dataclass(frozen=True, slots=True)
class ReadContext:
    """O que todo registro de um arquivo herda, e que não vem da linha."""

    dataset_id: DatasetId
    dataset_version: DatasetVersion
    file_id: str
    manifest_fingerprint: ContentHash
    provenance: DataProvenance
    mapping: SourceMappingDefinition


@final
class SourceReader:
    """Lê um arquivo local e devolve lotes de registros com papéis.

    RECEBE UM CAMINHO LOCAL, e não o arquivo bruto. A materialização do
    objeto do arquivo bruto para um temporário é do chamador, pelo mesmo
    motivo do PR-02: o Parquet exige acesso aleatório, e o leitor não deveria
    conhecer o object store para dizer isso.
    """

    def __init__(self, *, batch_size: int) -> None:
        if batch_size < 1:
            raise ValidationError(f"tamanho de lote {batch_size} inválido")
        self._batch_size = batch_size

    def read(
        self, path: Path, *, file_format: DatasetFormat, context: ReadContext
    ) -> Iterator[SourceBatch]:
        linhas = self._linhas(path, file_format)
        acumulado: list[SourceRecord] = []
        indice = 0
        for numero, bruta in linhas:
            acumulado.append(self._registro(bruta, numero, context))
            if len(acumulado) >= self._batch_size:
                yield SourceBatch(records=tuple(acumulado), batch_index=indice)
                acumulado = []
                indice += 1
        if acumulado:
            yield SourceBatch(records=tuple(acumulado), batch_index=indice)

    def _registro(
        self, bruta: dict[str, Any], numero: int, context: ReadContext
    ) -> SourceRecord:
        """Aplica o mapeamento: coluna → papel semântico → valor tipado.

        COLUNAS NÃO MAPEADAS SÃO IGNORADAS, e é deliberado: um arquivo com
        cinquenta colunas das quais o mapeamento declara doze produz doze
        papéis. Carregar as outras trinta e oito «por precaução» encheria a
        memória com texto que ninguém consulta.
        """
        valores = {}
        for campo in context.mapping.fields:
            cru = bruta.get(campo.column)
            valores[campo.role] = campo.extract(
                None if cru is None else (cru if isinstance(cru, str) else str(cru))
            )
        return SourceRecord(
            ref=DatasetRecordRef(
                dataset_id=context.dataset_id,
                file_id=context.file_id,
                record_number=numero,
            ),
            dataset_version=context.dataset_version,
            provider_id=context.mapping.provider_id,
            values=valores,
            provenance=context.provenance,
            manifest_fingerprint=context.manifest_fingerprint,
        )

    def _linhas(
        self, path: Path, file_format: DatasetFormat
    ) -> Iterator[tuple[int, dict[str, Any]]]:
        if file_format is DatasetFormat.CSV:
            return self._csv(path)
        if file_format is DatasetFormat.JSONL:
            return self._jsonl(path)
        return self._parquet(path)

    @staticmethod
    def _csv(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
        """O número da linha é o do ARQUIVO, contando o cabeçalho como 1.

        É assim que um editor de texto conta, e é lá que quem investiga uma
        decisão vai olhar. Um índice de registro começando em zero obrigaria
        toda investigação a somar dois.
        """
        with path.open("r", encoding="utf-8-sig", newline="") as fonte:
            leitor = csv.DictReader(fonte)
            for numero, linha in enumerate(leitor, start=2):
                yield numero, dict(linha)

    @staticmethod
    def _jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
        with path.open("r", encoding="utf-8-sig") as fonte:
            for numero, bruta in enumerate(fonte, start=1):
                texto = bruta.strip()
                if not texto:
                    continue
                try:
                    objeto = json.loads(texto)
                except json.JSONDecodeError:
                    # LINHA MALFORMADA É PULADA, não derruba a leitura. O
                    # PR-02 já a relatou na validação; parar aqui perderia as
                    # outras noventa e nove mil.
                    continue
                if isinstance(objeto, dict):
                    yield numero, objeto

    @staticmethod
    def _parquet(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
        """Por row group, e nunca `read_table` inteiro.

        `iter_batches` é o que mantém o pico de memória no tamanho do bloco.
        Um `read_table(path).to_pylist()` seria uma linha mais curta e
        materializaria o arquivo inteiro — o defeito que o PR-02 mediu e que
        este leitor não pode reintroduzir.
        """
        import pyarrow.parquet as pq

        arquivo = pq.ParquetFile(path)
        numero = 1
        for bloco in arquivo.iter_batches(batch_size=_PARQUET_CHUNK):
            for linha in bloco.to_pylist():
                yield numero, linha
                numero += 1


def required_roles_present(
    mapping: SourceMappingDefinition, roles: frozenset[SemanticRole]
) -> tuple[SemanticRole, ...]:
    """Os papéis exigidos que o mapeamento NÃO declara.

    Chamado antes de a execução começar. Descobrir que falta o nome do
    visitante depois de processar cem mil linhas custa a execução inteira;
    descobrir antes custa uma mensagem.
    """
    return tuple(sorted(roles - mapping.roles, key=lambda r: r.value))
