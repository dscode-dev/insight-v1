"""Republish the lake's validated layer onto the historical stream.

    explorer/validated/**  →  insight:stream:historical  →  Anvil  →  ClickHouse

WHEN TO RUN IT. Whenever the lake holds records ClickHouse does not: the
first time the stream is wired up, after a Redis outage during collection
(the job tickets `historical_publish_failed` and keeps going, because the
lake write already succeeded), or after adding a historical table.

WHY REPUBLISHING IS SAFE. The historical tables are ReplacingMergeTree keyed
by (competition, season, fixture, source), so a record that arrives twice
merges into one row. That is what makes the lake — not the stream — the
source of truth: the stream can be replayed from it at any time.

    python -m scripts.backfill_historical                 # everything
    python -m scripts.backfill_historical --competition premier_league
    python -m scripts.backfill_historical --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterator


def _lake_root() -> Path:
    return Path(os.environ.get("EXPLORER_DATA_LAKE", "/home/insight/data/explorer"))


def _iter_envelopes(
    validated_root: Path,
    competition: str | None,
    season: str | None,
    entity_type: str | None,
) -> Iterator[dict[str, Any]]:
    """Walk validated/{competition}/{season}/{source}/{entity_type}/*.jsonl.

    Streamed line by line rather than loaded: a season of odds is thousands
    of records, and reading a whole competition into memory to publish it
    would make the backfill's footprint scale with the archive.
    """
    if not validated_root.exists():
        return
    for path in sorted(validated_root.rglob("*.jsonl")):
        parts = path.relative_to(validated_root).parts
        if len(parts) < 4:
            continue
        comp, seas, _source, kind = parts[0], parts[1], parts[2], parts[3]
        if competition and comp != competition:
            continue
        if season and seas != season:
            continue
        if entity_type and kind != entity_type:
            continue
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    # One corrupt line must not abandon the file. It is
                    # reported in the summary; the rest still reaches
                    # ClickHouse.
                    yield {"__corrupt__": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--competition")
    parser.add_argument("--season")
    parser.add_argument("--entity-type", choices=["fixture", "stats", "odds_snapshot"])
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true",
                        help="count what would be published, publish nothing")
    args = parser.parse_args()

    validated_root = _lake_root() / "validated"
    print(f"lake: {validated_root}")

    publisher = None
    if not args.dry_run:
        from explorer.datalake.historical_publisher import HistoricalPublisher

        publisher = HistoricalPublisher()

    batch: list[dict[str, Any]] = []
    published = corrupt = skipped = 0
    by_type: dict[str, int] = {}

    def flush() -> None:
        nonlocal published
        if not batch:
            return
        if publisher is not None:
            published += publisher.publish_many(batch)
        else:
            published += len(batch)
        batch.clear()

    for envelope in _iter_envelopes(validated_root, args.competition,
                                    args.season, args.entity_type):
        if envelope.get("__corrupt__"):
            corrupt += 1
            continue
        kind = envelope.get("entity_type")
        if kind not in ("fixture", "stats", "odds_snapshot"):
            skipped += 1
            continue
        by_type[kind] = by_type.get(kind, 0) + 1
        batch.append(envelope)
        if len(batch) >= args.batch_size:
            flush()
    flush()

    verb = "would publish" if args.dry_run else "published"
    print(f"{verb}: {published}")
    for kind, count in sorted(by_type.items()):
        print(f"  {kind:16} {count}")
    if skipped:
        print(f"skipped (no historical table): {skipped}")
    if corrupt:
        print(f"CORRUPT LINES: {corrupt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
