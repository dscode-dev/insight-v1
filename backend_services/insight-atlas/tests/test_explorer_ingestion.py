from datetime import datetime, timezone
from uuid import uuid4

import pytest

from atlas.ingestion import (
    AtlasIngestionBatch,
    AtlasIngestionService,
    AtlasMemoryIngest,
    AtlasVectorIngest,
)


def _lineage():
    return {
        "generation_id": "bridge-dry-run",
        "source_system": "insight-explorer",
        "source_path": "derived/atlas/memory_snapshots.jsonl",
        "source_checksum": "sha256:" + "a" * 64,
        "feature_time_policy": "strictly_before_kickoff",
        "producer_version": "explorer-enrich-a",
    }


def _memory():
    payload = {
        "competition": "brasileirao_serie_a",
        "home_team_memory": {"team_id": "santos"},
        "away_team_memory": {"team_id": "flamengo"},
    }
    return {
        "schema_version": "explorer-atlas.ingest.v1",
        "record_id": str(uuid4()),
        "content_hash": "sha256:" + "b" * 64,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "lineage": _lineage(),
        "competition": "brasileirao_serie_a",
        "home_team": "santos",
        "away_team": "flamengo",
        "payload": payload,
    }


def _vector():
    return {
        "schema_version": "explorer-atlas.ingest.v1",
        "record_id": str(uuid4()),
        "content_hash": "sha256:" + "c" * 64,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "lineage": _lineage(),
        "source_match_id": "bridge-match-1",
        "competition": "brasileirao_serie_a",
        "regime": "league",
        "home_team": "santos",
        "away_team": "flamengo",
        "behavior": ["draw_tendency"],
        "trends": ["draw_trend"],
        "signals": ["home_form"],
        "market_available": False,
        "uncertainty": 0.3,
        "embedding_version": "atlas-memory-embedding-v1",
        "embedding": [0.0] * 31 + [1.0],
    }


def test_ingestion_contracts_are_immutable_and_strict():
    memory = AtlasMemoryIngest.model_validate(_memory())
    vector = AtlasVectorIngest.model_validate(_vector())
    assert memory.lineage.generation_id == "bridge-dry-run"
    assert len(vector.embedding) == 32
    with pytest.raises(Exception):
        memory.competition = "other"


class _Repository:
    def __init__(self):
        self.saved = None

    async def persist(self, batch, memories, behaviors, vectors, signals, rejections):
        self.saved = (batch, memories, behaviors, vectors, signals, rejections)
        return {
            "accepted": len(memories) + len(behaviors) + len(vectors) + len(signals),
            "rejected": len(rejections),
            "memories": len(memories),
            "behaviors": len(behaviors),
            "vectors": len(vectors),
            "signals": len(signals),
        }


@pytest.mark.asyncio
async def test_ingestion_rejects_bad_record_without_losing_valid_records():
    bad = _vector()
    bad["embedding"] = [0.0]
    batch = AtlasIngestionBatch.model_validate({
        "schema_version": "explorer-atlas.ingest.v1",
        "batch_id": str(uuid4()),
        "generation_id": "bridge-dry-run",
        "source_system": "insight-explorer",
        "content_hash": "sha256:" + "d" * 64,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "memories": [_memory()],
        "vectors": [_vector(), bad],
    })
    repository = _Repository()
    result = await AtlasIngestionService(repository).ingest(batch)
    assert result["status"] == "partial"
    assert result["accepted"] == 2
    assert result["rejected"] == 1
    assert len(repository.saved[1]) == 1
    assert len(repository.saved[3]) == 1
