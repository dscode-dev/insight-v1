"""Erros do domínio — que não sabem que existe HTTP.

A REGRA. Nada aqui importa FastAPI, e nenhum erro carrega status code. A
tradução para HTTP é trabalho do adapter, e mantê-la lá é o que permite a
mesma regra de negócio servir a API, a CLI e um worker sem que cada um invente
a própria semântica de falha.

O CAMINHO OPOSTO é comum: `raise HTTPException(404)` no domínio. Ele funciona
até o dia em que a mesma regra roda num worker, onde não há requisição para
responder — e aí a exceção sobe como erro interno de um servidor que não
existe.

CATEGORIA E NÃO HIERARQUIA PROFUNDA. Uma árvore de cinquenta exceções obriga
quem trata a conhecer todas. Uma categoria enumerada deixa o `match` exaustivo
e o mapeamento para HTTP ser uma tabela de dez linhas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ErrorCategory(StrEnum):
    """A natureza da falha. Governa a tradução na fronteira."""

    VALIDATION = "VALIDATION"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    #: Uma dependência externa falhou de forma que não vai melhorar sozinha.
    DEPENDENCY = "DEPENDENCY"
    #: Falha que provavelmente passa: vale tentar de novo.
    TRANSIENT = "TRANSIENT"
    INTERNAL = "INTERNAL"
    #: O dado chegou, é bem formado, e não é bom o bastante para ser usado.
    DATA_QUALITY = "DATA_QUALITY"
    #: Uma regra que o sistema promete nunca quebrar foi quebrada. Sempre um
    #: defeito nosso, nunca entrada ruim do usuário.
    INVARIANT_VIOLATION = "INVARIANT_VIOLATION"

    @property
    def is_retryable(self) -> bool:
        return self is ErrorCategory.TRANSIENT

    @property
    def is_caller_fault(self) -> bool:
        """Se quem chamou pode consertar mudando o que enviou."""
        return self in (
            ErrorCategory.VALIDATION,
            ErrorCategory.NOT_FOUND,
            ErrorCategory.CONFLICT,
            ErrorCategory.UNAUTHORIZED,
            ErrorCategory.FORBIDDEN,
        )


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    """Onde e o quê. Uma lista disto é o que torna um erro acionável.

    RELATAR TODOS OS PROBLEMAS, NÃO O PRIMEIRO. Um registro com quatro campos
    errados relatado um por vez custa quatro idas e voltas, e quem conserta
    começa a adivinhar na segunda.
    """

    field: str
    message: str


class EngineError(Exception):
    """A raiz. Toda falha do domínio passa por aqui, com categoria."""

    category: ErrorCategory = ErrorCategory.INTERNAL

    def __init__(
        self,
        message: str,
        *,
        details: tuple[ErrorDetail, ...] = (),
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        #: Dados estruturados para o log. NUNCA segredo: este dicionário é
        #: serializado inteiro pelo logger.
        self.context = context or {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "message": self.message,
            "details": [{"field": d.field, "message": d.message} for d in self.details],
            "context": self.context,
        }

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.category}: {self.message!r})"


class ValidationError(EngineError):
    category = ErrorCategory.VALIDATION


class NotFoundError(EngineError):
    category = ErrorCategory.NOT_FOUND


class ConflictError(EngineError):
    category = ErrorCategory.CONFLICT


class UnauthorizedError(EngineError):
    category = ErrorCategory.UNAUTHORIZED


class ForbiddenError(EngineError):
    category = ErrorCategory.FORBIDDEN


class DependencyError(EngineError):
    category = ErrorCategory.DEPENDENCY


class TransientError(EngineError):
    category = ErrorCategory.TRANSIENT


class DataQualityError(EngineError):
    """O dado é bem formado e não é bom o bastante.

    Separado de `ValidationError` porque a ação é outra: validação se conserta
    reenviando; qualidade se conserta buscando outra fonte ou aceitando a
    ausência.
    """

    category = ErrorCategory.DATA_QUALITY


class InvariantViolationError(EngineError):
    """Uma promessa estrutural foi quebrada.

    SEMPRE UM DEFEITO NOSSO. Se isto sobe, um estado que o sistema garante ser
    impossível aconteceu — como uma partida ao vivo entrando no índice
    histórico que ela própria consulta (ADR-0007). Não se trata com retry nem
    se devolve como "entrada inválida": trata-se investigando.
    """

    category = ErrorCategory.INVARIANT_VIOLATION


@dataclass(frozen=True, slots=True)
class ErrorResponse:
    """A forma que a fronteira serializa. Sem status code: o adapter decide.

    `correlation_id` é o que liga a resposta que o usuário viu à linha de log
    que explica o que houve.
    """

    category: ErrorCategory
    message: str
    details: tuple[ErrorDetail, ...] = field(default_factory=tuple)
    correlation_id: str | None = None

    @classmethod
    def from_error(cls, error: EngineError, correlation_id: str | None = None) -> ErrorResponse:
        return cls(
            category=error.category,
            message=error.message,
            details=error.details,
            correlation_id=correlation_id,
        )
