"""Artifact persistence — wraps joblib for the model wrappers.

Atlas writes one file per (family, version_id). The registry stores the
path; this module owns serialisation. Atomic write: serialise to a
temp file, fsync, then rename.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import joblib


def save_artifact(directory: str, *, family: str, version_id: str, payload: dict[str, Any]) -> str:
    Path(directory).mkdir(parents=True, exist_ok=True)
    final = Path(directory) / f"{family}_{version_id}.joblib"
    with tempfile.NamedTemporaryFile(
        dir=directory, prefix=f"{family}_{version_id}_", suffix=".tmp", delete=False
    ) as tmp:
        joblib.dump(payload, tmp)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = tmp.name
    os.replace(tmp_path, final)
    return str(final)


def load_artifact(path: str) -> dict[str, Any]:
    return joblib.load(path)
