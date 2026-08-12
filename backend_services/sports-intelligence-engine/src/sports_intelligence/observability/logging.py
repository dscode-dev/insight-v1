"""Log estruturado, com correlação, e sem segredo dentro.

DUAS COISAS QUE ESTE MÓDULO GARANTE.

A PRIMEIRA É CORRELAÇÃO. Um evento atravessa ingestão, estado, inteligência e
publicação; sem um id comum, investigar exige juntar linhas por timestamp — e
timestamps empatam. `ContextVar` carrega o contexto através de `await` sem que
cada função precise repassá-lo, que é a alternativa e vira ruído em toda
assinatura.

A SEGUNDA É QUE SEGREDO NÃO ENTRA. `SecretStr` protege a representação em
Python, e um `str(settings.password.get_secret_value())` num log a desfaz. O
filtro abaixo é a última barreira: ele redige por NOME de campo, porque o
valor não se reconhece sozinho.

REDIGIR POR NOME, E NÃO POR PADRÃO DE VALOR. Procurar "coisas que parecem
token" gera falso negativo em todo token que não parece — e um token vazado é
vazado. A lista de nomes é fechada e conservadora.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any, Final

from sports_intelligence.config.settings import AppSettings

#: Contexto que viaja com o processamento. Cada chave só aparece no log quando
#: foi preenchida — um campo nulo em toda linha é ruído.
#:
#: SEM DEFAULT MUTAVEL, e o motivo e concreto: `default={}` e UM dicionario
#: compartilhado por todo contexto que ainda nao escreveu. Um bind que
#: mutasse esse objeto vazaria o correlation_id de uma requisicao para
#: outra. `None` obriga a leitura a materializar um dicionario novo, e o
#: vazamento deixa de ser possivel por construcao.
_CONTEXTO: ContextVar[dict[str, str] | None] = ContextVar("log_context", default=None)


def _contexto_atual() -> dict[str, str]:
    return _CONTEXTO.get() or {}

#: Campos redigidos, por nome. Comparação por substring e minúsculas: cobre
#: `api_key`, `X-API-KEY` e `provider_api_key` com uma entrada só.
_SENSIVEIS: Final = frozenset(
    {
        "password", "passwd", "secret", "token", "api_key", "apikey",
        "authorization", "credential", "private_key", "access_key",
        "session", "cookie", "bearer",
    }
)

_REDIGIDO: Final = "***"

#: Atributos que o `logging` põe em todo record. Precisam ser filtrados para
#: que `extra` não os duplique no JSON.
_PADRAO_LOGRECORD: Final = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "taskName",
    }
)


def _redigir(chave: str, valor: Any) -> Any:
    minuscula = chave.lower()
    if any(sensivel in minuscula for sensivel in _SENSIVEIS):
        return _REDIGIDO
    if isinstance(valor, dict):
        return {k: _redigir(k, v) for k, v in valor.items()}
    return valor


class JsonFormatter(logging.Formatter):
    """Uma linha, um objeto JSON. Sem multilinha, sem prefixo humano.

    Log estruturado não é preferência estética: uma exceção formatada em
    quinze linhas é quinze registros para o coletor, e a busca por
    `correlation_id` acha a primeira.
    """

    def __init__(self, service_name: str, version: str) -> None:
        super().__init__()
        self._service = service_name
        self._version = version

    def format(self, record: logging.LogRecord) -> str:
        saida: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self._service,
            "version": self._version,
        }
        saida.update(_contexto_atual())
        for chave, valor in record.__dict__.items():
            if chave in _PADRAO_LOGRECORD or chave.startswith("_"):
                continue
            saida[chave] = _redigir(chave, valor)
        if record.exc_info:
            saida["exception"] = self.formatException(record.exc_info)
        return json.dumps(saida, ensure_ascii=False, default=str)


def configure_logging(settings: AppSettings) -> None:
    """Ponto único de configuração. Chamado uma vez, na borda do processo."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(settings.service_name, settings.version))

    raiz = logging.getLogger()
    raiz.handlers.clear()
    raiz.addHandler(handler)
    raiz.setLevel(settings.log_level.value)

    # Uvicorn instala os próprios handlers e duplicaria cada linha em texto.
    for nome in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(nome)
        logger.handlers.clear()
        logger.propagate = True


def bind_context(**valores: str | None) -> None:
    """Acrescenta campos ao contexto do processamento corrente.

    Campos previstos: `trace_id`, `correlation_id`, `match_id`, `dataset_id`,
    `provider_id`. `None` é ignorado — um campo que não se aplica não deve
    aparecer como nulo em toda linha.
    """
    atual = dict(_contexto_atual())
    atual.update({k: str(v) for k, v in valores.items() if v is not None})
    _CONTEXTO.set(atual)


def clear_context() -> None:
    """Limpa o contexto. Chamado ao fim de uma requisição ou de um tick —
    sem isso o contexto de um vaza para o próximo no mesmo worker."""
    _CONTEXTO.set(None)


def current_context() -> dict[str, str]:
    return dict(_contexto_atual())
