"""A validação estrutural de um dataset: o que ela verifica e o que não.

O QUE ELA VERIFICA. Que os bytes estão lá; que o arquivo é do formato que diz
ser; que o texto decodifica; que o cabeçalho existe e não tem coluna
duplicada; que as linhas têm a forma do cabeçalho; que as colunas obrigatórias
declaradas aparecem; e que nada disso estoura os limites configurados.

O QUE ELA PROPOSITALMENTE NÃO VERIFICA — e a lista importa tanto quanto a
primeira:

    que `HomeTeam` é um time            resolução de identidade, PR-03
    que `2019-08-09` é uma data válida  exige fuso, que o arquivo não declara
    que o placar é plausível            semântica futebolística, PR-03+
    que duas fontes concordam           fusão, PR-03
    que não falta a rodada 12           completude do domínio, não do arquivo

A tentação de acrescentar "só uma" dessas é constante, e cada uma delas
arrastaria para cá uma decisão que precisa de confiança de identidade,
conflito e fila de revisão. Um validador estrutural que começa a entender
futebol vira o pipeline de fusão sem nenhuma das garantias dele.

MATERIALIZAÇÃO EM DISCO, E POR QUÊ. O Parquet exige acesso aleatório: o
schema está no rodapé, e não há como lê-lo a partir de um stream sequencial.
Então cada arquivo é baixado do arquivo bruto para um temporário local antes
da inspeção. O custo é disco e uma leitura extra; o ganho é que o pico de
MEMÓRIA continua sendo o de um bloco, e é a memória que derruba o processo.
O temporário é removido no `finally`, inclusive quando a inspeção levanta.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import final

from sports_intelligence.domain.datasets.files import DatasetFile
from sports_intelligence.domain.datasets.models import Dataset
from sports_intelligence.domain.datasets.schema import (
    DatasetSchemaContract,
    DatasetSchemaObservation,
)
from sports_intelligence.domain.datasets.validation import (
    DatasetValidationIssue,
    DatasetValidationReport,
    IssueCode,
    IssueCollector,
    IssueSeverity,
)
from sports_intelligence.ingestion.validation.detection import PROBE_BYTES, probe
from sports_intelligence.ingestion.validation.inspectors import Inspection, inspect
from sports_intelligence.ports.clock import ClockPort
from sports_intelligence.ports.raw_dataset_archive import RawDatasetArchivePort


@final
@dataclass(frozen=True, slots=True)
class ValidationLimits:
    """Os tetos, num objeto só.

    NÚMEROS MÁGICOS ESPALHADOS SÃO POLÍTICAS QUE DIVERGEM. `max_rows` escrito
    em três inspetores vira três limites diferentes na primeira vez que
    alguém ajusta um. Aqui eles vêm de settings e chegam por injeção.
    """

    max_file_size_bytes: int
    max_rows_per_file: int
    max_issues: int

    def __post_init__(self) -> None:
        for nome in ("max_file_size_bytes", "max_rows_per_file", "max_issues"):
            if getattr(self, nome) < 1:
                raise ValueError(f"{nome} precisa ser positivo")


@final
class StructuralValidator:
    """Valida um dataset inteiro e produz um relatório imutável."""

    def __init__(
        self,
        *,
        archive: RawDatasetArchivePort,
        clock: ClockPort,
        limits: ValidationLimits,
    ) -> None:
        self._archive = archive
        self._clock = clock
        self._limits = limits

    async def validate(
        self, dataset: Dataset, *, contract: DatasetSchemaContract | None = None
    ) -> DatasetValidationReport:
        """Valida os arquivos COM BYTES CONFIRMADOS e nada além deles.

        `stored_files` E NÃO `files`: um arquivo em `PENDING` é uma promessa,
        e validar uma promessa produziria um relatório limpo sobre um
        conteúdo que ninguém leu — que é a forma exata do `STAGED` falso que
        este PR existe para impedir.
        """
        comeco = self._clock.now()
        coletor = IssueCollector(max_issues=self._limits.max_issues)
        observacoes: list[DatasetSchemaObservation] = []
        linhas_totais = 0
        inspecionados = 0

        if dataset.needs_license_review:
            coletor.add(
                DatasetValidationIssue.of(
                    IssueCode.LICENSE_REVIEW_REQUIRED,
                    f"licença {dataset.source.license_class} — armazenar e validar é "
                    "legítimo; promover a uso comercial exige decisão humana explícita",
                )
            )

        vistos: dict[str, DatasetFile] = {}
        for arquivo in dataset.stored_files:
            anterior = vistos.get(arquivo.content_hash.value)
            if anterior is not None:
                coletor.add(
                    DatasetValidationIssue.of(
                        IssueCode.DUPLICATE_CONTENT,
                        f"{arquivo.safe_filename!r} tem os mesmos bytes de "
                        f"{anterior.safe_filename!r} ({arquivo.content_hash.short}) — "
                        "cada linha entraria duas vezes no que vier depois",
                        file_id=str(arquivo.id),
                    )
                )
                continue
            vistos[arquivo.content_hash.value] = arquivo

            inspecionados += 1
            resultado = await self._validar_arquivo(arquivo, contract=contract)
            for issue in resultado.issues:
                coletor.add(issue)
            if resultado.observation is not None:
                observacoes.append(resultado.observation)
                linhas_totais += resultado.observation.row_count

        for issue in _divergencia_entre_arquivos(observacoes):
            coletor.add(issue)

        return DatasetValidationReport.build(
            dataset_id=dataset.id,
            dataset_version=dataset.version,
            started_at=comeco,
            generated_at=self._clock.now(),
            files_checked=inspecionados,
            rows_observed=linhas_totais,
            issues=coletor.issues,
            schema_observations=tuple(observacoes),
            issue_count=coletor.total,
            truncated=coletor.truncated,
        )

    async def _validar_arquivo(
        self, arquivo: DatasetFile, *, contract: DatasetSchemaContract | None
    ) -> Inspection:
        """Um arquivo: presença, tamanho, formato, encoding, e só então parser.

        A ORDEM É A DEFESA. Cada checagem barata que falha impede a próxima,
        mais cara e mais perigosa, de rodar. O parser — que é a única peça que
        aloca com base em bytes arbitrários — é o último a ver o arquivo.
        """
        file_id = str(arquivo.id)

        if arquivo.size_bytes == 0:
            return Inspection(
                observation=None,
                issues=(
                    DatasetValidationIssue.of(
                        IssueCode.EMPTY_FILE, "arquivo com zero bytes", file_id=file_id
                    ),
                ),
            )
        if arquivo.size_bytes > self._limits.max_file_size_bytes:
            return Inspection(
                observation=None,
                issues=(
                    DatasetValidationIssue.of(
                        IssueCode.SIZE_LIMIT_EXCEEDED,
                        f"{arquivo.size_bytes} bytes acima do limite de "
                        f"{self._limits.max_file_size_bytes}",
                        file_id=file_id,
                    ),
                ),
            )
        if not await self._archive.verify(arquivo):
            # O REGISTRO DIZ QUE OS BYTES ESTÃO LÁ E ELES NÃO ESTÃO. É o
            # estado que o protocolo de três fases existe para tornar
            # detectável, e detectá-lo aqui é o que impede o dataset de
            # subir afirmando ter preservado o que perdeu.
            return Inspection(
                observation=None,
                issues=(
                    DatasetValidationIssue.of(
                        IssueCode.OBJECT_MISSING,
                        f"o registro aponta {arquivo.object_key} e o arquivo bruto não "
                        "tem esse objeto com o tamanho esperado",
                        file_id=file_id,
                    ),
                ),
            )

        caminho: Path | None = None
        try:
            caminho, cabeca = await self._materializar(arquivo)
            exame = probe(
                cabeca, declared=arquivo.format, size_bytes=arquivo.size_bytes
            )
            if exame.compression is not None:
                return Inspection(
                    observation=None,
                    issues=(
                        DatasetValidationIssue.of(
                            IssueCode.COMPRESSED_FILE_UNSUPPORTED,
                            f"o conteúdo é {exame.compression} e a V1 não aceita arquivo "
                            "compactado — descompacte na origem e reenvie",
                            file_id=file_id,
                        ),
                    ),
                )
            if exame.format_conflicts:
                return Inspection(
                    observation=None,
                    issues=(
                        DatasetValidationIssue.of(
                            IssueCode.FORMAT_MISMATCH,
                            f"declarado como {arquivo.format} e o conteúdo é "
                            f"{exame.looks_like} — a extensão não prova formato",
                            file_id=file_id,
                        ),
                    ),
                )
            if exame.encoding_error is not None:
                return Inspection(
                    observation=None,
                    issues=(
                        DatasetValidationIssue.of(
                            IssueCode.UNSUPPORTED_ENCODING,
                            exame.encoding_error,
                            file_id=file_id,
                        ),
                    ),
                )

            resultado = inspect(
                caminho,
                file_id=file_id,
                file_format=arquivo.format,
                max_rows=self._limits.max_rows_per_file,
            )
        finally:
            if caminho is not None:
                caminho.unlink(missing_ok=True)

        if contract is None or contract.is_empty or resultado.observation is None:
            return resultado
        return Inspection(
            observation=resultado.observation,
            issues=(
                *resultado.issues,
                *_issues_de_contrato(contract, resultado.observation, file_id),
            ),
        )

    async def _materializar(self, arquivo: DatasetFile) -> tuple[Path, bytes]:
        """Baixa o objeto para um temporário local e devolve a cabeça lida.

        A CABEÇA VEM DESTA MESMA PASSAGEM, não de uma leitura extra: os
        primeiros bytes já estão passando, e pedi-los de novo ao object store
        seria uma ida à rede para obter o que já se tem em mãos.
        """
        with tempfile.NamedTemporaryFile(
            prefix="sie-validate-", suffix=arquivo.format.canonical_extension, delete=False
        ) as destino:
            caminho = Path(destino.name)
            cabeca = b""
            async for bloco in self._archive.open(arquivo):
                if len(cabeca) < PROBE_BYTES:
                    cabeca = (cabeca + bloco)[:PROBE_BYTES]
                destino.write(bloco)
        return caminho, cabeca


def _issues_de_contrato(
    contract: DatasetSchemaContract, observado: DatasetSchemaObservation, file_id: str
) -> list[DatasetValidationIssue]:
    """O confronto entre o que se esperava e o que veio."""
    issues: list[DatasetValidationIssue] = []
    faltando = contract.missing_required(observado)
    issues.extend(
        DatasetValidationIssue.of(
            IssueCode.MISSING_REQUIRED_COLUMN,
            f"a coluna obrigatória {coluna!r} não está no arquivo",
            file_id=file_id,
            location=f"coluna {coluna}",
        )
        for coluna in faltando
    )
    inesperadas = contract.unexpected(observado)
    if inesperadas:
        issues.append(
            DatasetValidationIssue.of(
                IssueCode.UNEXPECTED_COLUMN,
                f"colunas fora do contrato: {', '.join(inesperadas[:10])}"
                + (f" (e mais {len(inesperadas) - 10})" if len(inesperadas) > 10 else "")
                + " — fonte pública acrescenta coluna sem avisar, e isso não recusa o arquivo",
                file_id=file_id,
                occurrences=len(inesperadas),
            )
        )
    for coluna, declarado, encontrado in contract.type_mismatches(observado):
        issues.append(
            DatasetValidationIssue.of(
                IssueCode.TYPE_MISMATCH,
                f"a coluna {coluna!r} foi declarada {declarado} e veio {encontrado}",
                file_id=file_id,
                location=f"coluna {coluna}",
                # Divergência de tipo numa coluna OBRIGATÓRIA é outra coisa:
                # o consumidor a lerá com o tipo declarado e vai quebrar.
                severity=(
                    IssueSeverity.ERROR
                    if coluna in contract.required_columns
                    else IssueSeverity.WARNING
                ),
            )
        )
    return issues


def _divergencia_entre_arquivos(
    observacoes: list[DatasetSchemaObservation],
) -> list[DatasetValidationIssue]:
    """Arquivos do mesmo dataset com cabeçalhos diferentes.

    AVISO E NÃO IMPEDITIVO, porque o caso é legítimo com frequência: um
    dataset de vinte temporadas costuma ter a temporada em que a fonte passou
    a publicar xG com uma coluna a mais. O que não pode é isso passar
    despercebido — quem processar o conjunto como se fosse homogêneo vai
    encontrar a coluna ausente em dezenove arquivos.

    O ARQUIVO DE REFERÊNCIA É O DE MAIS COLUNAS, e não o primeiro: com o
    primeiro, um dataset ordenado da temporada mais antiga para a mais nova
    acusaria divergência em todos os outros dezenove.
    """
    if len(observacoes) < 2:
        return []
    referencia = max(observacoes, key=lambda o: o.column_count)
    esperadas = {n.strip().lower() for n in referencia.column_names}
    issues: list[DatasetValidationIssue] = []
    for observacao in observacoes:
        if observacao.file_id == referencia.file_id:
            continue
        presentes = {n.strip().lower() for n in observacao.column_names}
        faltando = esperadas - presentes
        extras = presentes - esperadas
        if not faltando and not extras:
            continue
        partes: list[str] = []
        if faltando:
            partes.append(f"faltam {', '.join(sorted(faltando)[:5])}")
        if extras:
            partes.append(f"tem a mais {', '.join(sorted(extras)[:5])}")
        issues.append(
            DatasetValidationIssue.of(
                IssueCode.SCHEMA_DIVERGENCE_BETWEEN_FILES,
                f"cabeçalho diferente do arquivo com mais colunas: {'; '.join(partes)}",
                file_id=observacao.file_id,
            )
        )
    return issues
