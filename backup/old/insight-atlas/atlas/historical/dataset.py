"""Historical dataset builder for real football history.

The builder accepts canonical historical rows that have already been
resolved through the catalogues. It performs temporal splitting only,
records dataset lineage, and refuses to emit supervised labels unless
the row carries real historical labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID

import numpy as np

from atlas.features.definitions import FEATURE_NAMES, defaults
from atlas.registry.models import LabelSource


CONTEXT_LABEL_TO_ID = {
    "balanced": 0,
    "late_pressure": 1,
    "high_volatility": 2,
    "high_engagement": 3,
}


@dataclass(frozen=True)
class HistoricalDatasetRow:
    match_id: UUID
    competition_id: UUID | None
    event_ts: datetime
    features: dict[str, float]
    provider: str
    label: str | None = None
    relevance: int | None = None

    def vector(self) -> list[float]:
        d = defaults()
        d.update({k: float(v) for k, v in self.features.items() if k in d})
        return [float(d[name]) for name in FEATURE_NAMES]


@dataclass(frozen=True)
class DatasetSplit:
    rows: list[HistoricalDatasetRow]

    @property
    def X(self) -> np.ndarray:
        return np.asarray([r.vector() for r in self.rows], dtype=float)

    @property
    def classifier_y(self) -> np.ndarray | None:
        labels: list[int] = []
        for row in self.rows:
            if row.label is None:
                return None
            if row.label not in CONTEXT_LABEL_TO_ID:
                raise ValueError(f"unknown historical label: {row.label}")
            labels.append(CONTEXT_LABEL_TO_ID[row.label])
        return np.asarray(labels, dtype=int)

    @property
    def relevance_y(self) -> np.ndarray | None:
        values: list[int] = []
        for row in self.rows:
            if row.relevance is None:
                return None
            values.append(int(max(0, min(4, row.relevance))))
        return np.asarray(values, dtype=int)

    @property
    def match_ids(self) -> list[UUID]:
        return [r.match_id for r in self.rows]


@dataclass(frozen=True)
class HistoricalDataset:
    version: str
    created_at: datetime
    feature_schema_version: int
    historical_window: tuple[datetime, datetime]
    provider_composition: dict[str, int]
    splits: dict[str, DatasetSplit]
    metadata: dict

    @property
    def train(self) -> DatasetSplit:
        return self.splits["train"]

    @property
    def validation(self) -> DatasetSplit:
        return self.splits["validation"]

    @property
    def test(self) -> DatasetSplit:
        return self.splits["test"]


class HistoricalDatasetBuilder:
    def __init__(
        self,
        *,
        feature_schema_version: int,
        train_until_year: int,
        validation_year: int,
        test_year: int,
    ) -> None:
        self._schema = feature_schema_version
        self._train_until_year = train_until_year
        self._validation_year = validation_year
        self._test_year = test_year

    def build(self, rows: list[HistoricalDatasetRow]) -> HistoricalDataset:
        if not rows:
            raise ValueError("historical dataset requires real rows")
        ordered = sorted(rows, key=lambda r: r.event_ts)
        splits = {"train": [], "validation": [], "test": []}
        for row in ordered:
            y = row.event_ts.astimezone(timezone.utc).year
            if y <= self._train_until_year:
                splits["train"].append(row)
            elif y == self._validation_year:
                splits["validation"].append(row)
            elif y == self._test_year:
                splits["test"].append(row)
        if not splits["train"] or not splits["validation"] or not splits["test"]:
            raise ValueError("temporal split produced an empty train/validation/test set")

        provider_composition: dict[str, int] = {}
        for row in ordered:
            provider_composition[row.provider] = provider_composition.get(row.provider, 0) + 1

        start = ordered[0].event_ts.astimezone(timezone.utc)
        end = ordered[-1].event_ts.astimezone(timezone.utc)
        version = self._version(ordered, start, end)
        return HistoricalDataset(
            version=version,
            created_at=datetime.now(timezone.utc),
            feature_schema_version=self._schema,
            historical_window=(start, end),
            provider_composition=provider_composition,
            splits={k: DatasetSplit(v) for k, v in splits.items()},
            metadata={
                "sample_count": len(ordered),
                "feature_names": list(FEATURE_NAMES),
                "label_source": self.label_source(ordered).value,
                "split_policy": {
                    "train": f"<= {self._train_until_year}",
                    "validation": str(self._validation_year),
                    "test": str(self._test_year),
                },
            },
        )

    @staticmethod
    def label_source(rows: list[HistoricalDatasetRow]) -> LabelSource:
        if rows and all(r.label is not None for r in rows):
            return LabelSource.historical_outcome
        return LabelSource.none

    def _version(
        self, rows: list[HistoricalDatasetRow], start: datetime, end: datetime
    ) -> str:
        h = sha256()
        h.update(str(self._schema).encode())
        h.update(start.isoformat().encode())
        h.update(end.isoformat().encode())
        for row in rows:
            h.update(str(row.match_id).encode())
            h.update(row.event_ts.isoformat().encode())
        return f"hist-{start.date()}-{end.date()}-{h.hexdigest()[:12]}"
