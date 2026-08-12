"""ModelRegistry.promote() coverage — previously untested (the
`registry_factory` fixture in conftest.py had zero test consumers).
Covers the archive-then-activate behavior and the family-scoped lock
key mapping added to close the concurrent-promote race window."""

from __future__ import annotations

import uuid

from atlas.registry.models import ModelFamily, ModelStage
from atlas.registry.repo import _FAMILY_LOCK_KEY


def test_family_lock_key_covers_every_model_family():
    # Would silently skip locking for a new family if this drifts.
    assert set(_FAMILY_LOCK_KEY) == set(ModelFamily)
    assert len(set(_FAMILY_LOCK_KEY.values())) == len(ModelFamily)  # all distinct


async def _register(registry, *, family=ModelFamily.classifier, semver="1.0.0"):
    return await registry.register(
        family=family, semver=semver, artifact_path="/tmp/x.pkl",
        feature_schema_version=2, train_metric=0.9, feature_importance={},
    )


async def test_promote_archives_previous_active_for_same_family(registry_factory):
    registry = registry_factory
    v1 = await _register(registry, semver="1.0.0")
    v2 = await _register(registry, semver="2.0.0")

    promoted_v1 = await registry.promote(v1.id)
    assert promoted_v1.stage == ModelStage.active
    assert (await registry.get_active(ModelFamily.classifier)).id == v1.id

    promoted_v2 = await registry.promote(v2.id)
    assert promoted_v2.stage == ModelStage.active
    active = await registry.get_active(ModelFamily.classifier)
    assert active.id == v2.id  # v2 is now the only active version

    versions = await registry.list_versions(ModelFamily.classifier)
    by_id = {v.id: v for v in versions}
    assert by_id[v1.id].stage == ModelStage.archived  # v1 was archived, not left active


async def test_promote_already_active_is_idempotent(registry_factory):
    registry = registry_factory
    v1 = await _register(registry)
    await registry.promote(v1.id)
    result = await registry.promote(v1.id)  # promote again, already active
    assert result.stage == ModelStage.active
    assert result.id == v1.id


async def test_promote_unknown_version_returns_none(registry_factory):
    registry = registry_factory
    assert await registry.promote(uuid.uuid4()) is None


async def test_promote_does_not_affect_other_families(registry_factory):
    registry = registry_factory
    classifier_v1 = await _register(registry, family=ModelFamily.classifier)
    anomaly_v1 = await _register(registry, family=ModelFamily.anomaly)

    await registry.promote(classifier_v1.id)
    await registry.promote(anomaly_v1.id)

    assert (await registry.get_active(ModelFamily.classifier)).id == classifier_v1.id
    assert (await registry.get_active(ModelFamily.anomaly)).id == anomaly_v1.id
