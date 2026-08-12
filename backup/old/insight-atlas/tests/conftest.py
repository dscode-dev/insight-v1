from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timezone
from uuid import UUID, uuid4

import numpy as np
import pytest

from atlas.features.definitions import FEATURE_NAMES
from atlas.features.snapshot import FeatureSnapshot
from atlas.registry import ModelRegistry, build_engine, build_session_factory
from atlas.registry.base import Base
import atlas.registry.models  # noqa: F401
from atlas.training import TrainingPipeline, synthesize_training_set


@pytest.fixture
def training_matrix() -> np.ndarray:
    return synthesize_training_set(n_samples=400, seed=11)


@pytest.fixture
def feature_count() -> int:
    return len(FEATURE_NAMES)


@pytest.fixture
def fresh_match_id() -> UUID:
    return uuid4()


@pytest.fixture
def synthetic_snapshot(fresh_match_id: UUID) -> FeatureSnapshot:
    return FeatureSnapshot(
        match_id=fresh_match_id,
        ts=datetime.now(timezone.utc),
        schema_version=1,
        features={n: 0.5 for n in FEATURE_NAMES},
    ).with_defaults()


@pytest.fixture
async def registry_factory():
    """Creates a fresh SQLite-backed ModelRegistry per test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    url = f"sqlite+aiosqlite:///{path}"

    # SQLite doesn't understand the `atlas` schema clause from the ORM
    # models, so we patch table args at runtime for the test session.
    for tbl in Base.metadata.tables.values():
        tbl.schema = None

    engine = build_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = build_session_factory(engine)
    try:
        yield ModelRegistry(sf)
    finally:
        await engine.dispose()
        try:
            os.unlink(path)
        except OSError:
            pass


@pytest.fixture
async def training_pipeline(registry_factory: ModelRegistry):
    """Pipeline writing artifacts to a temp dir; uses registry_factory."""
    artifact_dir = tempfile.mkdtemp(prefix="atlas-test-")
    yield TrainingPipeline(
        registry=registry_factory,
        artifact_dir=artifact_dir,
        feature_schema_version=1,
    )


# Required by pytest-asyncio when using asyncio fixtures in a module.
@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()
