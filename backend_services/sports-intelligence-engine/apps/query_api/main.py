"""Query Plane: leitura da inteligência já materializada.

A RESTRIÇÃO QUE GOVERNA ESTE PROCESSO (ADR-0010): requisição de usuário NUNCA
dispara cálculo do motor. O que ele serve foi computado quando o estado mudou
e materializado; N usuários lendo a mesma partida fazem N leituras de cache, e
não N cálculos.

O custo escala com partidas e estados, não com audiência. É isso que permite
uma partida popular ser lida por milhares de pessoas sem que o motor sinta.
"""

from __future__ import annotations

from fastapi import FastAPI

from apps._shared import create_app
from sports_intelligence.config.settings import AppSettings


def build() -> FastAPI:
    return create_app(AppSettings(), title="Insight Engine — Query API", plane="query")


app = build()
