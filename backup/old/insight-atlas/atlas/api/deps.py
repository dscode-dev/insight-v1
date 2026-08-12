from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import Depends, Header, HTTPException, Request, status

from atlas.config import Settings
from atlas.emitters import ContextEmitter
from atlas.features.builders import AnalyticsReader, SentimentReader
from atlas.inference import InferenceEngine
from atlas.registry import ModelRegistry
from atlas.store import FeatureStore, InferenceCache
from atlas.training import TrainingPipeline

if TYPE_CHECKING:
    from atlas.similarity import SimilarityService


@dataclass
class AppContainer:
    settings: Settings
    registry: ModelRegistry
    engine: InferenceEngine
    feature_store: FeatureStore
    inference_cache: InferenceCache
    emitter: ContextEmitter
    training: TrainingPipeline
    analytics: AnalyticsReader
    sentiment: SentimentReader
    similarity: SimilarityService | Any
    replay: Any
    strength: Any
    approvals: Any
    #: Ingestão por atlas.match.v1 — a mesma base para a API e para o CLI.
    #: `Any` como os vizinhos: tipar aqui traria atlas.intake para dentro
    #: do módulo de dependências e fecharia um ciclo de import.
    intake_repository: Any = None
    #: As cinco categorias de consulta sobre atlas.vector.v1.
    query_service: Any = None
    #: Reconstrói atlas.match_vector a partir de atlas.match_record.
    vector_builder: Any = None


def get_container(request: Request) -> AppContainer:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise RuntimeError("AppContainer not bound on app.state")
    return container


def require_internal_token(
    container: AppContainer = Depends(get_container),
    x_internal_token: str | None = Header(default=None),
) -> None:
    if not x_internal_token or not secrets.compare_digest(
        x_internal_token, container.settings.internal_token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="internal_token_required"
        )
