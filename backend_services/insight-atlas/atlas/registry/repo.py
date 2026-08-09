"""ModelRegistry — narrow API over the registry tables."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.registry.models import (
    LabelSource,
    ModelFamily,
    ModelStage,
    ModelVersion,
    TrainingRun,
)

logger = logging.getLogger(__name__)

# Fixed, stable mapping (not Python's hash() — randomized per-process by
# PYTHONHASHSEED) for pg_advisory_xact_lock's bigint key, one per family.
_FAMILY_LOCK_KEY: dict[ModelFamily, int] = {
    family: index for index, family in enumerate(ModelFamily)
}


class ModelRegistry:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ---- versions -------------------------------------------------------

    async def register(
        self,
        *,
        family: ModelFamily,
        semver: str,
        artifact_path: str,
        feature_schema_version: int,
        train_metric: float | None,
        feature_importance: dict,
        notes: str = "",
        label_source: LabelSource = LabelSource.none,
        dataset_version: str = "",
        historical_window: dict | None = None,
        dataset_metadata: dict | None = None,
    ) -> ModelVersion:
        async with self._sf() as session:
            version = ModelVersion(
                family=family,
                semver=semver,
                stage=ModelStage.staged,
                artifact_path=artifact_path,
                feature_schema_version=feature_schema_version,
                train_metric=train_metric,
                feature_importance=feature_importance,
                notes=notes,
                label_source=label_source,
                dataset_version=dataset_version,
                historical_window=historical_window or {},
                dataset_metadata=dataset_metadata or {},
            )
            session.add(version)
            await session.commit()
            await session.refresh(version)
            return version

    async def get_active(self, family: ModelFamily) -> ModelVersion | None:
        async with self._sf() as session:
            stmt = select(ModelVersion).where(
                ModelVersion.family == family,
                ModelVersion.stage == ModelStage.active,
            )
            return (await session.execute(stmt)).scalar_one_or_none()

    async def promote(self, version_id: UUID) -> ModelVersion | None:
        """Move the given version to `active`. Archives whatever was
        previously active for the same family. Idempotent.

        Archive-then-activate is two statements, not one atomic step —
        under READ COMMITTED, two concurrent promote() calls for the
        SAME family can each observe "I'm the only active version" and
        both end up `active` (the archive UPDATE's WHERE clause only
        re-checks rows it already locked, never rows that became
        `active` after its scan started — see the regression test for
        the exact interleaving). A postgres advisory xact lock keyed on
        the family serializes the whole critical section; the unique
        partial index from migration 0019 is the database-level
        backstop if this is ever bypassed (fails loud, not silently).
        No-ops on sqlite (tests) — advisory locks are postgres-only, and
        sqlite's own single-writer file locking already prevents this
        specific interleaving for the sequential test suite.
        """
        async with self._sf() as session:
            target = await session.get(ModelVersion, version_id)
            if target is None:
                return None
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": _FAMILY_LOCK_KEY[target.family]},
                )
                # session.get() above is identity-map cached — it would
                # NOT re-query even if called again. Force a fresh read
                # of `target`'s current state now that the lock is held,
                # so a concurrent promote() that ran (and committed)
                # while we were waiting on the lock is actually observed.
                await session.refresh(target)
            if target.stage == ModelStage.active:
                return target
            # Archive prior active.
            await session.execute(
                update(ModelVersion)
                .where(
                    ModelVersion.family == target.family,
                    ModelVersion.stage == ModelStage.active,
                )
                .values(stage=ModelStage.archived)
            )
            target.stage = ModelStage.active
            await session.commit()
            await session.refresh(target)
            return target

    async def list_versions(
        self, family: ModelFamily, *, limit: int = 10
    ) -> list[ModelVersion]:
        async with self._sf() as session:
            stmt = (
                select(ModelVersion)
                .where(ModelVersion.family == family)
                .order_by(ModelVersion.created_at.desc())
                .limit(limit)
            )
            return list((await session.execute(stmt)).scalars().all())

    # ---- training runs --------------------------------------------------

    async def start_run(
        self, *, family: ModelFamily, feature_schema_version: int
    ) -> TrainingRun:
        async with self._sf() as session:
            run = TrainingRun(
                family=family, feature_schema_version=feature_schema_version
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)
            return run

    async def finish_run(
        self,
        run_id: UUID,
        *,
        version_id: UUID | None,
        succeeded: bool,
        sample_count: int,
        metrics: dict,
        error: str = "",
    ) -> TrainingRun | None:
        async with self._sf() as session:
            run = await session.get(TrainingRun, run_id)
            if run is None:
                return None
            run.finished_at = datetime.now(timezone.utc)
            run.succeeded = succeeded
            run.version_id = version_id
            run.sample_count = sample_count
            run.metrics = metrics
            run.error = error[:2048]
            await session.commit()
            await session.refresh(run)
            return run
