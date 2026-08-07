"""Re-run club resolution over the validated lake, in place.

    validated/**/*.jsonl  →  resolve_club(team.name)  →  validated/**/*.jsonl

WHY THIS EXISTS. A club_id in the lake is whatever `explorer.clubs` decided
at collection time. When the resolver changes — a fixed rule, a new alias, a
club added to the registry — every record written before the change still
carries the old answer, and nothing downstream can tell. The names are still
there, so the resolution can simply be redone.

WHAT PROMPTED IT. The token-subset fallback accepted three-letter short
names, so `Ath Madrid` (Atlético Madrid, in Football-Data's abbreviated
style) resolved to `athletic_bilbao` via the code ATH — 76 matches filed
under a club in another city. `RCD Espanyol de Barcelona` resolved to
`barcelona` because Espanyol was not in the registry at all. Neither reached
the review queue: a wrong club_id looks exactly like a right one.

RAW NAMES ARE NEVER TOUCHED. Only `club_id` is rewritten, from `name`. That
keeps this replayable: run it again after the next registry change and it
recomputes from the same source text rather than from its own output.

    python -m scripts.reresolve_clubs --dry-run
    python -m scripts.reresolve_clubs
    python -m scripts.reresolve_clubs --competition la_liga
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from explorer.clubs import resolve_club

_TEAM_FIELDS = ("home_team", "away_team")


def _lake_root() -> Path:
    return Path(os.environ.get("EXPLORER_DATA_LAKE", "/home/insight/data/explorer"))


def _reresolve(envelope: dict, changes: Counter, unresolved: Counter) -> bool:
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        return False
    touched = False
    for field in _TEAM_FIELDS:
        team = payload.get(field)
        if not isinstance(team, dict):
            continue
        name = team.get("name")
        if not name:
            continue
        before = team.get("club_id")
        after = resolve_club(str(name))
        if after is None:
            # Left as-is rather than nulled: an unresolvable name today may
            # be a registry gap, and discarding a previously resolved id
            # would lose information this script cannot recover.
            unresolved[str(name)] += 1
            continue
        if after != before:
            team["club_id"] = after
            changes[f"{before} -> {after}"] += 1
            touched = True
    return touched


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--competition")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = _lake_root() / "validated"
    if not root.exists():
        print(f"lake ausente: {root}")
        return 1

    changes: Counter = Counter()
    unresolved: Counter = Counter()
    files_rewritten = records = 0

    for path in sorted(root.rglob("*.jsonl")):
        parts = path.relative_to(root).parts
        if args.competition and (not parts or parts[0] != args.competition):
            continue

        lines_out: list[str] = []
        file_touched = False
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                records += 1
                envelope = json.loads(line)
                if _reresolve(envelope, changes, unresolved):
                    file_touched = True
                lines_out.append(json.dumps(envelope, ensure_ascii=False))

        if file_touched and not args.dry_run:
            # Written to a sibling and moved into place: a crash mid-write
            # would otherwise leave a truncated file where the lake's source
            # of truth used to be.
            temporary = path.with_suffix(".jsonl.tmp")
            temporary.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
            temporary.replace(path)
        if file_touched:
            files_rewritten += 1

    verb = "seriam reescritos" if args.dry_run else "reescritos"
    print(f"registros lidos: {records}")
    print(f"arquivos {verb}: {files_rewritten}")
    print(f"club_ids corrigidos: {sum(changes.values())}")
    for transition, count in changes.most_common():
        print(f"  {count:6}  {transition}")
    if unresolved:
        print(f"\nnomes sem resolucao ({len(unresolved)} distintos, club_id preservado):")
        for name, count in unresolved.most_common(20):
            print(f"  {count:6}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
