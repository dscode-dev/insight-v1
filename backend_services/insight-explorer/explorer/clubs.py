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


@lru_cache(maxsize=1)
def _subset_index() -> tuple[tuple[frozenset[str], str], ...]:
    """The keys the token-subset fallback is allowed to match, longest first.

    SHORT NAMES ARE EXCLUDED. They are three-letter codes — ATH, BAR, MIL —
    and 194 of the registry's 219 entries have one. As a subset rule, a
    three-letter token matches any name that happens to contain it, which is
    how `Ath Madrid` (Atlético Madrid, in football-data.co.uk's abbreviated
    style) resolved to `athletic_bilbao` via ATH: 76 real matches filed under
    a club in a different city. A code identifies a club only when it IS the
    whole name, so it stays in `_index` — reachable by exact match, never by
    containment.
    """
    data = json.loads(_registry_path().read_text("utf-8"))
    keys: dict[str, str] = {}
    for club in data["clubs"]:
        cid = club["club_id"]
        for n in [club.get("name"), cid.replace("_", " "), *club.get("aliases", [])]:
            if not n:
                continue
            key = _normalize(n)
            if key:
                keys.setdefault(key, cid)
    # Longest first so the most specific key wins: "real betis" beats "betis"
    # for `Real Betis Balompié`, rather than whichever dict order reached first.
    return tuple(
        (frozenset(key.split()), cid)
        for key, cid in sorted(keys.items(), key=lambda kv: -len(kv[0].split()))
    )


def resolve_club(name: str) -> str | None:
    """Return the canonical club_id, or None if the name cannot be resolved
    deterministically (the caller then opens an entity-resolution path)."""
    if not name:
        return None
    idx = _index()
    key = _normalize(name)
    if key in idx:
        return idx[key]

    tokens = set(key.split())
    if not tokens:
        return None

    # Token-subset fallback, for source spellings that decorate a registry
    # name rather than replace it ("Real Betis Balompié" → real_betis).
    candidates = [(len(rtokens), cid) for rtokens, cid in _subset_index()
                  if rtokens <= tokens]
    if not candidates:
        return None

    # AMBIGUITY IS A REFUSAL, NOT A COIN FLIP. `RCD Espanyol de Barcelona`
    # contains "barcelona", and before Espanyol was in the registry that is
    # what it resolved to — 58 matches of Barcelona's city rival folded into
    # Barcelona's history, silently, because the loop returned its first hit.
    # When two clubs are equally good explanations of a name, neither is
    # established: None sends it to the review queue, where a human decides.
    best = candidates[0][0]
    winners = {cid for size, cid in candidates if size == best}
    return winners.pop() if len(winners) == 1 else None


def registry_size() -> int:
    return len(json.loads(_registry_path().read_text("utf-8"))["clubs"])
