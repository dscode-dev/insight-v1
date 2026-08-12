"""Control Plane: administração, datasets, configuração, reconciliação.

O QUE O SEPARA DO QUERY PLANE (ADR-0002): aqui moram as operações que MUDAM o
sistema — promover um dataset, corrigir uma partida, reconciliar. São
operações raras, privilegiadas e auditadas.

A separação é de processo, não só de rota, e o motivo é operacional: um pico
de leitura no Query API não pode competir por recurso com uma reconciliação
em andamento, e uma operação administrativa não deve ser alcançável pelo mesmo
endereço que atende usuário final.
"""

from __future__ import annotations

from fastapi import FastAPI

from apps._shared import create_app
from sports_intelligence.config.settings import AppSettings


def build() -> FastAPI:
    return create_app(
        AppSettings(), title="Insight Engine — Control API", plane="control"
    )


app = build()
