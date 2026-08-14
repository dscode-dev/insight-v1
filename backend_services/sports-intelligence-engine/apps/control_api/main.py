"""Control Plane: administração, datasets, configuração, reconciliação.

O QUE O SEPARA DO QUERY PLANE (ADR-0002): aqui moram as operações que MUDAM o
sistema — registrar um dataset, validar, promover, reconciliar. São operações
raras, privilegiadas e auditadas.

A separação é de processo, não só de rota, e o motivo é operacional: um pico
de leitura no Query API não pode competir por recurso com um upload de 2 GB em
andamento, e uma operação administrativa não deve ser alcançável pelo mesmo
endereço que atende usuário final.

O UPLOAD MORA AQUI E SÓ AQUI. `query_api` não tem rota de escrita, e não é
convenção: é o que impede um endpoint de ingestão de aparecer no processo
exposto a tráfego de leitura.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps._shared import create_app
from apps.composition import build_container
from apps.control_api.routes import datasets as rotas_de_dataset
from apps.control_api.routes import resolution as rotas_de_resolucao
from sports_intelligence.config.settings import AppSettings


def build() -> FastAPI:
    settings = AppSettings()

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
        """Monta o contêiner e abre o pool UMA vez, no boot.

        NO STARTUP E NÃO POR REQUISIÇÃO. Um pool criado dentro de um
        `Depends` produz um pool por requisição, e o sintoma sob carga é
        esgotamento de conexões no PostgreSQL — que ninguém lê como "erro de
        composição", porque não é assim que ele aparece.

        A FALHA DE CONEXÃO NÃO IMPEDE O PROCESSO DE SUBIR. `/health/live`
        continua respondendo, `/health/ready` reporta o banco fora, e o
        orquestrador para de mandar tráfego sem entrar em laço de reinício —
        reiniciar um processo saudável não conserta um banco fora do ar.
        """
        contêiner = build_container(settings)
        app.state.container = contêiner
        try:
            await contêiner.database.connect()
        except Exception as erro:  # noqa: BLE001 — reportado no readiness
            app.state.startup_error = str(erro)
        yield
        await contêiner.database.close()

    app = create_app(
        settings, title="Insight Engine — Control API", plane="control"
    )
    app.router.lifespan_context = ciclo_de_vida
    app.include_router(rotas_de_dataset.router)
    app.include_router(rotas_de_resolucao.router)

    @app.get("/health/ready", tags=["health"])
    async def readiness() -> dict[str, object]:
        """Se o processo pode ATENDER — e o que está fora quando não pode.

        Sobrescreve o readiness genérico do PR-00, que reportava `checks`
        vazio porque não havia dependência. Agora há duas, e o valor está em
        dizer QUAL está fora: "banco fora" e "bucket fora" mandam a
        investigação para lugares diferentes.
        """
        contêiner = app.state.container
        banco = await contêiner.database.ping()
        objetos = await _ping_do_store(contêiner.object_store)
        pronto = banco and objetos
        return {
            "status": "ok" if pronto else "degraded",
            "service": settings.service_name,
            "checks": {
                "postgres": "ok" if banco else "indisponível",
                "object_store": "ok" if objetos else "indisponível",
            },
        }

    return app


async def _ping_do_store(store: object) -> bool:
    """`ping` é do adapter e não do port, então é consultado por duck typing.

    Deixá-lo fora do `ObjectStorePort` é deliberado: diagnóstico não é uma
    capacidade que o domínio precise; é uma que a borda usa. Pôr no protocolo
    obrigaria todo duplo de teste a implementá-lo.
    """
    metodo = getattr(store, "ping", None)
    if metodo is None:  # pragma: no cover
        return True
    resultado = await metodo()
    return bool(resultado)


app = build()
