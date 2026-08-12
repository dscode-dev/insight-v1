"""O que control_api e query_api compartilham — sem duplicar regra.

DUAS APLICAÇÕES, UMA MONTAGEM. As duas expõem health e version, as duas
carregam contexto de correlação, as duas traduzem erro do domínio para HTTP.
Copiar isso em cada uma é como as duas divergem: a primeira ganha um campo, a
segunda não, e ninguém percebe até um cliente reclamar.

AQUI É ONDE FastAPI PODE APARECER. Este módulo é adapter, e a tradução de
`EngineError` para status code mora nele por decisão explícita (ADR-0003): o
domínio não sabe que HTTP existe, e a fronteira sabe.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Final

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from sports_intelligence.config.settings import AppSettings
from sports_intelligence.domain.shared.errors import EngineError, ErrorCategory
from sports_intelligence.observability.logging import (
    bind_context,
    clear_context,
    configure_logging,
)
from sports_intelligence.observability.metrics import (
    HTTP_DURATION,
    HTTP_REQUESTS,
    Timer,
    record_start,
)

#: A tradução, num lugar só. Uma tabela e não `if`s espalhados: com `if`s, a
#: categoria nova esquecida em um handler vira 500 silencioso.
_STATUS: Final[dict[ErrorCategory, int]] = {
    ErrorCategory.VALIDATION: 422,
    ErrorCategory.NOT_FOUND: 404,
    ErrorCategory.CONFLICT: 409,
    ErrorCategory.UNAUTHORIZED: 401,
    ErrorCategory.FORBIDDEN: 403,
    ErrorCategory.DEPENDENCY: 502,
    ErrorCategory.TRANSIENT: 503,
    ErrorCategory.DATA_QUALITY: 422,
    # 500 e não 4xx: quebrar um invariante é defeito nosso, e devolver 4xx
    # colocaria a culpa em quem chamou.
    ErrorCategory.INVARIANT_VIOLATION: 500,
    ErrorCategory.INTERNAL: 500,
}

CORRELATION_HEADER: Final = "X-Correlation-Id"


class HealthResponse(BaseModel):
    """Resposta de saúde. Tipada para que o contrato seja o schema."""

    status: str = Field(description="'ok' quando o processo pode servir")
    service: str
    checks: dict[str, str] = Field(
        default_factory=dict,
        description="Nome da dependência → estado. Vazio quando nada é exigido.",
    )


class VersionResponse(BaseModel):
    service: str
    version: str
    environment: str


def create_app(settings: AppSettings, *, title: str, plane: str) -> FastAPI:
    """Monta uma aplicação com o que as duas precisam ter igual."""
    configure_logging(settings)
    record_start(settings.service_name, settings.version)

    app = FastAPI(title=title, version=settings.version, docs_url="/docs")
    app.state.settings = settings
    app.state.plane = plane

    @app.middleware("http")
    async def _contexto_e_metricas(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # O id do cliente é aceito quando vem — é o que amarra o rastro
        # através dos serviços do Insight; quando não vem, nasce aqui.
        correlation_id = request.headers.get(CORRELATION_HEADER) or str(uuid.uuid4())
        bind_context(correlation_id=correlation_id)
        rota = request.scope.get("route")
        # O PATH DO TEMPLATE, não o path concreto: `/matches/{id}` como label
        # é uma série; `/matches/<uuid>` é uma série POR PARTIDA, e isso
        # derruba o coletor.
        label = getattr(rota, "path", request.url.path)
        try:
            with Timer(HTTP_DURATION, request.method, label):
                resposta = await call_next(request)
        finally:
            clear_context()
        HTTP_REQUESTS.inc(request.method, label, str(resposta.status_code))
        resposta.headers[CORRELATION_HEADER] = correlation_id
        return resposta

    @app.exception_handler(EngineError)
    async def _erro_do_dominio(request: Request, exc: EngineError) -> JSONResponse:
        """A ÚNICA ponte entre erro de domínio e HTTP."""
        return JSONResponse(
            status_code=_STATUS[exc.category],
            content={
                "category": exc.category.value,
                "message": exc.message,
                "details": [{"field": d.field, "message": d.message} for d in exc.details],
                "correlation_id": request.headers.get(CORRELATION_HEADER),
            },
        )

    @app.get("/health/live", response_model=HealthResponse, tags=["health"])
    async def health_live() -> HealthResponse:
        """O processo está de pé.

        NÃO CONSULTA DEPENDÊNCIA NENHUMA, e isso é o ponto: um liveness que
        falha porque o banco caiu faz o orquestrador reiniciar um processo
        saudável — e reiniciar não conserta banco.
        """
        return HealthResponse(status="ok", service=settings.service_name)

    @app.get("/health/ready", response_model=HealthResponse, tags=["health"])
    async def health_ready() -> HealthResponse:
        """O processo pode ATENDER.

        No PR-00 não há dependência externa: `checks` sai vazio e diz isso.
        Cada adapter que entrar acrescenta a própria verificação aqui.
        """
        return HealthResponse(status="ok", service=settings.service_name, checks={})

    @app.get("/version", response_model=VersionResponse, tags=["meta"])
    async def version() -> VersionResponse:
        return VersionResponse(
            service=settings.service_name,
            version=settings.version,
            environment=settings.environment.value,
        )

    return app
