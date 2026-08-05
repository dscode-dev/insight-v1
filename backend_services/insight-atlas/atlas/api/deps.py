from __future__ import annotations

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
    from atlas.vector_memory.repository import PgVectorMemoryRepository


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
    vector_memory: PgVectorMemoryRepository | Any
    similarity: SimilarityService | Any
    replay: Any
    ingestion: Any
    datasets: Any
    strength: Any
    odds: Any


def get_container(request: Request) -> AppContainer:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise RuntimeError("AppContainer not bound on app.state")
    return container


def require_internal_token(
    container: AppContainer = Depends(get_container),
    x_internal_token: str | None = Header(default=None),
) -> None:
    if not x_internal_token or x_internal_token != container.settings.internal_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="internal_token_required"
        )
