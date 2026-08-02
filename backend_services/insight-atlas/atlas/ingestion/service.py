"""Record-isolated validation and transactional Atlas ingestion."""

from __future__ import annotations

import time

from pydantic import ValidationError

from atlas.ingestion.contracts import (
    AtlasBehaviorIngest,
    AtlasIngestionBatch,
    AtlasMemoryIngest,
    AtlasSignalIngest,
    AtlasVectorIngest,
)
from atlas.ingestion.repository import AtlasIngestionRepository
from atlas.operational_events import event_bus


class AtlasIngestionService:
    def __init__(self, repository: AtlasIngestionRepository) -> None:
        self.repository = repository

    async def ingest(self, batch: AtlasIngestionBatch) -> dict:
        batch_started = time.perf_counter()
        event_bus.emit(
            "batch_queue_received",
            current_state="received",
            correlation_id=str(batch.batch_id),
            batch_id=str(batch.batch_id),
            metadata={
                "batch_id": str(batch.batch_id),
                "generation_id": batch.generation_id,
                "memory_rows": len(batch.memories),
                "behavior_rows": len(batch.behaviors),
                "vector_rows": len(batch.vectors),
                "signal_rows": len(batch.signals),
            },
        )
        event_bus.emit(
            "atlas_batch_received",
            current_state="received",
            correlation_id=str(batch.batch_id),
            batch_id=str(batch.batch_id),
            metadata={"batch_id": str(batch.batch_id), "generation_id": batch.generation_id},
        )
        rejections = []
        event_bus.emit(
            "batch_validation_started",
            current_state="validating",
            stage="validation",
            correlation_id=str(batch.batch_id),
            batch_id=str(batch.batch_id),
            metadata={"families": ["memory", "behavior", "vector", "signal"]},
        )
        event_bus.emit(
            "signal_processing_started",
            current_state="processing",
            correlation_id=str(batch.batch_id),
            batch_id=str(batch.batch_id),
            metadata={"batch_id": str(batch.batch_id), "signal_rows": len(batch.signals)},
        )
        memories = _validate(batch.memories, AtlasMemoryIngest, "memory", rejections)
        behaviors = _validate(
            batch.behaviors, AtlasBehaviorIngest, "behavior", rejections
        )
        vectors = _validate(batch.vectors, AtlasVectorIngest, "vector", rejections)
        signals = _validate(batch.signals, AtlasSignalIngest, "signal", rejections)
        event_bus.emit(
            "batch_validation_finished",
            current_state="validated",
            stage="validation",
            correlation_id=str(batch.batch_id),
            batch_id=str(batch.batch_id),
            metadata={
                "accepted_memories": len(memories),
                "accepted_behaviors": len(behaviors),
                "accepted_vectors": len(vectors),
                "accepted_signals": len(signals),
                "rejections": len(rejections),
            },
        )
        event_bus.emit(
            "signal_processing_finished",
            current_state="validated",
            correlation_id=str(batch.batch_id),
            batch_id=str(batch.batch_id),
            metadata={
                "batch_id": str(batch.batch_id),
                "accepted_signals": len(signals),
                "rejections": len([row for row in rejections if row["family"] == "signal"]),
            },
        )
        event_bus.emit(
            "memory_update_started",
            current_state="processing",
            correlation_id=str(batch.batch_id),
            batch_id=str(batch.batch_id),
            metadata={"batch_id": str(batch.batch_id), "memory_rows": len(memories)},
        )
        event_bus.emit(
            "behavior_update_started",
            current_state="processing",
            correlation_id=str(batch.batch_id),
            batch_id=str(batch.batch_id),
            metadata={"batch_id": str(batch.batch_id), "behavior_rows": len(behaviors)},
        )
        event_bus.emit(
            "persistence_started",
            current_state="persisting",
            stage="persistence",
            correlation_id=str(batch.batch_id),
            batch_id=str(batch.batch_id),
            metadata={"batch_id": str(batch.batch_id)},
        )
        counts = await self.repository.persist(
            batch, memories, behaviors, vectors, signals, rejections
        )
        event_bus.emit(
            "persistence_finished",
            current_state="persisted",
            stage="persistence",
            correlation_id=str(batch.batch_id),
            batch_id=str(batch.batch_id),
            duration_ms=int((time.perf_counter() - batch_started) * 1000),
            metadata={"batch_id": str(batch.batch_id), **counts},
        )
        event_bus.emit(
            "memory_update_finished",
            current_state="persisted",
            correlation_id=str(batch.batch_id),
            batch_id=str(batch.batch_id),
            metadata={"batch_id": str(batch.batch_id), "memories": counts.get("memories", 0)},
        )
        event_bus.emit(
            "behavior_update_finished",
            current_state="persisted",
            correlation_id=str(batch.batch_id),
            batch_id=str(batch.batch_id),
            metadata={"batch_id": str(batch.batch_id), "behaviors": counts.get("behaviors", 0)},
        )
        event_bus.emit(
            "vector_update_finished",
            current_state="persisted",
            correlation_id=str(batch.batch_id),
            batch_id=str(batch.batch_id),
            metadata={"batch_id": str(batch.batch_id), "vectors": counts.get("vectors", 0)},
        )
        event_bus.emit(
            "atlas_batch_acknowledged",
            current_state="partial" if rejections else "completed",
            correlation_id=str(batch.batch_id),
            batch_id=str(batch.batch_id),
            metadata={
                "batch_id": str(batch.batch_id),
                "generation_id": batch.generation_id,
                "rejections": len(rejections),
                **counts,
            },
        )
        return {
            "batch_id": str(batch.batch_id),
            "generation_id": batch.generation_id,
            "status": "partial" if rejections else "completed",
            **counts,
            "rejections": rejections,
        }


def _validate(rows, model, family, rejections):
    accepted = []
    for index, row in enumerate(rows):
        try:
            accepted.append(model.model_validate(row))
        except ValidationError as exc:
            rejections.append({
                "family": family,
                "index": index,
                "errors": [
                    {
                        "loc": list(error["loc"]),
                        "msg": error["msg"],
                        "type": error["type"],
                    }
                    for error in exc.errors(include_url=False)
                ],
            })
    return accepted
