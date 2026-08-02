"""Historical similarity — cosine similarity over feature vectors.

Stored as a numpy array of past snapshots + their match_ids. Inference
returns the top-K most similar matches with the similarity score and
the features they share most strongly with the query.

For V1 this is in-process and fits ≤ 10k matches comfortably in memory.
When the corpus grows past that, FAISS or an HNSW index is the next
step — same interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import numpy as np

from atlas.features.definitions import FEATURE_NAMES


@dataclass
class SimilarMatch:
    match_id: UUID
    similarity: float
    shared_factors: list[tuple[str, float]]


class SimilarityIndex:
    def __init__(self, *, ids: list[UUID], matrix: np.ndarray) -> None:
        if matrix.ndim != 2 or matrix.shape[1] != len(FEATURE_NAMES):
            raise ValueError("matrix must match feature schema")
        if matrix.shape[0] != len(ids):
            raise ValueError("ids and matrix rows must align")
        self.ids = list(ids)
        self.matrix = matrix
        # Precompute L2 norms for cosine.
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        # Avoid divide-by-zero — flag zero-norm rows with epsilon.
        norms = np.where(norms < 1e-9, 1e-9, norms)
        self._normalised = matrix / norms

    @classmethod
    def build(cls, samples: list[tuple[UUID, list[float]]]) -> "SimilarityIndex":
        if not samples:
            return cls(ids=[], matrix=np.zeros((0, len(FEATURE_NAMES))))
        ids = [s[0] for s in samples]
        matrix = np.asarray([s[1] for s in samples], dtype=float)
        return cls(ids=ids, matrix=matrix)

    def topk(
        self, x: list[float] | np.ndarray, *, k: int = 5, top_factors: int = 3
    ) -> list[SimilarMatch]:
        if not self.ids:
            return []
        v = np.asarray(x, dtype=float).reshape(1, -1)
        n = np.linalg.norm(v)
        if n < 1e-9:
            return []
        vn = v / n
        sims = (self._normalised @ vn.T).ravel()
        # Take top-k by similarity, descending.
        order = np.argsort(-sims)[: max(1, k)]
        out: list[SimilarMatch] = []
        v_ravel = v.ravel()
        for idx in order:
            i = int(idx)
            other = self.matrix[i]
            # Features whose product (component-wise) is highest — these
            # are the dimensions that contributed most to the similarity.
            product = np.abs(v_ravel) * np.abs(other)
            factors = list(zip(FEATURE_NAMES, [float(p) for p in product]))
            factors.sort(key=lambda kv: kv[1], reverse=True)
            out.append(
                SimilarMatch(
                    match_id=self.ids[i],
                    similarity=float(sims[i]),
                    shared_factors=factors[: max(1, top_factors)],
                )
            )
        return out

    def to_state(self) -> dict:
        return {"ids": [str(i) for i in self.ids], "matrix": self.matrix}

    @classmethod
    def from_state(cls, state: dict) -> "SimilarityIndex":
        return cls(
            ids=[UUID(s) for s in state["ids"]],
            matrix=np.asarray(state["matrix"], dtype=float),
        )
