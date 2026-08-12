"""Trend Intelligence Pipeline — Sprint 1.5 Part 4.

The production flow from detection to publication:

    TrendEngine
        ↓
    TrendLifecycleEngine     (how is each pattern evolving?)
        ↓
    TrendCorrelationEngine   (which patterns co-occur?)
        ↓
    PublishScoreEngine       (is this worth publishing?)
        ↓
    Repository               (EVERY trend persists — full audit trail)
        ↓
    Publisher                (only PUBLISH / PRIORITY_PUBLISH stream;
                              priority flag on the top tier)

Atlas no longer publishes raw detected trends — only evaluated
intelligence, each carrying lifecycle state, correlation context,
publish score and publication tier.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-only: atlas.patterns imports trend/lifecycle models, so a
    # runtime import here would be circular through the package init.
    from atlas.intelligence.enrichment import IntelligenceEnricher
    from atlas.patterns import PatternMemory
    from atlas.trends.timeline import TrendTimelineRepository

from atlas.trends.correlation.engine import TrendCorrelationEngine
from atlas.trends.correlation.models import CorrelatedTrend
from atlas.trends.correlation.repository import CorrelatedTrendRepository
from atlas.trends.engine import TrendEngine
from atlas.trends.interpretation import interpret
from atlas.trends.lifecycle.engine import TrendLifecycleEngine
from atlas.trends.lifecycle.models import TrendInstance, TrendLifecycleState
from atlas.trends.lifecycle.repository import TrendLifecycleRepository
from atlas.trends.models import Trend, TrendInputs
from atlas.trends.publisher import TrendPublisher
from atlas.trends.repository import TrendRepository
from atlas.trends.scoring.engine import (
    PRIORITY_TRENDS_TOTAL,
    PublicationTier,
    PublishScore,
    PublishScoreEngine,
)
from atlas.trends.similarity_probe import OnlineSimilarityProbe

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TrendPipelineResult:
    """Everything one tick produced, for logging + tests."""

    trends: list[Trend] = field(default_factory=list)
    correlations: list[CorrelatedTrend] = field(default_factory=list)
    lifecycle_instances: list[TrendInstance] = field(default_factory=list)
    scores: dict[str, PublishScore] = field(default_factory=dict)
    published: list[Trend] = field(default_factory=list)
    priority_published: list[Trend] = field(default_factory=list)


class TrendIntelligencePipeline:
    def __init__(
        self,
        *,
        engine: TrendEngine,
        lifecycle_engine: TrendLifecycleEngine,
        lifecycle_repository: TrendLifecycleRepository,
        correlation_engine: TrendCorrelationEngine,
        correlation_repository: CorrelatedTrendRepository,
        scoring_engine: PublishScoreEngine,
        trend_repository: TrendRepository,
        publisher: TrendPublisher,
        pattern_memory: PatternMemory | None = None,
        timeline_repository: TrendTimelineRepository | None = None,
        intelligence_enricher: IntelligenceEnricher | None = None,
        similarity_probe: OnlineSimilarityProbe | None = None,
    ) -> None:
        self._engine = engine
        self._lifecycle = lifecycle_engine
        self._lifecycle_repo = lifecycle_repository
        self._correlation = correlation_engine
        self._correlation_repo = correlation_repository
        self._scoring = scoring_engine
        self._trend_repo = trend_repository
        self._publisher = publisher
        self._patterns = pattern_memory
        self._timeline = timeline_repository
        self._enricher = intelligence_enricher
        # ATLAS-VECTOR-B: async online pgvector search, run BEFORE the sync
        # detectors so OracleSimilarityDetector can consume the result.
        self._similarity_probe = similarity_probe

    async def process(
        self, inputs: TrendInputs, *, now: datetime | None = None
    ) -> TrendPipelineResult:
        ts = now or datetime.now(timezone.utc)

        # 0. Online similarity (async) — attach the pgvector result so the sync
        # OracleSimilarityDetector can consume it. Graceful: any probe failure
        # leaves similarity None and the detector simply emits nothing.
        if self._similarity_probe is not None and inputs.similarity is None:
            try:
                probed = await self._similarity_probe.probe(inputs)
            except Exception:
                # Probe isolation: an infrastructure failure (pgvector
                # down, timeout, bad row) must never break detection.
                #
                # BROAD ON PURPOSE. An earlier revision narrowed this to
                # (OSError, RuntimeError, ValueError, TimeoutError) to
                # stop it masking the frozen-dataclass bug described
                # below — but SQLAlchemy/asyncpg errors derive straight
                # from Exception and match NONE of those, so the narrow
                # form let a real database outage escape and kill the
                # whole tick. That is precisely the failure this handler
                # exists to prevent, so breadth wins here.
                #
                # The bug the narrowing was aimed at: `TrendInputs` is a
                # frozen dataclass, so `inputs.similarity = ...` raised
                # FrozenInstanceError (an AttributeError subclass), was
                # swallowed here, and left similarity ALWAYS None —
                # OracleSimilarityDetector returned [] on its first line
                # and historical_similarity/historical_pattern were
                # never emitted in production, while the pgvector query
                # was still paid for on every tick. That class of bug is
                # now prevented BY CONSTRUCTION (`dataclasses.replace`
                # below) and guarded by
                # tests/test_pipeline_similarity_probe.py — which is
                # where programming errors belong, not in an except
                # clause that also has to survive an outage.
                logger.exception(
                    "similarity_probe_failed",
                    extra={"canonical_match_id": str(inputs.canonical_match_id)},
                )
            else:
                # Rebind the local — frozen dataclasses are replaced, not mutated.
                inputs = dataclasses.replace(inputs, similarity=probed)

        # 1. Detect.
        detected = await self._engine.detect(inputs)

        # 2. Lifecycle: evolve instances with this tick's trends +
        # confirmation/failure evidence; persist every touched instance.
        open_instances = await self._lifecycle_repo.open_instances(
            inputs.canonical_match_id
        )
        touched, state_by_trend = self._lifecycle.process(
            open_instances=open_instances,
            trends=detected,
            impact_category=inputs.impact_category,
            now=ts,
        )
        await self._lifecycle_repo.save_many(touched)
        instance_by_trend: dict[str, TrendInstance] = {}
        for inst in touched:
            for tid in inst.trend_ids:
                instance_by_trend[tid] = inst

        # 2b. Pattern memory (A3): fold every terminal instance into the
        # recurrence counters so future ticks can cite history.
        # Isolated: these are OPTIONAL enrichment seams (both are
        # `| None` constructor args). A failure here must never abort
        # the tick before steps 5/6 persist and publish the trends that
        # were already detected — the same isolation every other
        # optional seam in this pipeline already had.
        if self._patterns is not None:
            for inst in touched:
                if inst.current_state.terminal:
                    try:
                        await self._patterns.record_outcome(
                            inst, inputs.competition_id
                        )
                    except Exception:
                        logger.exception(
                            "pattern_memory_record_failed",
                            extra={"instance_id": str(inst.instance_id)},
                        )

        # 2c. Market memory (Maturity 1.5): the same closures land in
        # the append-only outcome log (insert-once; replay-safe).
        if self._enricher is not None:
            try:
                await self._enricher.record_closures(touched, inputs.competition_id)
            except Exception:
                logger.exception(
                    "market_memory_record_closures_failed",
                    extra={"canonical_match_id": str(inputs.canonical_match_id)},
                )

        # 3. Correlation: fusion trends become first-class members of
        # this tick's trend set; member trends learn their correlation ids.
        correlations, fusions, membership = await self._correlation.correlate(
            inputs, detected, now=ts
        )
        for correlated in correlations:
            await self._correlation_repo.record(correlated)
        for fusion in fusions:
            state_by_trend[str(fusion.trend_id)] = TrendLifecycleState.ACTIVE

        # 4. Score + enrich every trend (members + fusions) with the
        # V2 evaluation fields.
        evaluated: list[Trend] = []
        scores: dict[str, PublishScore] = {}
        for trend in [*detected, *fusions]:
            tid = str(trend.trend_id)
            state = state_by_trend.get(tid)
            instance = instance_by_trend.get(tid)
            correlation_ids = list(trend.correlation_ids) or membership.get(tid, [])
            score = self._scoring.score(
                trend,
                lifecycle_state=state,
                instance=instance,
                correlated=bool(correlation_ids),
                impact_label=inputs.impact_label,
                now=ts,
            )
            scores[tid] = score
            # Contract V3 enrichment: interpretation (deterministic
            # meaning), lifecycle timeline, and known pattern recurrence.
            interpretation = interpret(trend)
            timeline = instance.timeline() if instance is not None else {}
            pattern: dict = {}
            if self._patterns is not None:
                stats = await self._patterns.lookup(
                    inputs.competition_id, trend.trend_type, trend.direction
                )
                if stats is not None:
                    pattern = stats.to_wire()
            update = {
                "publish_score": score.score,
                "publication_tier": score.tier.value,
                "lifecycle_state": state.value if state else None,
                "correlation_ids": correlation_ids,
                "meaning": interpretation.meaning,
                "meaning_category": interpretation.meaning_category.value,
                "meaning_confidence": interpretation.meaning_confidence,
                "timeline": timeline,
                "pattern": pattern,
            }
            # Contract V4 enrichment (Maturity 1.5): historical
            # outcomes, market memory, competition context, regime and
            # continuation — deterministic aggregates over the outcome
            # log, mirrored compactly into the evidence (Parts 2 + 7).
            if self._enricher is not None:
                v4 = await self._enricher.trend_fields(
                    trend, competition_id=inputs.competition_id
                )
                update.update(v4)
                extra_evidence = self._enricher.evidence_fields(v4)
                if extra_evidence:
                    update["evidence"] = {**trend.evidence, **extra_evidence}
            evaluated.append(trend.model_copy(update=update))

        # 4b. Enriched correlations (Maturity 1.5 Part 10): predicate
        # rules over the V4 fields (historical alignment, structural
        # volatility). Their fusions are scored + interpreted like any
        # other trend and join this tick's evaluated set.
        enriched_records, enriched_fusions = (
            await self._correlation.correlate_enriched(inputs, evaluated, now=ts)
        )
        for record in enriched_records:
            await self._correlation_repo.record(record)
            correlations.append(record)
        for fusion in enriched_fusions:
            score = self._scoring.score(
                fusion,
                lifecycle_state=TrendLifecycleState.ACTIVE,
                instance=None,
                correlated=True,
                impact_label=inputs.impact_label,
                now=ts,
            )
            scores[str(fusion.trend_id)] = score
            interpretation = interpret(fusion)
            evaluated.append(fusion.model_copy(update={
                "publish_score": score.score,
                "publication_tier": score.tier.value,
                "lifecycle_state": TrendLifecycleState.ACTIVE.value,
                "meaning": interpretation.meaning,
                "meaning_category": interpretation.meaning_category.value,
                "meaning_confidence": interpretation.meaning_confidence,
            }))

        # 5. Persist EVERY evaluated trend (suppress/store included —
        # the audit trail is unconditional).
        for trend in evaluated:
            await self._trend_repo.record(trend)

        # 5b. Trend timeline (Sprint 3.6): append-only narrative record
        # per story (keyed by the lifecycle instance id).
        if self._timeline is not None:
            from atlas.trends.timeline import TrendTimelineEntry

            for trend in evaluated:
                instance = instance_by_trend.get(str(trend.trend_id))
                if instance is None:
                    continue
                await self._timeline.append(
                    instance.instance_id,
                    TrendTimelineEntry(
                        timestamp=trend.detected_at,
                        trend_id=trend.trend_id,
                        trend_type=trend.trend_type.value,
                        lifecycle_state=trend.lifecycle_state or "",
                        confidence=trend.confidence,
                        strength=trend.strength,
                        summary=trend.summary,
                        meaning=trend.meaning or "",
                    ),
                )

        # 6. Publish only the publishable tiers.
        published: list[Trend] = []
        priority_published: list[Trend] = []
        for trend in evaluated:
            tier = scores[str(trend.trend_id)].tier
            if not tier.streams:
                continue
            priority = tier == PublicationTier.PRIORITY_PUBLISH
            if await self._publisher.publish(trend, priority=priority) is not None:
                published.append(trend)
                if priority:
                    priority_published.append(trend)
                    PRIORITY_TRENDS_TOTAL.inc()

        if evaluated:
            logger.info(
                "trend_pipeline_tick",
                extra={
                    "canonical_match_id": str(inputs.canonical_match_id),
                    "detected": len(detected),
                    "fusions": len(fusions),
                    "correlations": len(correlations),
                    "published": len(published),
                    "priority": len(priority_published),
                    "tiers": {
                        str(t.trend_id): scores[str(t.trend_id)].tier.value
                        for t in evaluated
                    },
                },
            )

        return TrendPipelineResult(
            trends=evaluated,
            correlations=correlations,
            lifecycle_instances=touched,
            scores=scores,
            published=published,
            priority_published=priority_published,
        )
