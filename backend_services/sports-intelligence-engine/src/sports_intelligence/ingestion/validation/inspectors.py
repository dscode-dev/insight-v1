"""A inspeção de cada formato — em streaming, e sem confiar no arquivo.

TRÊS INSPETORES, UMA SAÍDA. Cada um devolve o mesmo par: o schema observado e
as issues encontradas. É o que permite ao relatório de um CSV e ao de um
Parquet serem lidos lado a lado, que é exatamente quando alguém os compara.

DIVISÃO DE TRABALHO ENTRE AS BIBLIOTECAS, e ela não é arbitrária — cada uma
responde a uma pergunta diferente sobre o mesmo arquivo:

    PyArrow, no Parquet     "qual é o schema?"
        O rodapé já traz nomes, tipos, nulabilidade e contagem de linhas.
        Lê-los custa alguns KB; um Parquet de 4 GB é inspecionado sem tocar
        nos dados. É por isso que ele é o formato preferencial interno.

    Polars, nos tipos       "de que tipo é cada coluna?"
        Inferência em Rust, sobre uma amostra, sem trazer o arquivo para a
        RAM. Ele lida com campo entre aspas contendo o delimitador, notação
        científica, data com e sem fuso — casos que uma heurística caseira
        erra em silêncio, e o erro vai parar no relatório que o operador
        compara com o contrato dele.

    `csv` e `json` da       "ONDE está o defeito?"
    biblioteca padrão
        Uma issue que diz "linha 4.312 tem 9 campos e o cabeçalho tem 10"
        manda alguém ao lugar certo. "Erro de parsing" manda alguém abrir
        cem mil linhas. O Polars resolve linha irregular sozinho — truncando
        ou preenchendo — e resolver sozinho é exatamente o problema: o dado
        da coluna que sobrou some e o dataframe fica com a forma certa.

UMA FONTE DE TIPO SÓ. Os tipos vêm do Polars ou do Arrow, nunca de heurística
nossa. Quando eles não conseguem ler o arquivo, o tipo é `UNKNOWN` — que é
honesto — e não um palpite que o contrato de schema compararia como se fosse
medição.

Pandas não entra. Ele materializa o dataframe inteiro por construção, que é a
única coisa que este caminho não pode fazer.
"""

from __future__ import annotations

import csv
import json
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, final

from sports_intelligence.domain.datasets.formats import DatasetFormat
from sports_intelligence.domain.datasets.schema import (
    MAX_COLUMNS_DESCRIBED,
    MAX_SAMPLES_PER_COLUMN,
    ColumnObservation,
    DatasetSchemaObservation,
    DetectedType,
)
from sports_intelligence.domain.datasets.validation import (
    DatasetValidationIssue,
    IssueCode,
    IssueSeverity,
)

#: Quantas linhas alimentam a inferência de tipo do Polars.
_LINHAS_DE_AMOSTRA: Final[int] = 200

#: Profundidade máxima de um objeto JSON. O parser da biblioteca padrão é
#: recursivo, e um documento com milhares de níveis estoura a pilha do
#: interpretador — que não é exceção tratável, é o processo morrendo.
MAX_JSON_DEPTH: Final[int] = 32

#: Tamanho máximo de uma linha de texto. Um arquivo sem quebras de linha é
#: uma linha só do tamanho do arquivo, e lê-la anula o streaming inteiro.
MAX_LINE_BYTES: Final[int] = 8 * 1024 * 1024

#: Teto de linhas defeituosas relatadas individualmente. Passando disso elas
#: viram uma issue agregada — cem mil issues idênticas não informam mais que
#: vinte mais a contagem.
_MAX_LINHAS_RELATADAS: Final[int] = 20

#: Acima desta fração de linhas defeituosas o defeito deixa de ser local: o
#: arquivo provavelmente foi lido com o delimitador errado, e nesse caso ele
#: não é o que diz ser.
_FRACAO_QUE_TORNA_IMPEDITIVO: Final[float] = 0.25


@final
@dataclass(frozen=True, slots=True)
class Inspection:
    """O resultado de olhar um arquivo."""

    observation: DatasetSchemaObservation | None
    issues: tuple[DatasetValidationIssue, ...]

    @property
    def rows(self) -> int:
        return self.observation.row_count if self.observation else 0


def inspect(
    path: Path, *, file_id: str, file_format: DatasetFormat, max_rows: int
) -> Inspection:
    """Despacha para o inspetor do formato."""
    if file_format is DatasetFormat.PARQUET:
        return inspect_parquet(path, file_id=file_id, max_rows=max_rows)
    if file_format is DatasetFormat.CSV:
        return inspect_csv(path, file_id=file_id, max_rows=max_rows)
    return inspect_jsonl(path, file_id=file_id, max_rows=max_rows)


# ------------------------------------------------------------------ parquet --


def inspect_parquet(path: Path, *, file_id: str, max_rows: int) -> Inspection:
    """Lê o rodapé do Parquet. Não toca nos dados.

    Sem amostras de valores, e é consequência da mesma escolha: pegá-las
    exigiria ler um row group, ordens de grandeza mais caro. O tipo declarado
    do Parquet já é confiável, ao contrário do de um CSV, onde a amostra é a
    única informação que existe.
    """
    import pyarrow.parquet as pq

    try:
        arquivo = pq.ParquetFile(path)
        esquema = arquivo.schema_arrow
        linhas = int(arquivo.metadata.num_rows)
    except Exception as erro:  # noqa: BLE001 — parser é fronteira não confiável
        return _falha(IssueCode.INVALID_FORMAT, file_id, "não foi possível ler como Parquet", erro)

    issues: list[DatasetValidationIssue] = []
    if linhas > max_rows:
        issues.append(
            DatasetValidationIssue.of(
                IssueCode.ROW_LIMIT_EXCEEDED,
                f"{linhas} linhas excedem o limite configurado de {max_rows}",
                file_id=file_id,
            )
        )

    colunas = tuple(
        ColumnObservation(
            name=campo.name,
            detected_type=_tipo_arrow(str(campo.type)),
            nullable=campo.nullable,
        )
        for campo in list(esquema)[:MAX_COLUMNS_DESCRIBED]
    )
    observacao = DatasetSchemaObservation(
        file_id=file_id,
        columns=colunas,
        row_count=linhas,
        truncated_columns=len(esquema) > MAX_COLUMNS_DESCRIBED,
    )
    issues.extend(_issues_de_colunas(observacao, file_id))
    if linhas == 0:
        issues.append(
            DatasetValidationIssue.of(
                IssueCode.NO_ROWS, "Parquet válido e sem nenhuma linha", file_id=file_id
            )
        )
    return Inspection(observation=observacao, issues=tuple(issues))


# ---------------------------------------------------------------------- csv --


def inspect_csv(path: Path, *, file_id: str, max_rows: int) -> Inspection:
    """Duas passagens sobre o mesmo arquivo, cada uma respondendo uma coisa.

    A PRIMEIRA é a varredura estrutural: cabeçalho, contagem exata de linhas
    e a posição de cada linha que não bate com o cabeçalho.

    A SEGUNDA é o Polars, sobre uma amostra, só para os tipos. Ela é opcional
    por construção: se o arquivo for irregular demais para o Polars, os tipos
    saem `UNKNOWN` e a inspeção continua — porque o que interessa nesse caso
    já foi apurado na primeira passagem.
    """
    varredura = _varrer_csv(path, file_id=file_id, max_rows=max_rows)
    if varredura.header is None:
        return Inspection(observation=None, issues=varredura.issues)

    issues = list(varredura.issues)
    colunas = _tipos_de_csv(path, varredura.header)
    observacao = DatasetSchemaObservation(
        file_id=file_id,
        columns=colunas,
        row_count=varredura.rows,
        truncated_columns=len(varredura.header) > MAX_COLUMNS_DESCRIBED,
    )
    issues.extend(_issues_de_colunas(observacao, file_id))
    if varredura.rows == 0:
        issues.append(
            DatasetValidationIssue.of(
                IssueCode.NO_ROWS,
                "o arquivo tem cabeçalho e nenhuma linha de dado",
                file_id=file_id,
            )
        )
    return Inspection(observation=observacao, issues=tuple(issues))


@final
@dataclass(frozen=True, slots=True)
class _Varredura:
    header: list[str] | None
    rows: int
    defective: int
    issues: tuple[DatasetValidationIssue, ...]


def _varrer_csv(path: Path, *, file_id: str, max_rows: int) -> _Varredura:
    issues: list[DatasetValidationIssue] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fonte:
            leitor = csv.reader(_linhas_limitadas(fonte, file_id, issues))
            try:
                cabecalho = next(leitor)
            except StopIteration:
                return _Varredura(
                    header=None,
                    rows=0,
                    defective=0,
                    issues=(
                        DatasetValidationIssue.of(
                            IssueCode.MISSING_HEADER,
                            "arquivo sem nenhuma linha: não há cabeçalho",
                            file_id=file_id,
                        ),
                    ),
                )

            esperado = len(cabecalho)
            linhas = 0
            irregulares = 0
            relatadas = 0
            for numero, linha in enumerate(leitor, start=2):
                if not linha:
                    continue
                linhas += 1
                if linhas > max_rows:
                    issues.append(
                        DatasetValidationIssue.of(
                            IssueCode.ROW_LIMIT_EXCEEDED,
                            f"mais de {max_rows} linhas — leitura interrompida",
                            file_id=file_id,
                        )
                    )
                    break
                if len(linha) != esperado:
                    irregulares += 1
                    if relatadas < _MAX_LINHAS_RELATADAS:
                        relatadas += 1
                        issues.append(
                            DatasetValidationIssue.of(
                                IssueCode.INCONSISTENT_FIELD_COUNT,
                                f"a linha tem {len(linha)} campos e o cabeçalho tem "
                                f"{esperado}",
                                file_id=file_id,
                                location=f"linha {numero}",
                            )
                        )
    except UnicodeDecodeError as erro:
        return _Varredura(
            header=None,
            rows=0,
            defective=0,
            issues=(_issue_encoding(file_id, erro),),
        )
    except (OSError, csv.Error) as erro:
        return _Varredura(
            header=None,
            rows=0,
            defective=0,
            issues=_falha(IssueCode.UNREADABLE_FILE, file_id, "falha ao ler o CSV", erro).issues,
        )

    issues.extend(
        _issues_agregadas(
            file_id=file_id,
            code=IssueCode.INCONSISTENT_FIELD_COUNT,
            defeituosas=irregulares,
            total=linhas,
            resumo="linha(s) com número de campos diferente do cabeçalho",
            motivo_impeditivo="provavelmente o delimitador não é vírgula",
        )
    )
    return _Varredura(
        header=cabecalho, rows=linhas, defective=irregulares, issues=tuple(issues)
    )


def _tipos_de_csv(path: Path, cabecalho: list[str]) -> tuple[ColumnObservation, ...]:
    """Os tipos, pelo Polars, sobre uma amostra. `UNKNOWN` quando ele desiste."""
    import polars as pl

    try:
        amostra = pl.read_csv(
            path,
            n_rows=_LINHAS_DE_AMOSTRA,
            infer_schema_length=_LINHAS_DE_AMOSTRA,
            # O arquivo já foi varrido e as irregularidades já viraram issue
            # com número de linha. Aqui elas não podem interromper a única
            # coisa que esta passagem faz — e truncar é o certo, porque o
            # objetivo é o TIPO das colunas declaradas no cabeçalho.
            truncate_ragged_lines=True,
            encoding="utf8-lossy",
        )
    except Exception:  # noqa: BLE001 — inferência é opcional, não pode derrubar
        return tuple(
            ColumnObservation(name=nome, detected_type=DetectedType.UNKNOWN)
            for nome in cabecalho[:MAX_COLUMNS_DESCRIBED]
        )

    colunas: list[ColumnObservation] = []
    for nome, dtype in list(amostra.schema.items())[:MAX_COLUMNS_DESCRIBED]:
        serie = amostra.get_column(nome)
        nulos = int(serie.null_count())
        valores = [
            str(v) for v in serie.drop_nulls().head(MAX_SAMPLES_PER_COLUMN).to_list()
        ]
        colunas.append(
            ColumnObservation(
                name=nome,
                detected_type=_tipo_polars(str(dtype)),
                nullable=bool(nulos),
                null_count=nulos,
                samples=tuple(valores),
            )
        )
    return tuple(colunas)


# -------------------------------------------------------------------- jsonl --


def inspect_jsonl(path: Path, *, file_id: str, max_rows: int) -> Inspection:
    """Uma linha, um objeto JSON. Com guarda de profundidade.

    A GUARDA DE PROFUNDIDADE NÃO É PARANOIA. `json.loads` é recursivo, e um
    documento com milhares de níveis de aninhamento estoura a pilha do
    interpretador. Um `[[[[[...]]]]]` de 4 KB derruba o worker, e não há
    `except` que salve.

    A defesa é medir a profundidade nos CARACTERES, antes de parsear: contar
    aberturas fora de string é O(n) sobre a linha e não entra em recursão.
    """
    issues: list[DatasetValidationIssue] = []
    linhas = 0
    malformadas = 0
    relatadas = 0
    chaves: dict[str, None] = {}

    try:
        with path.open("r", encoding="utf-8-sig") as fonte:
            for numero, bruta in enumerate(_linhas_limitadas(fonte, file_id, issues), start=1):
                linha = bruta.strip()
                if not linha:
                    continue
                linhas += 1
                if linhas > max_rows:
                    issues.append(
                        DatasetValidationIssue.of(
                            IssueCode.ROW_LIMIT_EXCEEDED,
                            f"mais de {max_rows} linhas — leitura interrompida",
                            file_id=file_id,
                        )
                    )
                    break
                problema = _problema_da_linha_jsonl(linha, chaves)
                if problema is None:
                    continue
                malformadas += 1
                if relatadas < _MAX_LINHAS_RELATADAS:
                    relatadas += 1
                    issues.append(
                        DatasetValidationIssue.of(
                            IssueCode.MALFORMED_ROW,
                            problema,
                            file_id=file_id,
                            location=f"linha {numero}",
                        )
                    )
    except UnicodeDecodeError as erro:
        return Inspection(observation=None, issues=(_issue_encoding(file_id, erro),))
    except OSError as erro:
        return _falha(IssueCode.UNREADABLE_FILE, file_id, "falha ao ler o JSONL", erro)

    issues.extend(
        _issues_agregadas(
            file_id=file_id,
            code=IssueCode.MALFORMED_ROW,
            defeituosas=malformadas,
            total=linhas,
            resumo="linha(s) malformada(s)",
            motivo_impeditivo="o arquivo provavelmente não é JSONL",
        )
    )

    if linhas == 0:
        return Inspection(
            observation=DatasetSchemaObservation(file_id=file_id, columns=(), row_count=0),
            issues=(
                *issues,
                DatasetValidationIssue.of(
                    IssueCode.NO_ROWS, "nenhuma linha de dado", file_id=file_id
                ),
            ),
        )

    colunas = _tipos_de_jsonl(path, tuple(chaves))
    observacao = DatasetSchemaObservation(
        file_id=file_id,
        columns=colunas,
        row_count=linhas,
        truncated_columns=len(chaves) > MAX_COLUMNS_DESCRIBED,
    )
    issues.extend(_issues_de_colunas(observacao, file_id))
    return Inspection(observation=observacao, issues=tuple(issues))


def _problema_da_linha_jsonl(linha: str, chaves: dict[str, None]) -> str | None:
    """`None` se a linha está bem; a descrição do defeito se não está."""
    if _profundidade_excede(linha, MAX_JSON_DEPTH):
        return (
            f"aninhamento acima de {MAX_JSON_DEPTH} níveis — não parseado, "
            "para não estourar a pilha do interpretador"
        )
    try:
        objeto = json.loads(linha)
    except json.JSONDecodeError as erro:
        return f"JSON inválido: {erro.msg} (coluna {erro.colno})"
    if not isinstance(objeto, dict):
        return f"cada linha de JSONL deve ser um OBJETO; esta é {type(objeto).__name__}"
    for chave in objeto:
        chaves.setdefault(str(chave), None)
    return None


def _tipos_de_jsonl(path: Path, chaves: tuple[str, ...]) -> tuple[ColumnObservation, ...]:
    import polars as pl

    try:
        amostra = pl.read_ndjson(path, n_rows=_LINHAS_DE_AMOSTRA)
    except Exception:  # noqa: BLE001 — inferência é opcional
        return tuple(
            ColumnObservation(name=chave, detected_type=DetectedType.UNKNOWN)
            for chave in chaves[:MAX_COLUMNS_DESCRIBED]
        )

    colunas: list[ColumnObservation] = []
    for nome, dtype in list(amostra.schema.items())[:MAX_COLUMNS_DESCRIBED]:
        serie = amostra.get_column(nome)
        nulos = int(serie.null_count())
        valores = [
            str(v)[:64] for v in serie.drop_nulls().head(MAX_SAMPLES_PER_COLUMN).to_list()
        ]
        colunas.append(
            ColumnObservation(
                name=nome,
                detected_type=_tipo_polars(str(dtype)),
                nullable=bool(nulos),
                null_count=nulos,
                samples=tuple(valores),
            )
        )
    return tuple(colunas)


# ------------------------------------------------------------------ comuns --


def _linhas_limitadas(
    fonte: Iterator[str], file_id: str, issues: list[DatasetValidationIssue]
) -> Iterator[str]:
    """Passa as linhas adiante, parando na primeira absurdamente longa.

    UM ARQUIVO SEM QUEBRA DE LINHA É UMA LINHA DO TAMANHO DO ARQUIVO, e lê-la
    anula o streaming: o pico de memória volta a ser o tamanho do arquivo,
    que é justamente o que todo este caminho existe para evitar.
    """
    for numero, linha in enumerate(fonte, start=1):
        if len(linha) > MAX_LINE_BYTES:
            issues.append(
                DatasetValidationIssue.of(
                    IssueCode.MALFORMED_ROW,
                    f"linha com {len(linha)} caracteres, acima do limite de "
                    f"{MAX_LINE_BYTES} — provavelmente o arquivo não tem quebras de linha",
                    file_id=file_id,
                    location=f"linha {numero}",
                    severity=IssueSeverity.BLOCKING,
                )
            )
            return
        yield linha


def _issues_agregadas(
    *,
    file_id: str,
    code: IssueCode,
    defeituosas: int,
    total: int,
    resumo: str,
    motivo_impeditivo: str,
) -> list[DatasetValidationIssue]:
    """O excedente do teto, e a elevação quando o defeito deixa de ser local."""
    issues: list[DatasetValidationIssue] = []
    if defeituosas > _MAX_LINHAS_RELATADAS:
        restantes = defeituosas - _MAX_LINHAS_RELATADAS
        issues.append(
            DatasetValidationIssue.of(
                code,
                f"mais {restantes} {resumo}",
                file_id=file_id,
                occurrences=restantes,
            )
        )
    if total and defeituosas / total >= _FRACAO_QUE_TORNA_IMPEDITIVO:
        # DEIXA DE SER DANO LOCAL. Um quarto das linhas defeituosas quase
        # sempre significa que o arquivo não é o que diz ser, e nesse caso
        # nada do que vier depois faz sentido.
        issues.append(
            DatasetValidationIssue.of(
                IssueCode.FORMAT_MISMATCH,
                f"{defeituosas} de {total} linhas ({defeituosas / total:.0%}) com defeito — "
                f"{motivo_impeditivo}",
                file_id=file_id,
                severity=IssueSeverity.BLOCKING,
            )
        )
    return issues


def _issues_de_colunas(
    observacao: DatasetSchemaObservation, file_id: str
) -> list[DatasetValidationIssue]:
    """Os defeitos que são do cabeçalho, não do conteúdo."""
    issues: list[DatasetValidationIssue] = []
    issues.extend(
        DatasetValidationIssue.of(
            IssueCode.DUPLICATE_COLUMN,
            f"a coluna {nome!r} aparece mais de uma vez — quase toda biblioteca "
            "renomeia ou descarta uma delas em silêncio",
            file_id=file_id,
            location=f"coluna {nome}",
        )
        for nome in observacao.duplicated_columns()
    )
    vazias = sum(1 for c in observacao.columns if not c.name.strip())
    if vazias:
        issues.append(
            DatasetValidationIssue.of(
                IssueCode.EMPTY_COLUMN_NAME,
                f"{vazias} coluna(s) sem nome no cabeçalho",
                file_id=file_id,
                occurrences=vazias,
            )
        )
    return issues


def _issue_encoding(file_id: str, erro: UnicodeDecodeError) -> DatasetValidationIssue:
    return DatasetValidationIssue.of(
        IssueCode.UNSUPPORTED_ENCODING,
        f"o arquivo não é UTF-8: {erro.reason} na posição {erro.start}. "
        "Latin-1 não é adivinhado de propósito — toda sequência de bytes é Latin-1 "
        "válida, e supor isso produziria acentos errados sem nenhum erro.",
        file_id=file_id,
    )


def _falha(code: IssueCode, file_id: str, prefixo: str, erro: BaseException) -> Inspection:
    return Inspection(
        observation=None,
        issues=(
            DatasetValidationIssue.of(
                code, f"{prefixo}: {_resumo_do_erro(erro)}", file_id=file_id
            ),
        ),
    )


_TIPOS_POLARS: Final[tuple[tuple[tuple[str, ...], DetectedType], ...]] = (
    (("list", "struct", "array", "object"), DetectedType.NESTED),
    (("bool",), DetectedType.BOOLEAN),
    (("datetime",), DetectedType.TIMESTAMP),
    (("date",), DetectedType.DATE),
    (("int", "uint"), DetectedType.INTEGER),
    (("float", "decimal"), DetectedType.FLOAT),
    (("str", "utf8", "binary", "categorical", "enum"), DetectedType.STRING),
    (("null",), DetectedType.UNKNOWN),
)


def _tipo_polars(dtype: str) -> DetectedType:
    """Traduz o dtype do Polars para o vocabulário pequeno do relatório."""
    t = dtype.strip().lower()
    for prefixos, tipo in _TIPOS_POLARS:
        if t.startswith(prefixos):
            return tipo
    return DetectedType.UNKNOWN


_TIPOS_ARROW: Final[tuple[tuple[tuple[str, ...], DetectedType], ...]] = (
    (("list", "struct", "map", "large_list"), DetectedType.NESTED),
    (("bool",), DetectedType.BOOLEAN),
    (("timestamp",), DetectedType.TIMESTAMP),
    (("date",), DetectedType.DATE),
    (("int", "uint"), DetectedType.INTEGER),
    (("float", "double", "decimal", "halffloat"), DetectedType.FLOAT),
    (("string", "large_string", "utf8", "binary"), DetectedType.STRING),
)


def _tipo_arrow(tipo: str) -> DetectedType:
    t = tipo.strip().lower()
    for prefixos, detectado in _TIPOS_ARROW:
        if t.startswith(prefixos):
            return detectado
    return DetectedType.UNKNOWN


def _profundidade_excede(linha: str, limite: int) -> bool:
    """Profundidade de aninhamento medida nos caracteres, sem recursão.

    Ignora o que está dentro de string — um `{` num nome de time não é
    abertura de objeto, e contá-lo produziria recusa falsa.
    """
    profundidade = 0
    dentro_de_string = False
    escapado = False
    for caractere in linha:
        if escapado:
            escapado = False
        elif caractere == "\\":
            escapado = True
        elif caractere == '"':
            dentro_de_string = not dentro_de_string
        elif dentro_de_string:
            continue
        elif caractere in "{[":
            profundidade += 1
            if profundidade > limite:
                return True
        elif caractere in "}]":
            profundidade -= 1
    return False


def _resumo_do_erro(erro: BaseException) -> str:
    """A mensagem do parser, truncada e sem caminho de sistema de arquivos.

    ERRO DE PARSER É SAÍDA NÃO CONFIÁVEL. Ele costuma incluir o caminho do
    arquivo temporário e, em alguns casos, um trecho do conteúdo — os dois
    vazariam para o relatório, que é lido por quem pode não ter direito de
    ver o conteúdo.
    """
    texto = str(erro).replace("\n", " ").strip()
    if sys.platform == "win32":
        texto = texto.replace("\\", "/")
    partes = [p for p in texto.split() if not p.startswith("/") and ":/" not in p]
    resumo = " ".join(partes)[:200]
    return resumo or type(erro).__name__

