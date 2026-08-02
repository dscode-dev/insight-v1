"""Confidence-combination policies.

Sprint 0.1 introduces a third confidence axis (`source_confidence`)
alongside the existing two (`feature_quality` ≅ model's own
`context_confidence`, `data_confidence`). The example combination
from the spec is the product of the three. But the spec also says:

    "Do NOT hardcode formulas. Create extension points for future
     weighting policies."

So combination lives behind a `ConfidencePolicy` protocol. The default
shipped here is `ConservativeProductPolicy`:

    final = feature_quality
            × _reduce(source_confidence_dict)
            × data_confidence

where `_reduce` is configurable (default: min — the chain is only as
strong as its weakest source). A future policy can swap in a weighted
geometric mean, a learned combiner, anything.

The policy NEVER mutates inputs — pure function over scalars + dicts.
The engine calls `policy.combine(...)` once per ContextOutput.
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable


def _reduce_min(source_confidence: dict[str, float]) -> float:
    """Default reducer over the source_confidence dict.

    Empty dict → 1.0 (no source-side information available; don't
    penalize the final score for the absence of data we never had).
    This is the SAFEST conservative default when paired with the
    quarantine layer — anything truly missing should have been
    quarantined before reaching here.
    """
    if not source_confidence:
        return 1.0
    return min(source_confidence.values())


@runtime_checkable
class ConfidencePolicy(Protocol):
    """Pluggable strategy for combining the three confidence signals.

    `feature_quality` — the model's own confidence in its output
                        (e.g. classifier softmax peak, anomaly score
                        normalised against training envelope). What
                        Atlas today calls `context_confidence`.

    `source_confidence` — dict of `source_id → trust`. Policy decides
                          how to reduce it to a scalar (min/mean/
                          weighted/etc).

    `data_confidence` — fraction of features that came from real
                        upstream data (vs registry-default imputed).
    """

    def combine(
        self,
        *,
        feature_quality: float,
        source_confidence: dict[str, float],
        data_confidence: float,
    ) -> float: ...


class ConservativeProductPolicy:
    """Default policy — multiplicative combination, conservative reducer.

    Why product: each axis is interpretable as "fraction of trust" and
    they're (assumed) statistically independent. A 0.9 model over 0.5
    source over 0.8 data ⇒ 0.36 final — captures the intuition that
    none of those signals can "carry" the others.

    Why min as the default source reducer: see `_reduce_min`.

    Reducer is injectable so test fixtures + future policies can swap
    in mean / weighted-mean / learned-combiner without subclassing.
    """

    def __init__(
        self,
        *,
        source_reducer: Callable[[dict[str, float]], float] = _reduce_min,
    ) -> None:
        self._source_reducer = source_reducer

    def combine(
        self,
        *,
        feature_quality: float,
        source_confidence: dict[str, float],
        data_confidence: float,
    ) -> float:
        # Defensive clamp — callers MAY pass slightly out-of-range
        # floats due to numerical noise (e.g. classifier softmax
        # 1.0000002). Clamp before multiplying.
        fq = max(0.0, min(1.0, float(feature_quality)))
        dc = max(0.0, min(1.0, float(data_confidence)))
        sc = max(0.0, min(1.0, float(self._source_reducer(source_confidence))))
        return fq * sc * dc


# Module-level default instance — the engine and tests use this unless
# they swap in their own. Constructed once because it's stateless.
DEFAULT_POLICY: ConfidencePolicy = ConservativeProductPolicy()
