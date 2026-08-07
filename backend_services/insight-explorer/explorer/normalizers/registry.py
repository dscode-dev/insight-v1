"""Source → normalizer dispatch. Keeps the pipeline source-agnostic: the
Normalize node calls `normalize_artifact`, which routes by `artifact.source`.
"""

from __future__ import annotations

from typing import Any, Callable

from explorer.adapters.base import RawArtifact
from explorer.normalizers import api_football as api_football_norm
from explorer.normalizers import espn as espn_norm
from explorer.normalizers import fbref as fbref_norm
from explorer.normalizers import football_data as fd_norm
from explorer.normalizers import odds_api as odds_api_norm
from explorer.normalizers import openfootball as openfootball_norm
from explorer.normalizers import statsbomb as statsbomb_norm
from explorer.normalizers.espn import NormalizationError

_NORMALIZERS: dict[str, Callable[[RawArtifact], dict[str, Any]]] = {
    "espn": espn_norm.normalize,
    "football_data": fd_norm.normalize,
    "fbref": fbref_norm.normalize,
    "openfootball": openfootball_norm.normalize,
    "statsbomb": statsbomb_norm.normalize,
    "api_football": api_football_norm.normalize,
    "odds_api": odds_api_norm.normalize,
}


def normalize_artifact(artifact: RawArtifact) -> dict[str, Any]:
    fn = _NORMALIZERS.get(artifact.source)
    if fn is None:
        raise NormalizationError(f"no normalizer registered for source {artifact.source!r}")
    return fn(artifact)
