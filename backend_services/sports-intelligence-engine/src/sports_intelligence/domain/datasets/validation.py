"""O relatório de validação estrutural, e por que ele não é um booleano.

`is_valid = True/False` É A FORMA MAIS COMUM DE PERDER INFORMAÇÃO AQUI. Um
arquivo com três linhas malformadas em cem mil e um arquivo que não é sequer
um CSV recebem o mesmo `False`, e as ações que eles pedem são opostas: o
primeiro segue com uma anotação, o segundo volta para a origem. Quem opera
precisa da diferença, e ela não existe depois que o booleano foi calculado.

Então: cada achado é uma ISSUE tipada, com código, severidade e localização. O
estado do dataset sai da pior severidade encontrada, e a passagem para
`STAGED` depende de UMA severidade específica, não de um resumo.

AS QUATRO SEVERIDADES E A LINHA QUE IMPORTA:

    INFO       observado, sem defeito         não muda nada
    WARNING    suspeito, provavelmente ok     alguém deveria olhar
    ERROR      defeito localizado             algumas linhas se perdem
    BLOCKING   o arquivo não é o que diz ser  nada adiante funciona

A linha está entre ERROR e BLOCKING, e ela separa dano LOCAL de dano TOTAL.
Doze linhas malformadas em cem mil é `ERROR`: o arquivo é o que diz ser, doze
linhas não entram, e o operador decide se isso importa. Um Parquet declarado
como CSV é `BLOCKING`: nada do que vier depois tem sentido, e deixar passar
faria o PR-03 gastar uma execução inteira para descobrir o que este PR já
sabia.

TETO DE ISSUES, E ELE NÃO É OPCIONAL. Um arquivo com um separador errado
produz uma issue por linha. Guardar um milhão de linhas de relatório para
dizer "o separador está errado" derruba o banco para não acrescentar
informação nenhuma depois da décima. Guardamos uma amostra, contamos o total,
e dizemos que truncamos — as três coisas, porque só a amostra mentiria sobre
a extensão e só o total não deixaria ninguém entender o problema.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import ClassVar, Final, Self, final

from sports_intelligence.domain.datasets.schema import DatasetSchemaObservation
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import DatasetId
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion, Version


@final
@dataclass(frozen=True, slots=True, order=True)
class ValidatorVersion(Version):
    """A versão do validador estrutural.

    ELA VIAJA NO RELATÓRIO PORQUE O VALIDADOR MUDA. Um arquivo aprovado pela
    v1.0 e reprovado pela v1.1 não mudou — o que mudou foi o que sabemos
    procurar. Sem a versão gravada, a diferença entre os dois relatórios
    pareceria uma mudança no arquivo, e alguém iria procurar o que não existe.
    """

    KIND: ClassVar[str] = "versão do validador"


#: A versão que este PR entrega.
CURRENT_VALIDATOR_VERSION: Final[ValidatorVersion] = ValidatorVersion(major=1, minor=0)


class IssueSeverity(IntEnum):
    """Quão grave. Ordenável, e a ordem é o que permite "a pior encontrada".

    `IntEnum` E NÃO `StrEnum`, ao contrário do resto da base: aqui a
    comparação entre valores é a operação principal — `max(severidades)` — e
    fazê-la sobre strings exigiria uma tabela de ordem paralela ao enum, que
    é mais uma coisa para divergir.
    """

    INFO = 10
    WARNING = 20
    ERROR = 30
    BLOCKING = 40

    @property
    def blocks_staging(self) -> bool:
        """A única pergunta que decide se o dataset pode subir para `STAGED`."""
        return self is IssueSeverity.BLOCKING

    def __str__(self) -> str:
        return self.name


class IssueCode(StrEnum):
    """O que especificamente foi encontrado. Fechado."""

    # ---- estruturais do arquivo
    EMPTY_FILE = "EMPTY_FILE"
    INVALID_FORMAT = "INVALID_FORMAT"
    FORMAT_MISMATCH = "FORMAT_MISMATCH"
    COMPRESSED_FILE_UNSUPPORTED = "COMPRESSED_FILE_UNSUPPORTED"
    UNSUPPORTED_ENCODING = "UNSUPPORTED_ENCODING"
    SIZE_LIMIT_EXCEEDED = "SIZE_LIMIT_EXCEEDED"
    ROW_LIMIT_EXCEEDED = "ROW_LIMIT_EXCEEDED"
    UNREADABLE_FILE = "UNREADABLE_FILE"
    CONTENT_HASH_MISMATCH = "CONTENT_HASH_MISMATCH"
    OBJECT_MISSING = "OBJECT_MISSING"

    # ---- do cabeçalho e das colunas
    MISSING_HEADER = "MISSING_HEADER"
    DUPLICATE_COLUMN = "DUPLICATE_COLUMN"
    MISSING_REQUIRED_COLUMN = "MISSING_REQUIRED_COLUMN"
    UNEXPECTED_COLUMN = "UNEXPECTED_COLUMN"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    EMPTY_COLUMN_NAME = "EMPTY_COLUMN_NAME"

    # ---- das linhas
    MALFORMED_ROW = "MALFORMED_ROW"
    NO_ROWS = "NO_ROWS"
    INCONSISTENT_FIELD_COUNT = "INCONSISTENT_FIELD_COUNT"

    # ---- do conjunto
    DUPLICATE_CONTENT = "DUPLICATE_CONTENT"
    SCHEMA_DIVERGENCE_BETWEEN_FILES = "SCHEMA_DIVERGENCE_BETWEEN_FILES"
    LICENSE_REVIEW_REQUIRED = "LICENSE_REVIEW_REQUIRED"

    @property
    def default_severity(self) -> IssueSeverity:
        """A severidade natural do código.

        UMA TABELA E NÃO UM CAMPO LIVRE. Se cada lugar que emite uma issue
        escolhesse a severidade, o mesmo defeito seria impeditivo num arquivo
        e aviso em outro, dependendo de qual caminho o encontrou. A severidade
        é propriedade do que foi encontrado, não de quem encontrou.

        O emissor ainda pode elevá-la — `MALFORMED_ROW` em metade das linhas
        deixa de ser dano local — mas a elevação é explícita e visível.
        """
        return _SEVERIDADE_PADRAO[self]


_SEVERIDADE_PADRAO: Final[dict[IssueCode, IssueSeverity]] = {
    # Nada adiante funciona: o arquivo não é o que diz ser.
    IssueCode.EMPTY_FILE: IssueSeverity.BLOCKING,
    IssueCode.INVALID_FORMAT: IssueSeverity.BLOCKING,
    IssueCode.FORMAT_MISMATCH: IssueSeverity.BLOCKING,
    IssueCode.COMPRESSED_FILE_UNSUPPORTED: IssueSeverity.BLOCKING,
    IssueCode.UNSUPPORTED_ENCODING: IssueSeverity.BLOCKING,
    IssueCode.SIZE_LIMIT_EXCEEDED: IssueSeverity.BLOCKING,
    IssueCode.ROW_LIMIT_EXCEEDED: IssueSeverity.BLOCKING,
    IssueCode.UNREADABLE_FILE: IssueSeverity.BLOCKING,
    # Os bytes gravados não conferem com o hash registrado. É o pior achado
    # possível neste PR: a evidência não é a que dissemos ter guardado.
    IssueCode.CONTENT_HASH_MISMATCH: IssueSeverity.BLOCKING,
    IssueCode.OBJECT_MISSING: IssueSeverity.BLOCKING,
    IssueCode.MISSING_HEADER: IssueSeverity.BLOCKING,
    IssueCode.MISSING_REQUIRED_COLUMN: IssueSeverity.BLOCKING,
    IssueCode.NO_ROWS: IssueSeverity.BLOCKING,
    IssueCode.DUPLICATE_CONTENT: IssueSeverity.BLOCKING,
    # Uma coluna duplicada não impede a leitura e faz uma das duas sumir sem
    # aviso — dano real, localizado, e o operador precisa decidir.
    IssueCode.DUPLICATE_COLUMN: IssueSeverity.ERROR,
    IssueCode.EMPTY_COLUMN_NAME: IssueSeverity.ERROR,
    IssueCode.MALFORMED_ROW: IssueSeverity.ERROR,
    IssueCode.INCONSISTENT_FIELD_COUNT: IssueSeverity.ERROR,
    # Divergência de tipo contra o contrato: quase sempre o contrato está
    # desatualizado, e quase sempre não impede nada.
    IssueCode.TYPE_MISMATCH: IssueSeverity.WARNING,
    # Fonte pública acrescenta coluna sem avisar. Não é motivo para recusar.
    IssueCode.UNEXPECTED_COLUMN: IssueSeverity.WARNING,
    IssueCode.SCHEMA_DIVERGENCE_BETWEEN_FILES: IssueSeverity.WARNING,
    # Guardar e validar dado de licença desconhecida é legítimo; promovê-lo a
    # uso comercial sem decisão humana não é. A marca é o que garante que a
    # pergunta seja feita — e ela não impede o staging.
    IssueCode.LICENSE_REVIEW_REQUIRED: IssueSeverity.INFO,
}


@final
@dataclass(frozen=True, slots=True)
class DatasetValidationIssue:
    """Um achado, com onde ele está.

    `location` É O QUE TORNA A ISSUE ACIONÁVEL. "linha 4.312, coluna `Date`"
    manda alguém ao lugar certo; "erro de formato" manda alguém abrir cem mil
    linhas para procurar.
    """

    code: IssueCode
    severity: IssueSeverity
    message: str
    #: O arquivo, quando o achado é de um arquivo. `None` para achados do
    #: conjunto — divergência de schema entre arquivos não é de nenhum deles.
    file_id: str | None = None
    location: str | None = None
    #: Quantas vezes este mesmo achado ocorreu. Existe por causa do teto: uma
    #: issue amostrada precisa carregar a extensão do que representa, senão a
    #: amostra vira a informação e o resto some.
    occurrences: int = 1

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValidationError("issue sem mensagem")
        if self.occurrences < 1:
            raise ValidationError(f"occurrences={self.occurrences} inválido")

    @classmethod
    def of(
        cls,
        code: IssueCode,
        message: str,
        *,
        file_id: str | None = None,
        location: str | None = None,
        severity: IssueSeverity | None = None,
        occurrences: int = 1,
    ) -> Self:
        """Cria com a severidade padrão do código, salvo elevação explícita."""
        return cls(
            code=code,
            severity=severity or code.default_severity,
            message=message,
            file_id=file_id,
            location=location,
            occurrences=occurrences,
        )

    def __str__(self) -> str:
        onde = f" ({self.location})" if self.location else ""
        vezes = f" ×{self.occurrences}" if self.occurrences > 1 else ""
        return f"[{self.severity}] {self.code}{onde}: {self.message}{vezes}"


class ValidationStatus(StrEnum):
    """O veredito do relatório, derivado — nunca informado."""

    PASSED = "PASSED"
    PASSED_WITH_WARNINGS = "PASSED_WITH_WARNINGS"
    #: Há defeito localizado. O dataset AINDA pode ser promovido: o operador
    #: decide se doze linhas perdidas importam. É a distinção que o booleano
    #: apagava.
    PASSED_WITH_ERRORS = "PASSED_WITH_ERRORS"
    #: Há impeditivo. `STAGED` fica fora de alcance.
    BLOCKED = "BLOCKED"


@final
@dataclass(frozen=True, slots=True)
class DatasetValidationReport:
    """O que a validação encontrou, e o que isso autoriza.

    IMUTÁVEL E DATADO. Revalidar não edita este relatório: produz outro, com
    outro id e outra versão de validador. Os dois coexistem, e a comparação
    entre eles é o que mostra o que o validador novo passou a enxergar.
    """

    id: str
    dataset_id: DatasetId
    dataset_version: DatasetVersion
    validator_version: ValidatorVersion
    started_at: Instant
    generated_at: Instant
    files_checked: int
    rows_observed: int
    #: A amostra guardada. Ver `issue_count` para o total real.
    issues: tuple[DatasetValidationIssue, ...] = ()
    schema_observations: tuple[DatasetSchemaObservation, ...] = ()
    #: O total encontrado, incluindo o que não coube. Sem ele, um relatório
    #: truncado em 100 issues afirmaria que houve 100.
    issue_count: int = 0
    truncated: bool = False
    #: Preenchido quando a validação não chegou ao fim por falha nossa —
    #: object store fora, processo morto. Distinto de um relatório com
    #: impeditivos: ali o arquivo é ruim, aqui nós é que falhamos.
    execution_error: str | None = None

    def __post_init__(self) -> None:
        if self.generated_at < self.started_at:
            raise ValidationError("relatório gerado antes de começar")
        if self.issue_count < len(self.issues):
            raise ValidationError(
                f"issue_count ({self.issue_count}) menor que as issues guardadas "
                f"({len(self.issues)}) — a contagem total nunca é menor que a amostra"
            )
        if self.truncated and self.issue_count <= len(self.issues):
            raise ValidationError(
                "relatório marcado como truncado sem ter perdido nenhuma issue"
            )
        for nome in ("files_checked", "rows_observed"):
            if getattr(self, nome) < 0:
                raise ValidationError(f"{nome} negativo")

    @classmethod
    def build(
        cls,
        *,
        dataset_id: DatasetId,
        dataset_version: DatasetVersion,
        started_at: Instant,
        generated_at: Instant,
        files_checked: int,
        rows_observed: int,
        issues: tuple[DatasetValidationIssue, ...],
        schema_observations: tuple[DatasetSchemaObservation, ...] = (),
        issue_count: int | None = None,
        truncated: bool = False,
        validator_version: ValidatorVersion = CURRENT_VALIDATOR_VERSION,
        execution_error: str | None = None,
    ) -> Self:
        """Monta o relatório, ordenando as issues por gravidade.

        A ORDENAÇÃO É PARTE DO CONTRATO, não estética. Quem lê um relatório em
        terminal lê as primeiras linhas; se a ordem for a de descoberta, o
        impeditivo aparece depois de quarenta avisos e ninguém o vê.
        """
        ordenadas = tuple(
            sorted(
                issues,
                key=lambda i: (-i.severity.value, i.code.value, i.file_id or "", i.location or ""),
            )
        )
        return cls(
            id=str(uuid.uuid4()),
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            validator_version=validator_version,
            started_at=started_at,
            generated_at=generated_at,
            files_checked=files_checked,
            rows_observed=rows_observed,
            issues=ordenadas,
            schema_observations=schema_observations,
            issue_count=issue_count if issue_count is not None else len(ordenadas),
            truncated=truncated,
            execution_error=execution_error,
        )

    @property
    def worst_severity(self) -> IssueSeverity | None:
        return max((i.severity for i in self.issues), default=None)

    @property
    def has_blocking_issues(self) -> bool:
        """A única pergunta que o staging faz a este relatório."""
        return any(i.severity.blocks_staging for i in self.issues)

    @property
    def status(self) -> ValidationStatus:
        pior = self.worst_severity
        if pior is None or pior is IssueSeverity.INFO:
            return ValidationStatus.PASSED
        if pior is IssueSeverity.WARNING:
            return ValidationStatus.PASSED_WITH_WARNINGS
        if pior is IssueSeverity.ERROR:
            return ValidationStatus.PASSED_WITH_ERRORS
        return ValidationStatus.BLOCKED

    @property
    def blocking_issues(self) -> tuple[DatasetValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity.blocks_staging)

    def count_by_severity(self) -> dict[IssueSeverity, int]:
        contagem: dict[IssueSeverity, int] = {}
        for issue in self.issues:
            contagem[issue.severity] = contagem.get(issue.severity, 0) + issue.occurrences
        return contagem

    def __str__(self) -> str:
        marca = " (truncado)" if self.truncated else ""
        return (
            f"{self.status} · {self.files_checked} arquivo(s) · "
            f"{self.rows_observed} linha(s) · {self.issue_count} achado(s){marca}"
        )


@final
@dataclass(slots=True)
class IssueCollector:
    """Acumula issues respeitando o teto, sem perder a contagem.

    A ÚNICA PEÇA MUTÁVEL DESTE PACOTE, e declarada como tal — sem `frozen`,
    para que a mutação seja visível na assinatura em vez de escondida atrás de
    um `object.__setattr__`. Ela existe porque a alternativa (cada validador
    guardando a própria lista e decidindo sozinho quando parar) produziria
    tetos diferentes por caminho de código, o que é o mesmo que não ter teto.
    """

    max_issues: int
    _guardadas: list[DatasetValidationIssue] = field(default_factory=list)
    _total: int = 0

    def __post_init__(self) -> None:
        if self.max_issues < 1:
            raise ValidationError(f"max_issues={self.max_issues} inválido")

    def add(self, issue: DatasetValidationIssue) -> None:
        self._total += issue.occurrences
        if len(self._guardadas) < self.max_issues:
            self._guardadas.append(issue)
        elif issue.severity.blocks_staging and not any(
            i.severity.blocks_staging for i in self._guardadas
        ):
            # UM IMPEDITIVO NUNCA É DESCARTADO POR TETO. Se o teto encheu de
            # avisos e o impeditivo chegou depois, ele entra no lugar do
            # último aviso — o relatório precisa CONTER o motivo pelo qual o
            # dataset não sobe, não apenas contá-lo.
            self._guardadas[-1] = issue

    @property
    def issues(self) -> tuple[DatasetValidationIssue, ...]:
        return tuple(self._guardadas)

    @property
    def total(self) -> int:
        return self._total

    @property
    def truncated(self) -> bool:
        return self._total > len(self._guardadas)
