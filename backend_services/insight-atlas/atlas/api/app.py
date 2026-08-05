"""FastAPI app factory — wires the container, lifespan, and routes.

The app owns:
  * a Redis client (feature store + inference cache + publisher)
  * Postgres engine + session factory (model registry)
  * one Gateway-mediated Anvil analytics reader
  * a null sentiment reader (canonical stream carries sentiment)
  * inference engine + training pipeline + emitter

A small periodic worker is started in the lifespan when
`feature_worker_enabled=True`; it loops over a list of live match ids
(injected via /internal endpoint or future stream subscription) and
keeps their hot snapshots fresh.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

import atlas.registry.models  # noqa: F401 — populates Base.metadata
from atlas.api.deps import AppContainer
from atlas.api.routes import backtest as backtest_routes
from atlas.api.routes import context as context_routes
from atlas.api.routes import intelligence_workspace as intelligence_workspace_routes
from atlas.api.routes import internal as internal_routes
from atlas.api.routes import meta as meta_routes
from atlas.backtest import ReplayService
from atlas.clients import AnvilGatewayReader, NullSentimentReader
from atlas.coherence import StoryCoherenceEngine
from atlas.config import get_settings
from atlas.context_engine import (
    CheckpointTracker,
    ContextRecalculationEngine,
    RedisCheckpointStore,
    RedisMatchContextStore,
)
from atlas.contracts import FeatureWindowOrigin
from atlas.datasets import AtlasDatasetService
from atlas.emitters import ContextEmitter
from atlas.event_aggregation import AggregationEngine, RedisAggregationStore
from atlas.event_impact import EventImpactEngine, Impact
from atlas.identity import IdentityRegistry, IdentityResolver
from atlas.inference import InferenceEngine
from atlas.ingestion import AtlasIngestionRepository, AtlasIngestionService
from atlas.intelligence import IntelligencePipeline
from atlas.intelligence.competition import CompetitionIntelligenceEngine
from atlas.intelligence.continuation import ContinuationEngine
from atlas.intelligence.crossmatch import CrossMatchEngine
from atlas.intelligence.enrichment import IntelligenceEnricher
from atlas.intelligence.historical_outcomes import HistoricalOutcomeEngine
from atlas.intelligence.market_memory import MarketMemoryEngine
from atlas.intelligence.meta_trends import MetaTrendEngine
from atlas.intelligence.regimes import RegimeEngine
from atlas.market import MarketStateEngine
from atlas.odds import (
    OddsContextStore,
    OddsFeatureStore,
    OddsHandler,
    OddsRepository,
)
from atlas.operational_events import event_bus
from atlas.operations import atlas_operations, start_grpc_server
from atlas.ops import DLQReplayService
from atlas.patterns import PatternMemory
from atlas.publication_engine import PublicationEngine
from atlas.registry import ModelRegistry, build_engine, build_session_factory
from atlas.registry.base import Base
from atlas.runtime.logging import configure_logging
from atlas.runtime.redis_factory import create_redis_client
from atlas.signal_engine import SignalEngine
from atlas.similarity import SimilarityCache, SimilarityRepository, SimilarityService
from atlas.store import FeatureStore, InferenceCache
from atlas.streaming import CanonicalConsumer, CanonicalEnvelope, ConsumerConfig
from atlas.streaming.publisher import DerivedPublisher
from atlas.streaming.streams import StreamPartitioning
from atlas.strength import StrengthRepository
from atlas.strength.sync_watcher import StrengthSyncWatcher
from atlas.training import TrainingPipeline
from atlas.trends import (
    CorrelatedTrendRepository,
    PublishScoreEngine,
    TrendCorrelationEngine,
    TrendEngine,
    TrendInputs,
    TrendIntelligencePipeline,
    TrendLifecycleEngine,
    TrendLifecycleRepository,
    TrendPublisher,
    TrendRepository,
)
from atlas.trends.correlation import RedisRecentTrendStore
from atlas.trends.similarity_probe import OnlineSimilarityProbe
from atlas.trends.timeline import TrendTimelineRepository
from atlas.validation import quarantine_snapshot
from atlas.vector_memory import PgVectorMemoryRepository
from atlas.watchers import (
    ClusterJanitor,
    CoherenceWatcher,
    IntelligenceWatcher,
    MarketWatcher,
    MatchWatcher,
    NarrativeWatcher,
    ObservationSink,
    RedisSeriesStore,
    RiskWatcher,
    WatcherRegistry,
    WatcherScheduler,
    export_watcher_config,
)

logger = logging.getLogger(__name__)


async def _record_series(store, canonical_match_id, inputs) -> None:
    """Record evolving state for the continuous watchers (Sprint 3.6):
    stat series from match statistics, narrative features, risk-event
    unit samples, and the recent-match index."""
    await store.touch_match(canonical_match_id)
    if inputs.match_stats:
        for key, value in inputs.match_stats.items():
            await store.record(canonical_match_id, key, float(value))
    if inputs.features:
        for key in ("sentiment_delta", "community_confidence"):
            if key in inputs.features:
                await store.record(
                    canonical_match_id, key, float(inputs.features[key])
                )
    if inputs.impact_category in ("yellow_card", "red_card", "foul", "injury"):
        await store.record(
            canonical_match_id, f"risk_{inputs.impact_category}", 1.0
        )


def _extract_match_stats(event: dict) -> dict[str, float] | None:
    """Live match statistics from a canonical event payload, normalised
    to the flat `{stat}_home` / `{stat}_away` convention the
    MomentumTrendEngine consumes. Provider-agnostic: accepts both the
    flat form ({"possession_home": 60}) and the nested form
    ({"possession": {"home": 60, "away": 40}}). Returns None when the
    payload carries no statistics."""
    raw = (event.get("payload") or {}).get("statistics")
    if not isinstance(raw, dict):
        return None
    out: dict[str, float] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            for side in ("home", "away"):
                v = value.get(side)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out[f"{key}_{side}"] = float(v)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            out[str(key)] = float(value)
    return out or None


def _extract_minute(event: dict) -> int | None:
    """Best-effort match minute from a canonical event payload. Live
    provider events carry it directly; absent for scheduling/odds events.
    """
    payload = event.get("payload") or {}
    raw = payload.get("minute")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return None


def build_app() -> FastAPI:
    configure_logging(service="atlas")
    settings = get_settings()

    db_engine = build_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
    )
    session_factory = build_session_factory(db_engine)
    registry = ModelRegistry(session_factory)

    redis = create_redis_client(settings.redis_url)
    feature_store = FeatureStore(
        redis=redis,
        key_prefix=settings.feature_hot_prefix,
        ttl_seconds=settings.feature_hot_ttl_seconds,
    )
    inference_cache = InferenceCache(
        redis=redis,
        key_prefix=settings.inference_cache_prefix,
        ttl_seconds=settings.inference_cache_ttl_seconds,
    )

    # Odds subsystem — full odds-history persistence (Postgres) plus
    # derived hot feature/context views (Redis). The OddsHandler is the
    # match.odds ingress path off insight:stream:events:odds.
    odds_repository = OddsRepository(session_factory)
    market_state_engine = MarketStateEngine()
    odds_handler = OddsHandler(
        repository=odds_repository,
        feature_store=OddsFeatureStore(
            redis=redis,
            key_prefix=settings.odds_hot_prefix,
            ttl_seconds=settings.odds_hot_ttl_seconds,
        ),
        context_store=OddsContextStore(
            redis=redis,
            key_prefix=settings.odds_hot_prefix,
            ttl_seconds=settings.odds_hot_ttl_seconds,
        ),
        history_limit=settings.odds_history_limit,
    )

    # Sprint 6.2 — real-time intelligence pipeline. Resolves canonical
    # match identity, classifies event impact, generates + aggregates
    # signals, decides publication, and recalculates context. All
    # Redis-backed; shares the session factory for the identity registry.
    intelligence = IntelligencePipeline(
        identity_resolver=IdentityResolver(
            IdentityRegistry(session_factory),
            tolerance_seconds=settings.identity_tolerance_seconds,
        ),
        impact_engine=EventImpactEngine(),
        signal_engine=SignalEngine(),
        aggregation_engine=AggregationEngine(RedisAggregationStore(redis)),
        publication_engine=PublicationEngine(
            min_confidence=settings.publication_min_confidence,
            min_impact=Impact[settings.publication_min_impact.upper()],
        ),
        context_engine=ContextRecalculationEngine(
            checkpoint_tracker=CheckpointTracker(RedisCheckpointStore(redis)),
        ),
        context_store=RedisMatchContextStore(
            redis=redis, ttl_seconds=settings.match_context_ttl_seconds
        ),
    )

    # Sprint 0/1/1.5 — the trend layer. Detection (five engine families)
    # → lifecycle evolution → correlation → publish scoring → persist
    # everything → stream only the publishable tiers. Atlas publishes
    # evaluated intelligence, never raw detections.
    trend_engine = TrendEngine(
        cooldown_store=RedisAggregationStore(redis, key_prefix="atlas:trendcd:"),
        cooldown_seconds=settings.trend_cooldown_seconds,
    )
    # Maturity Sprint 1.5 — the intelligence layer: memory over
    # closed lifecycles, historical/continuation profiles, competition
    # intelligence + regimes, cross-match recurrence, meta scans.
    market_memory_engine = MarketMemoryEngine(session_factory)
    historical_engine = HistoricalOutcomeEngine(session_factory)
    continuation_engine = ContinuationEngine(session_factory)
    competition_engine = CompetitionIntelligenceEngine(session_factory)
    regime_engine = RegimeEngine(session_factory)
    crossmatch_engine = CrossMatchEngine(session_factory)
    meta_engine = MetaTrendEngine(session_factory)
    intelligence_enricher = IntelligenceEnricher(
        market_memory=market_memory_engine,
        historical=historical_engine,
        continuation=continuation_engine,
        competition=competition_engine,
        regimes=regime_engine,
    )

    # ATLAS-SIMILARITY-A: the shared similarity capability (cache + storage +
    # scoring + metrics). One instance serves the trend probe AND the container,
    # so every consumer shares the same cache + metrics.
    similarity_service = SimilarityService(
        SimilarityRepository(session_factory),
        cache=SimilarityCache(),
    )

    trends_pipeline = TrendIntelligencePipeline(
        engine=trend_engine,
        lifecycle_engine=TrendLifecycleEngine(
            expiry_seconds=settings.trend_lifecycle_expiry_seconds,
        ),
        lifecycle_repository=TrendLifecycleRepository(session_factory),
        correlation_engine=TrendCorrelationEngine(
            RedisRecentTrendStore(redis),
            cooldown_store=RedisAggregationStore(redis, key_prefix="atlas:corrcd:"),
        ),
        correlation_repository=CorrelatedTrendRepository(session_factory),
        scoring_engine=PublishScoreEngine(),
        trend_repository=TrendRepository(session_factory),
        publisher=TrendPublisher(
            redis,
            stream=settings.trend_stream_key,
            maxlen=settings.trend_stream_maxlen,
        ),
        pattern_memory=PatternMemory(session_factory),
        timeline_repository=TrendTimelineRepository(session_factory),
        intelligence_enricher=intelligence_enricher,
        # ATLAS-VECTOR-B + ATLAS-SIMILARITY-A: online pgvector similarity through
        # the shared SimilarityService (cache + storage + scoring + metrics).
        # Reusable by every intelligence engine, not just the Oracle.
        similarity_probe=OnlineSimilarityProbe(similarity_service),
    )

    # Sprint 3.6 — continuous observation layer. Watchers observe
    # evolving state (recorded below as events flow) and feed synthetic
    # observations through the SAME trends pipeline. The janitor expires
    # stale stories; coherence is computed on the same schedule.
    series_store = RedisSeriesStore(redis)
    watcher_registry = WatcherRegistry()
    watcher_registry.register(MarketWatcher(
        odds_repository, series_store,
        window_seconds=settings.watcher_window_seconds,
        drift_threshold=settings.market_drift_threshold,
    ))
    watcher_registry.register(MatchWatcher(
        series_store, window_seconds=settings.watcher_window_seconds,
        possession_growth=settings.match_possession_growth_threshold,
    ))
    watcher_registry.register(RiskWatcher(
        series_store, window_seconds=settings.watcher_window_seconds,
        accumulation_threshold=settings.risk_accumulation_threshold,
    ))
    watcher_registry.register(NarrativeWatcher(
        series_store, window_seconds=settings.watcher_window_seconds,
        consensus_growth=settings.narrative_consensus_threshold,
    ))
    watcher_registry.register(CoherenceWatcher(
        StoryCoherenceEngine(TrendRepository(session_factory), session_factory),
        series_store,
        window_seconds=settings.watcher_window_seconds,
    ))
    watcher_registry.register(ClusterJanitor(
        session_factory,
        inactivity_seconds=settings.janitor_inactivity_seconds,
        market_memory=market_memory_engine,
    ))
    # ATLAS-SIM-A: keeps atlas.team_strength_state/head_to_head_state/
    # team_standings_state current from Explorer's validated lake (the
    # system of record for match results — see StrengthSyncWatcher's
    # docstring for why this isn't a canonical-event consumer hook).
    # explorer_data_root is the LAKE ROOT (raw/normalized/validated/...
    # side by side, per explorer/config.py::LAKE_LAYERS) — must read only
    # the validated/ layer, never raw/normalized.
    strength_repository = StrengthRepository(session_factory)
    watcher_registry.register(StrengthSyncWatcher(
        strength_repository,
        f"{settings.explorer_data_root.rstrip('/')}/validated",
        min_sync_interval_seconds=settings.strength_sync_min_interval_seconds,
        enabled=settings.strength_sync_enabled,
    ))
    watcher_registry.register(IntelligenceWatcher(
        competition_engine,
        regime_engine,
        meta_engine,
        crossmatch_engine,
    ))
    watcher_scheduler = WatcherScheduler(
        watcher_registry,
        ObservationSink(trends_pipeline),
        interval_seconds=settings.watcher_interval_seconds,
        jitter_seconds=settings.watcher_jitter_seconds,
    )
    export_watcher_config(
        market_drift_threshold=settings.market_drift_threshold,
        match_possession_growth_threshold=(
            settings.match_possession_growth_threshold
        ),
        risk_accumulation_threshold=settings.risk_accumulation_threshold,
        narrative_consensus_threshold=settings.narrative_consensus_threshold,
        watcher_interval_seconds=settings.watcher_interval_seconds,
        watcher_jitter_seconds=settings.watcher_jitter_seconds,
        watcher_window_seconds=settings.watcher_window_seconds,
    )
    # Admin-only DLQ operations (service layer; no routes).
    dlq_replay = DLQReplayService(redis, dlq_stream=settings.atlas_dlq_stream)

    publisher = DerivedPublisher(
        redis,
        partitioning=StreamPartitioning(
            base_key=settings.derived_stream_base_key,
            partitions=settings.stream_partitions,
        ),
        max_payload_bytes=settings.max_payload_bytes,
        stream_maxlen_approx=200_000,
    )
    emitter = ContextEmitter(publisher=publisher, region_code=settings.region_code)

    analytics = AnvilGatewayReader(
        base_url=settings.anvil_api_base_url,
        api_key=settings.anvil_api_key,
        timeout_seconds=settings.anvil_api_timeout_seconds,
    )
    # Consolidation Sprint 0: sentiment features come from the
    # canonical context stream; no HTTP sentiment dependency remains.
    sentiment_reader = NullSentimentReader()

    engine = InferenceEngine(
        registry=registry, feature_schema_version=settings.feature_schema_version
    )
    training = TrainingPipeline(
        registry=registry,
        artifact_dir=settings.artifact_dir,
        feature_schema_version=settings.feature_schema_version,
    )

    ingestion_repository = AtlasIngestionRepository(session_factory)
    container = AppContainer(
        settings=settings,
        registry=registry,
        engine=engine,
        feature_store=feature_store,
        inference_cache=inference_cache,
        emitter=emitter,
        training=training,
        analytics=analytics,
        sentiment=sentiment_reader,
        vector_memory=PgVectorMemoryRepository(session_factory),
        similarity=similarity_service,
        replay=ReplayService(events=event_bus),
        ingestion=AtlasIngestionService(ingestion_repository),
        datasets=AtlasDatasetService(
            session_factory, Path(settings.intelligence_dataset_path).parent
        ),
        strength=strength_repository,
    )

    # Sprint 5.1 — canonical-event consumer. Reads Hub-published
    # CanonicalSportsEvent envelopes off Redis Streams and refreshes
    # the hot feature snapshot for the affected match. The consumer
    # is the ONLY ingress path for upstream data; provider HTTP is
    # not called from Atlas.
    canonical_consumer = CanonicalConsumer(
        ConsumerConfig(
            redis_url=settings.redis_url,
            group=settings.atlas_consumer_group,
            consumer_name=settings.atlas_consumer_name,
            streams=tuple(settings.canonical_streams()),
            dlq_stream=settings.atlas_dlq_stream,
            processed_key_prefix=settings.atlas_processed_event_prefix,
            processed_ttl_seconds=settings.atlas_processed_ttl_seconds,
            retry_key_prefix=settings.atlas_retry_key_prefix,
            pending_reclaim_idle_ms=settings.atlas_pending_reclaim_idle_ms,
            max_handler_attempts=settings.atlas_max_handler_attempts,
        )
    )

    async def run_intelligence(
        env: CanonicalEnvelope,
        *,
        odds_shift: bool,
        odds_context: dict | None,
        market_state: dict | None = None,
        odds_history: list | None = None,
    ) -> None:
        """Run the Sprint 6.2 intelligence pipeline. Best-effort: a
        failure is logged + counted (never silent) but does not break
        ingestion of odds/feature state."""
        if not settings.intelligence_enabled:
            return
        event = env.event
        try:
            result = await intelligence.process(
                event,
                minute=_extract_minute(event),
                odds_shift=odds_shift,
                odds_context=odds_context,
                market_state=market_state,
            )
        except Exception:
            logger.exception(
                "atlas_intelligence_failed",
                extra={"event_id": event.get("event_id"), "key": env.idempotency_key},
            )
            return
        if result.published:
            logger.info(
                "atlas_intelligence_published",
                extra={
                    "canonical_match_id": str(result.canonical_match_id),
                    "impact": result.classification.impact.label,
                    "signals": [d.signal.signal_type.value for d in result.published],
                    "recalc_trigger": result.recalc.trigger or None,
                },
            )
        await run_trends(
            env, result, odds_context=odds_context, precomputed_odds_history=odds_history,
        )

    async def run_trends(
        env: CanonicalEnvelope, result, *, odds_context, precomputed_odds_history: list | None = None,
    ) -> None:
        """Sprint 0 — trend detection over this tick's correlated inputs.
        Persist-then-publish; failures are logged + counted, never break
        ingestion."""
        from uuid import UUID

        if not settings.trends_enabled:
            return
        event = env.event
        payload = event.get("payload") or {}
        try:
            # Odds timeline (market + historical detectors) — keyed by the
            # stable odds grouping id carried in the payload. `handle_envelope`
            # already fetched this exact (match_id, limit) history for the
            # match.odds path (see odds_handler.handle()'s return value) —
            # reuse it instead of a third identical Postgres round-trip.
            if precomputed_odds_history is not None:
                odds_history = precomputed_odds_history
            else:
                odds_history = []
                payload_match = payload.get("match_id")
                if str(event.get("event_type", "")) == "match.odds" and payload_match:
                    try:
                        odds_history = await odds_repository.history(
                            UUID(str(payload_match)), limit=settings.odds_history_limit
                        )
                    except (ValueError, TypeError):
                        odds_history = []

            # Latest hot feature snapshot (pulse + echo detectors).
            features = None
            event_match = event.get("match_id")
            if event_match:
                try:
                    snap = await feature_store.get(UUID(str(event_match)))
                    if snap is not None:
                        features = dict(snap.features)
                except (ValueError, TypeError):
                    features = None

            competition_id = None
            comp_raw = event.get("competition_id")
            if comp_raw:
                try:
                    competition_id = UUID(str(comp_raw))
                except (ValueError, TypeError):
                    competition_id = None

            inputs = TrendInputs(
                canonical_match_id=result.canonical_match_id,
                competition_id=competition_id,
                minute=_extract_minute(event),
                context=result.context,
                prior_context=result.prior_context,
                odds_context=odds_context,
                odds_history=odds_history,
                signals=result.signals,
                impact_label=result.classification.impact.label,
                impact_category=result.classification.category,
                features=features,
                match_stats=_extract_match_stats(event),
            )
            # Sprint 3.6 — record evolving state for the watchers.
            try:
                await _record_series(series_store, result.canonical_match_id, inputs)
            except Exception:
                logger.exception("atlas_series_record_failed")

            outcome = await trends_pipeline.process(inputs)
            if outcome.trends:
                logger.info(
                    "atlas_trends_evaluated",
                    extra={
                        "canonical_match_id": str(result.canonical_match_id),
                        "trend_types": [t.trend_type.value for t in outcome.trends],
                        "correlations": [
                            c.correlation_type.value for c in outcome.correlations
                        ],
                        "published": len(outcome.published),
                        "priority": len(outcome.priority_published),
                        "key": env.idempotency_key,
                    },
                )
        except Exception:
            logger.exception(
                "atlas_trends_failed",
                extra={"event_id": event.get("event_id"), "key": env.idempotency_key},
            )

    async def handle_envelope(env: CanonicalEnvelope) -> None:
        """Convert one envelope into refreshed feature + context + signal
        state."""
        from uuid import UUID

        event = env.event
        event_type = str(event.get("event_type", ""))
        # Odds are their own canonical category. They share the
        # "match." prefix but must NOT flow through the ML feature-
        # snapshot path — they have a dedicated persistence + feature +
        # context pipeline that preserves the full odds history.
        if event_type == "match.odds":
            # handle() already fetches this match's full history
            # (limit=settings.odds_history_limit, same as below) to
            # build features+context — reuse it for market_state instead
            # of issuing the identical Postgres query a second time.
            history = await odds_handler.handle(env)
            # An odds event that reached Atlas already passed the Hub's
            # change gate → a meaningful shift. Feed it to intelligence
            # with the freshly-stored odds context.
            odds_context = None
            market_state = None
            payload_match = (event.get("payload") or {}).get("match_id")
            if payload_match:
                try:
                    odds_match = UUID(str(payload_match))
                    odds_context = await odds_handler.context_for(odds_match)
                    # Magnus Absorption — recompute the market-state
                    # view from the full persisted odds timeline.
                    market_state = market_state_engine.compute(history).as_dict()
                except (ValueError, TypeError):
                    odds_context = None
            await run_intelligence(
                env,
                odds_shift=True,
                odds_context=odds_context,
                market_state=market_state,
                odds_history=history,
            )
            return
        # Every other canonical event flows through intelligence too
        # (impact classification, signals, context recalculation).
        await run_intelligence(env, odds_shift=False, odds_context=None)
        # The hot-snapshot refresh is only meaningful for match-scoped
        # events. competition.standings land here too but don't drive
        # a per-match snapshot in V1.
        if not event_type.startswith("match."):
            logger.info(
                "atlas_envelope_skip_non_match",
                extra={
                    "event_type": event_type,
                    "event_id": event.get("event_id"),
                    "key": env.idempotency_key,
                },
            )
            return
        match_id = UUID(str(event["match_id"]))
        competition_id_raw = event.get("competition_id")
        competition_id = (
            UUID(str(competition_id_raw)) if competition_id_raw else None
        )
        from atlas.features.pipeline import build_snapshot

        snapshot = await build_snapshot(
            match_id=match_id,
            competition_id=competition_id,
            as_of=env.published_at,
            schema_version=settings.feature_schema_version,
            analytics=analytics,
            sentiment=sentiment_reader,
            feature_window_origin=FeatureWindowOrigin.rolling,
        )
        await feature_store.put(snapshot)
        decision = quarantine_snapshot(
            snapshot,
            active_schema_version=settings.feature_schema_version,
        )
        if decision.quarantined:
            logger.warning(
                "atlas_stream_snapshot_quarantined",
                extra={
                    "match_id": str(match_id),
                    "event_id": event["event_id"],
                    "reason": decision.reason.value,
                    "detail": decision.detail,
                },
            )
            return
        context = await engine.context_for(snapshot)
        await inference_cache.put(
            match_id,
            settings.feature_schema_version,
            context.model_dump(mode="json"),
        )
        await emitter.emit(context)

    async def _run_consumer_supervised() -> None:
        """Restarts `canonical_consumer.run()` with backoff if it ever
        exits unexpectedly, instead of silently taking down ingestion
        for the process lifetime with no recovery (ATLAS review Round
        3, finding #1 — `_dispatch`'s own safety net makes this rare
        now, but a supervisor is cheap insurance against a future bug
        slipping past it). `app.state.consumer_alive` feeds `/ready` so
        a crashed-and-not-yet-recovered consumer is actually visible to
        health checks, not masked by the one-shot `operations_ready`
        flag."""
        backoff_seconds = 1.0
        while True:
            app.state.consumer_alive = True
            try:
                await canonical_consumer.run(handle_envelope)
                return  # run() only returns normally once _stop is set (real shutdown)
            except asyncio.CancelledError:
                raise
            except Exception:
                app.state.consumer_alive = False
                logger.exception("atlas_consumer_crashed")
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 60.0)
                try:
                    await canonical_consumer.reconnect()
                except Exception:
                    logger.exception("atlas_consumer_reconnect_failed")
                    continue

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container
        app.state.canonical_consumer = canonical_consumer
        app.state.operations_ready = False
        app.state.consumer_alive = not settings.canonical_consumer_enabled

        if settings.auto_apply_migrations and settings.database_url.startswith("sqlite"):
            async with db_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        # Start the canonical consumer in the background. The task
        # is supervised by the lifespan — cancelled at shutdown so
        # in-flight handler invocations finish + the redis client
        # closes cleanly. _run_consumer_supervised restarts run()
        # itself if it ever exits unexpectedly (see its docstring).
        consumer_task: asyncio.Task[None] | None = None
        if settings.canonical_consumer_enabled:
            await canonical_consumer.connect()
            consumer_task = asyncio.create_task(
                _run_consumer_supervised(),
                name="atlas-canonical-consumer",
            )

        # Sprint 3.6 — continuous observation scheduler.
        app.state.dlq_replay = dlq_replay
        if settings.watchers_enabled:
            watcher_scheduler.start()

        app.state.operations_ready = True
        operations_grpc = start_grpc_server(
            app.state.operations_service,
            os.getenv("OPERATIONS_GRPC_ADDR", "[::]:9081"),
        )
        logger.info(
            "atlas_started",
            extra={
                "feature_schema_version": settings.feature_schema_version,
                "artifact_dir": settings.artifact_dir,
                "canonical_consumer_enabled": settings.canonical_consumer_enabled,
            },
        )
        event_bus.emit(
            "atlas_started",
            current_state="running",
            metadata={
                "feature_schema_version": settings.feature_schema_version,
                "artifact_dir": settings.artifact_dir,
                "canonical_consumer_enabled": settings.canonical_consumer_enabled,
            },
        )
        try:
            yield
        finally:
            app.state.operations_ready = False
            operations_grpc.stop(grace=5)
            if settings.watchers_enabled:
                await watcher_scheduler.stop()
            if consumer_task is not None:
                await canonical_consumer.close()
                consumer_task.cancel()
                try:
                    await consumer_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            await analytics.aclose()
            await sentiment_reader.aclose()
            try:
                await redis.aclose()
            except Exception:
                pass
            await db_engine.dispose()
            logger.info("atlas_stopped")
            event_bus.emit("atlas_stopped", current_state="stopped")

    app = FastAPI(
        title="Insight Atlas",
        description="ML context layer (Layer M) — descriptive only, never predictive.",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/live", tags=["meta"])
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["meta"])
    async def ready() -> dict[str, str]:
        try:
            # A hung/unreachable Postgres must fail this probe FAST, not
            # hang past the caller's own probe timeout (which delays
            # failure detection instead of surfacing it) — build_engine
            # sets no connect/command timeout, so bound it here.
            async with asyncio.timeout(2.0):
                async with db_engine.connect() as conn:
                    await conn.exec_driver_sql("SELECT 1")
        except Exception as exc:
            return {"status": "not_ready", "error": str(exc)[:200]}
        if not getattr(app.state, "consumer_alive", True):
            return {"status": "not_ready", "error": "canonical_consumer_crashed"}
        return {"status": "ready"}

    @app.get("/metrics", tags=["meta"], include_in_schema=False)
    async def metrics():
        from fastapi import Response

        from atlas.runtime.metrics import render_metrics

        body, content_type = render_metrics()
        return Response(content=body, media_type=content_type)

    app.state.operations_service = atlas_operations(
        ready=lambda: (
            bool(getattr(app.state, "operations_ready", False))
            and bool(getattr(app.state, "consumer_alive", True))
        ),
        active_jobs=lambda: 1 if settings.canonical_consumer_enabled else 0,
    )

    @app.get("/healthz", tags=["operations"])
    async def operations_healthz() -> dict[str, object]:
        return app.state.operations_service.http_health()

    @app.get("/health", tags=["operations"])
    async def operations_health() -> dict[str, object]:
        return app.state.operations_service.http_health()

    @app.get("/status", tags=["operations"])
    async def operations_status() -> dict[str, object]:
        return app.state.operations_service.http_status()

    @app.get("/capabilities", tags=["operations"])
    async def operations_capabilities() -> dict[str, object]:
        return app.state.operations_service.http_capabilities()

    @app.get("/metrics/summary", tags=["operations"])
    async def operations_metrics() -> dict[str, object]:
        return app.state.operations_service.http_metrics()

    app.include_router(context_routes.router)
    app.include_router(internal_routes.router)
    app.include_router(intelligence_workspace_routes.router)
    app.include_router(intelligence_workspace_routes.atlas_router)
    app.include_router(meta_routes.router)
    app.include_router(backtest_routes.router)
    # /backtests is the only require_internal_token-protected router that
    # doesn't live under /v1/internal or /atlas — harmless today (the
    # token check is the real gate, not the prefix), but if an edge
    # layer ever allow-lists internal traffic by those two prefixes,
    # this would silently fall outside it. Kept as an additive alias —
    # the original /backtests/* path is untouched for existing callers.
    app.include_router(
        backtest_routes.router, prefix="/v1/internal", include_in_schema=False,
    )
    return app


app = build_app()
