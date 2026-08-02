"""Historical dataset file loaders.

The JSONL format is intentionally explicit and canonical. Each row must
represent a real historical observation after provider import/catalogue
resolution; the loader does not synthesize missing labels or features.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from atlas.historical.dataset import HistoricalDatasetRow


def load_historical_rows_jsonl(path: str | Path) -> list[HistoricalDatasetRow]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"historical dataset file not found: {p}")
    rows: list[HistoricalDatasetRow] = []
    with p.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                rows.append(_row(payload))
            except Exception as exc:
                raise ValueError(f"invalid historical row at {p}:{lineno}: {exc}") from exc
    if not rows:
        raise ValueError(f"historical dataset file is empty: {p}")
    return rows


def _row(payload: dict) -> HistoricalDatasetRow:
    return HistoricalDatasetRow(
        match_id=UUID(str(payload["match_id"])),
        competition_id=(
            UUID(str(payload["competition_id"]))
            if payload.get("competition_id")
            else None
        ),
        event_ts=datetime.fromisoformat(str(payload["event_ts"]).replace("Z", "+00:00")),
        features={str(k): float(v) for k, v in dict(payload["features"]).items()},
        provider=str(payload["provider"]),
        label=payload.get("label"),
        relevance=payload.get("relevance"),
    )
