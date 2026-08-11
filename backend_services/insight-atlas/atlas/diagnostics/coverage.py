"""Which blocks of a match record actually exist in the data we hold.

WHAT THIS IS FOR. The v2 ingestion contract will demand complete records —
no field silently absent, because a missing field is how wrong data gets in.
That rule has a price, and the price is measurable: every block a record
lacks is a match the Atlas would refuse.

This counts that price before the rule is written. It reads BOTH lake layers,
because the answer differs sharply between them: `validated/` is what Atlas
consumes today and carries no odds at all, while `raw/` holds 28.012 odds
snapshots and 3.800 statistics lines that never crossed over.

Matches are counted by their real identity — competition, season, home, away,
kickoff day — never by a source's own row id. Three sources describing one
game are one match here, the same rule `atlas.intelligence.corpus` applies.
"""

from __future__ import annotations

import glob
import json
from collections import defaultdict
from dataclasses import dataclass, field

#: The blocks a complete record would carry. `core` is what the corpus reader
#: requires today; the rest is what the dead vector dimensions are waiting on.
BLOCKS = ("core", "market", "stats")


@dataclass
class CoverageReport:
    #: (competition, season) → block → number of distinct matches holding it.
    by_season: dict[tuple[str, str], dict[str, int]] = field(default_factory=dict)
    total_matches: int = 0
    blocks: dict[str, int] = field(default_factory=dict)
    #: Matches holding every block — what a strict contract would keep.
    complete: int = 0
    #: Blocks we hold but that only attach to a match through a source's own
    #: fixture id. Counted apart from `blocks` — see measure_coverage.
    side_files: dict[str, int] = field(default_factory=dict)
    #: Lines still in the producing source's own shape (a football-data CSV
    #: row, say). NOT malformed — they simply have not been normalised yet,
    #: and calling them broken would hide that the data is right there.
    source_native: int = 0
    malformed_lines: int = 0

    def as_dict(self) -> dict:
        return {
            "total_matches": self.total_matches,
            "blocks": dict(self.blocks),
            "complete": self.complete,
            "complete_share": (
                round(self.complete / self.total_matches, 4) if self.total_matches else 0.0
            ),
            "side_files": dict(self.side_files),
            "source_native": self.source_native,
            "malformed_lines": self.malformed_lines,
            "by_season": {
                f"{competition}/{season}": counts
                for (competition, season), counts in sorted(self.by_season.items())
            },
        }


def measure_coverage(validated_dir: str, raw_dir: str | None = None) -> CoverageReport:
    """Count distinct matches, and which blocks each one has behind it."""
    report = CoverageReport()
    # identity → set of blocks seen for it
    held: dict[tuple[str, str, str, str, str], set[str]] = defaultdict(set)
    season_of: dict[tuple, tuple[str, str]] = {}

    for line, source_kind in _iter_lines(validated_dir, raw_dir):
        try:
            envelope = json.loads(line)
        except json.JSONDecodeError:
            report.malformed_lines += 1
            continue

        identity = _identity(envelope)
        if identity is None:
            # Not a fixture line (an odds or stats record carries no teams);
            # attach it to its fixture id instead.
            attached = _attach_by_fixture(envelope, source_kind)
            if attached is not None:
                fixture_id, block = attached
                held[("~fixture", fixture_id, "", "", "")].add(block)
            elif _is_source_native(envelope):
                report.source_native += 1
            else:
                report.malformed_lines += 1
            continue

        held[identity].add("core")
        season_of[identity] = (identity[0], identity[1])
        # An odds/stats block carried inline on the fixture itself.
        payload = envelope.get("payload") or {}
        if _has_market(payload):
            held[identity].add("market")
        if _has_stats(payload):
            held[identity].add("stats")

    # Resolve the side-file blocks onto their fixtures. Records keyed by a
    # source's fixture id can only be matched back through that id, which is
    # exactly why the new contract must carry the blocks INLINE — see the
    # module docstring of the ingestion contract.
    by_external: dict[str, set[str]] = defaultdict(set)
    for key, blocks in list(held.items()):
        if key[0] == "~fixture":
            by_external[key[1]] |= blocks
            del held[key]

    real = {k: v for k, v in held.items() if k[0] != "~fixture"}
    report.total_matches = len(real)
    report.blocks = {
        block: sum(1 for blocks in real.values() if block in blocks) for block in BLOCKS
    }
    report.complete = sum(1 for blocks in real.values() if set(BLOCKS) <= blocks)

    per_season: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {block: 0 for block in BLOCKS} | {"total": 0}
    )
    for identity, blocks in real.items():
        bucket = per_season[(identity[0], identity[1])]
        bucket["total"] += 1
        for block in blocks:
            if block in bucket:
                bucket[block] += 1
    report.by_season = dict(per_season)

    # Kept OUT of `blocks`, which is a per-match count. These are side-file
    # records keyed by a source's own fixture id — several per match for
    # odds (one per bookmaker), and collected more than once. Folding them
    # in produced "market: 446% of matches", a number that is not wrong so
    # much as meaningless.
    report.side_files = {
        "market": sum(1 for blocks in by_external.values() if "market" in blocks),
        "stats": sum(1 for blocks in by_external.values() if "stats" in blocks),
    }
    return report


def _iter_lines(validated_dir: str, raw_dir: str | None):
    for path in glob.glob(f"{validated_dir}/**/*.jsonl", recursive=True):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield line, "validated"
    if raw_dir:
        for path in glob.glob(f"{raw_dir}/**/*.jsonl", recursive=True):
            kind = path.replace("\\", "/").split("/")[-2]
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        yield line, kind


def _identity(envelope: dict) -> tuple[str, str, str, str, str] | None:
    # `payload` in the validated layer, `raw` in the raw layer. Reading only
    # the first reported 9.568 perfectly good raw fixtures as malformed —
    # a diagnostic that miscounts is worse than no diagnostic, because the
    # number gets quoted.
    payload = envelope.get("payload") or envelope.get("raw") or {}
    if not isinstance(payload, dict):
        return None
    home = _team(payload.get("home_team"))
    away = _team(payload.get("away_team"))
    scheduled = payload.get("scheduled_at") or payload.get("_date")
    if not (home and away and scheduled):
        return None
    competition = (envelope.get("competition") or {}).get("competition_key") or (
        envelope.get("competition_key") or ""
    )
    season = str(envelope.get("season") or "")
    return (str(competition), season, str(home), str(away), str(scheduled)[:10])


def _is_source_native(envelope: dict) -> bool:
    """A record still in the shape its source published.

    The raw layer keeps football-data's CSV row verbatim — `HomeTeam`,
    `FTHG`, `B365H`, `HS`/`AS`. Reporting those as malformed would be
    exactly backwards: they are the most COMPLETE records in the lake, and
    the reason the market and stats blocks can be filled at all.
    """
    raw = envelope.get("raw")
    return isinstance(raw, dict) and "payload" not in envelope


def _team(value) -> str | None:
    """The team's key, whichever shape the layer wrote it in.

    `validated/` carries an object with `club_id` and `name`; `raw/` often
    carries the bare name as a string. Assuming the object shape raised
    AttributeError on the first raw fixture — worth handling rather than
    excluding, since the raw layer is exactly where the odds live.
    """
    if isinstance(value, dict):
        return value.get("club_id") or value.get("name")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _attach_by_fixture(envelope: dict, source_kind: str) -> tuple[str, str] | None:
    raw = envelope.get("raw") or envelope.get("payload") or {}
    fixture_id = raw.get("_fixture_id") or envelope.get("external_id")
    if not fixture_id:
        return None
    if source_kind == "odds_snapshot" or "selections" in raw:
        return str(fixture_id), "market"
    if source_kind == "stats" or ("home" in raw and "shots" in (raw.get("home") or {})):
        return str(fixture_id), "stats"
    return None


def _has_market(payload: dict) -> bool:
    odds = payload.get("odds") or payload.get("market") or {}
    return bool(odds) and any(
        odds.get(key) for key in ("home", "draw", "away", "selections")
    )


def _has_stats(payload: dict) -> bool:
    stats = payload.get("stats") or payload.get("statistics") or {}
    return bool(stats)
