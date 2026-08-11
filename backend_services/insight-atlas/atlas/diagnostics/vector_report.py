"""How much information the vector memory actually carries.

Three readings, each answering a question that was previously answered by
impression:

  DIMENSÕES   — quanto cada posição do vetor distingue uma partida de outra.
  SIMILARIDADE— quão parecidas são duas partidas quaisquer, o que dá a régua
                sem a qual um score de 0.886 não significa nada.
  RECUPERAÇÃO — se os vizinhos devolvidos carregam informação real, medida
                contra a taxa base do corpus.

A CONSTÂNCIA É MEDIDA CONTRA O TERMO DE VIÉS, NÃO CONTRA ZERO. The stored
vectors are L2-normalised, so a component that was identical in every record
before normalisation still varies afterwards — its magnitude rides on the
vector's norm. Dividing by the bias term (fixed at 1.0 pre-normalisation)
undoes exactly that, and a ratio that never moves proves the value never
moved. Reading the raw standard deviation instead reported `line_movement`
as varying across 6.490 distinct values when it is 0.5 in all 7.261 rows.
"""

from __future__ import annotations

import json
import math
import random
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DimensionStat:
    index: int
    name: str
    minimum: float
    maximum: float
    mean: float
    stdev: float
    distinct: int
    #: Constant BEFORE normalisation — carries no information whatsoever.
    constant: bool
    #: The pre-normalisation value, when constant. None otherwise.
    fixed_value: float | None
    #: Index of an earlier dimension holding an identical column, if any.
    duplicate_of: int | None


@dataclass(frozen=True)
class SimilarityStat:
    label: str
    pairs: int
    median: float
    p05: float
    p95: float
    stdev: float
    above_090: float


@dataclass(frozen=True)
class RetrievalStat:
    k: int
    queries: int
    #: Share of queries whose neighbourhood majority matched what happened.
    agreement: float
    #: Always answering the corpus's most common outcome. The honest floor:
    #: a neighbourhood that cannot beat this is describing nothing.
    base_rate: float
    #: Median similarity of the closest neighbour. Near 1.0 means the score
    #: has no room left to distinguish a good match from an ordinary one.
    top_similarity: float

    @property
    def lift(self) -> float:
        return self.agreement - self.base_rate

    @property
    def margin(self) -> float:
        """95% margin of error on `agreement`, from the sample size alone.

        WHY THIS IS PRINTED AND NOT LEFT IMPLICIT. The same corpus answered
        +6.9 points with 120 queries and +5.6 with 400. Neither is wrong;
        the first simply had error bars wide enough to swallow the
        difference. A ruler that reports a number without its precision
        invites the next person to celebrate noise — which is the mistake
        this whole package exists to stop repeating.
        """
        if self.queries <= 0:
            return 0.0
        p = self.agreement
        return 1.96 * math.sqrt(max(p * (1.0 - p), 1e-9) / self.queries)

    @property
    def conclusive(self) -> bool:
        """The lift is larger than the uncertainty around it."""
        return abs(self.lift) > self.margin


@dataclass
class VectorReport:
    embedding_version: str
    rows: int
    dimensions: list[DimensionStat] = field(default_factory=list)
    similarity: list[SimilarityStat] = field(default_factory=list)
    retrieval: list[RetrievalStat] = field(default_factory=list)

    @property
    def constant_count(self) -> int:
        return sum(1 for d in self.dimensions if d.constant)

    @property
    def duplicate_count(self) -> int:
        return sum(1 for d in self.dimensions if d.duplicate_of is not None)

    @property
    def informative_count(self) -> int:
        return len(self.dimensions) - self.constant_count - self.duplicate_count

    def as_dict(self) -> dict:
        return {
            "embedding_version": self.embedding_version,
            "rows": self.rows,
            "dimensions_total": len(self.dimensions),
            "dimensions_constant": self.constant_count,
            "dimensions_duplicate": self.duplicate_count,
            "dimensions_informative": self.informative_count,
            "dimensions": [
                {
                    "index": d.index, "name": d.name, "stdev": round(d.stdev, 6),
                    "distinct": d.distinct, "constant": d.constant,
                    "fixed_value": d.fixed_value, "duplicate_of": d.duplicate_of,
                }
                for d in self.dimensions
            ],
            "similarity": [
                {
                    "label": s.label, "pairs": s.pairs, "median": round(s.median, 4),
                    "p05": round(s.p05, 4), "p95": round(s.p95, 4),
                    "stdev": round(s.stdev, 4), "above_090": round(s.above_090, 4),
                }
                for s in self.similarity
            ],
            "retrieval": [
                {
                    "k": r.k, "queries": r.queries,
                    "agreement": round(r.agreement, 4),
                    "base_rate": round(r.base_rate, 4),
                    "lift": round(r.lift, 4),
                    "margin": round(r.margin, 4),
                    "conclusive": r.conclusive,
                    "top_similarity": round(r.top_similarity, 4),
                }
                for r in self.retrieval
            ],
        }


def measure_dimensions(
    vectors: list[list[float]], names: tuple[str, ...], *, bias_index: int
) -> list[DimensionStat]:
    """Per-position statistics, with constancy judged against the bias term."""
    if not vectors:
        return []
    width = len(vectors[0])
    columns = [[row[i] for row in vectors] for i in range(width)]
    bias = columns[bias_index]

    stats: list[DimensionStat] = []
    seen: dict[tuple, int] = {}
    for index in range(width):
        column = columns[index]
        # The ratio to the bias term. Rounded because both sides carry
        # float noise from the normalisation; without it every row looks
        # like its own value.
        ratios = {
            round(column[k] / bias[k], 6) if bias[k] else 0.0
            for k in range(len(column))
        }
        constant = len(ratios) == 1
        fixed = next(iter(ratios)) if constant else None

        signature = tuple(round(v, 9) for v in column)
        duplicate_of = seen.get(signature)
        if duplicate_of is None:
            seen[signature] = index

        stats.append(
            DimensionStat(
                index=index,
                name=names[index] if index < len(names) else f"dim{index}",
                minimum=min(column),
                maximum=max(column),
                mean=sum(column) / len(column),
                stdev=statistics.pstdev(column),
                distinct=len({round(v, 6) for v in column}),
                constant=constant,
                fixed_value=fixed,
                # A constant column duplicating another constant column is
                # not news — both are already reported as carrying nothing.
                duplicate_of=None if constant else duplicate_of,
            )
        )
    return stats


def measure_similarity(
    vectors: list[list[float]],
    *,
    label: str,
    pairs: int = 60_000,
    sample: int = 1_200,
    seed: int = 7,
) -> SimilarityStat:
    """Cosine similarity between randomly drawn pairs.

    This is the ruler. Without it a reported score is a number with no
    scale: 0.886 sounds high and sits near the 65th percentile of random
    pairs in the August 2026 corpus.
    """
    rng = random.Random(seed)
    pool = vectors if len(vectors) <= sample else rng.sample(vectors, sample)
    if len(pool) < 2:
        return SimilarityStat(label, 0, 0.0, 0.0, 0.0, 0.0, 0.0)

    scores: list[float] = []
    for _ in range(pairs):
        left, right = rng.randrange(len(pool)), rng.randrange(len(pool))
        if left == right:
            continue
        scores.append(_dot(pool[left], pool[right]))
    scores.sort()

    def percentile(fraction: float) -> float:
        return scores[int(fraction * (len(scores) - 1))]

    return SimilarityStat(
        label=label,
        pairs=len(scores),
        median=percentile(0.5),
        p05=percentile(0.05),
        p95=percentile(0.95),
        stdev=statistics.pstdev(scores),
        above_090=sum(1 for s in scores if s > 0.90) / len(scores),
    )


def measure_retrieval(
    entries: list[tuple[str, str, list[float]]],
    outcomes: dict[str, str],
    *,
    k_values: tuple[int, ...] = (5, 25),
    queries: int = 400,
    warmup: int = 1_500,
    seed: int = 11,
) -> list[RetrievalStat]:
    """Do the retrieved neighbours carry information about what happened?

    NOT A PREDICTOR, AND MUST NOT BECOME ONE. Atlas is descriptive by
    charter. This asks a validity question: if the most similar prior
    matches ended the same way no more often than the corpus's own base
    rate, then the similarity is describing nothing, and the neighbours
    shown in a post are decoration.

    `entries` must be ordered oldest first — each query only sees matches
    that came BEFORE it, so nothing leaks backwards through the walk-forward
    features.
    """
    usable = [(uid, vector) for _, uid, vector in entries if uid in outcomes]
    if len(usable) <= warmup + 10:
        return []

    counts = Counter(outcomes[uid] for uid, _ in usable)
    base_rate = counts.most_common(1)[0][1] / len(usable)

    rng = random.Random(seed)
    targets = rng.sample(
        range(warmup, len(usable)), min(queries, len(usable) - warmup)
    )

    results: list[RetrievalStat] = []
    for k in k_values:
        agreed = 0
        top_scores: list[float] = []
        for index in targets:
            uid, vector = usable[index]
            neighbours = sorted(
                ((_dot(vector, other), other_uid)
                 for other_uid, other in usable[:index]),
                reverse=True,
            )[:k]
            if not neighbours:
                continue
            top_scores.append(neighbours[0][0])
            vote = Counter(
                outcomes[n_uid] for _, n_uid in neighbours
            ).most_common(1)[0][0]
            if vote == outcomes[uid]:
                agreed += 1
        top_scores.sort()
        results.append(
            RetrievalStat(
                k=k,
                queries=len(targets),
                agreement=agreed / len(targets),
                base_rate=base_rate,
                top_similarity=top_scores[len(top_scores) // 2] if top_scores else 0.0,
            )
        )
    return results


def load_outcomes(matches_path: Path) -> dict[str, str]:
    """uid → label, from the published corpus. Empty when it is absent —
    the retrieval reading is then skipped rather than faked."""
    if not matches_path.exists():
        return {}
    outcomes: dict[str, str] = {}
    with matches_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            uid, label = record.get("uid"), record.get("label")
            if uid and label:
                outcomes[str(uid)] = str(label)
    return outcomes


def standardise(vectors: list[list[float]], keep: list[int]) -> list[list[float]]:
    """Centre and rescale the kept dimensions, then re-normalise.

    Offered as a COMPARISON, not applied to anything stored. The August 2026
    measurement showed the stored layout (every component in [0, 1] plus a
    fixed bias) puts every vector in the same positive orthant, which caps
    how far apart any two can be — random pairs sat at 0.807. Centring moves
    that to roughly zero and triples the spread. Keeping the transform here
    lets the next encoder be argued against a number instead of a hunch.
    """
    if not vectors:
        return []
    subset = [[row[i] for i in keep] for row in vectors]
    width = len(keep)
    means = [sum(r[c] for r in subset) / len(subset) for c in range(width)]
    devs = [statistics.pstdev([r[c] for r in subset]) or 1.0 for c in range(width)]
    return [
        _normalise([(row[c] - means[c]) / devs[c] for c in range(width)])
        for row in subset
    ]


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _normalise(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values] if norm > 1e-12 else values
