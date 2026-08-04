"""Deterministic entity resolution against the Insight Club Registry.

This is the *authoritative* resolver: "Man City" / "Manchester City FC" →
`manchester_city`. The CrewAI Entity Resolver agent (Step 7) only proposes
candidates for names this resolver cannot match; it never overrides a
registry hit, and its proposals are never written to validated/ directly.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

# Resolution order: explicit env override → vendored copy bundled in the image
# → dev-tree location (sibling insight-protos checkout). The vendored copy
# makes the container self-contained; a dev checkout without EXPLORER_CLUB_REGISTRY
# set falls back to the sibling repo layout.
_REGISTRY_CANDIDATES = tuple(
    Path(p) for p in (
        os.environ.get("EXPLORER_CLUB_REGISTRY"),
        Path(__file__).resolve().parents[1] / "vendor" / "club_registry.json",
        Path(__file__).resolve().parents[1].parent / "insight-protos/contracts/clubs/club_registry.json",
    ) if p
)

# Common source-name decorations stripped before matching.
_NOISE = re.compile(
    r"\b(futebol clube|football club|f\.?c\.?|e\.?c\.?|s\.?c\.?|a\.?c\.?|"
    r"clube de regatas|esporte clube|associacao|club|cf|cd|afc|sc|ec|ac)\b",
    re.IGNORECASE,
)


def _normalize(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = _NOISE.sub(" ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@lru_cache(maxsize=1)
def _registry_path() -> Path:
    for p in _REGISTRY_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError("club_registry.json not found in expected locations")


@lru_cache(maxsize=1)
def _index() -> dict[str, str]:
    """normalized-name → club_id, built from name/short_name/aliases."""
    data = json.loads(_registry_path().read_text("utf-8"))
    idx: dict[str, str] = {}
    for club in data["clubs"]:
        cid = club["club_id"]
        names = [club.get("name"), club.get("short_name"), cid.replace("_", " "), *club.get("aliases", [])]
        for n in names:
            if not n:
                continue
            key = _normalize(n)
            if key:
                idx.setdefault(key, cid)
    return idx


def resolve_club(name: str) -> str | None:
    """Return the canonical club_id, or None if the name cannot be resolved
    deterministically (the caller then opens an entity-resolution path)."""
    if not name:
        return None
    idx = _index()
    key = _normalize(name)
    if key in idx:
        return idx[key]
    # token-subset fallback: every registry token present in the input.
    for rkey, cid in idx.items():
        rtokens = set(rkey.split())
        if rtokens and rtokens.issubset(set(key.split())):
            return cid
    return None


def registry_size() -> int:
    return len(json.loads(_registry_path().read_text("utf-8"))["clubs"])
