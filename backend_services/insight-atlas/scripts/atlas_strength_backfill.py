"""Bootstrap atlas.team_strength_state/team_standings_state/
competition_season_state/head_to_head_state from Explorer's validated
fixture lake — a full, forced replay (bypasses StrengthSyncWatcher's
throttle). Run this once before the live team-strength engine goes live
so `_runtime_query` isn't reading cold-start defaults for a lake full of
existing history; the periodic StrengthSyncWatcher takes over keeping
state current after that.

Idempotent: `StrengthRepository.record_result` skips matches already
folded in (`atlas.strength_processed_matches`), so re-running this is
safe and only applies genuinely new results.

Usage:
    python -m scripts.atlas_strength_backfill --database-url <url> --lake-dir <path>

`--lake-dir` must point at Explorer's `validated/` layer specifically
(e.g. `/var/atlas/explorer/validated`), never the lake root — Explorer's
`raw`/`normalized` layers sit alongside it (see
`explorer/config.py::LAKE_LAYERS`) and are not certified/deduplicated.
"""

from __future__ import annotations

import argparse
import asyncio

from atlas.registry import build_engine, build_session_factory
from atlas.strength import StrengthRepository, StrengthSyncWatcher


async def run(args) -> None:
    engine = build_engine(args.database_url)
    repository = StrengthRepository(build_session_factory(engine))
    watcher = StrengthSyncWatcher(repository, args.lake_dir)
    try:
        applied = await watcher.sync(force=True)
        print(f"strength_backfill_complete applied={applied}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--lake-dir", required=True)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
