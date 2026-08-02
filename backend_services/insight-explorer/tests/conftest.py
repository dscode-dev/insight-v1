"""Pytest fixtures. Helpers live in `_helpers.py` (imported bare to avoid a
`tests` package-name collision on a shared rootdir)."""

from __future__ import annotations

import pytest
from _helpers import sample_artifacts as _sample_artifacts


@pytest.fixture
def sample_artifacts():
    return _sample_artifacts()
