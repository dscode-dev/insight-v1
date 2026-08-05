from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- HTTP / API ---
    http_host: str = Field(default="0.0.0.0", alias="HTTP_HOST")
    http_port: int = Field(default=8085, alias="HTTP_PORT")
    # Stage 8 hardening: required from env (no insecure default). The
    # lab overlay supplies a lab token; production supplies a Secret.
    internal_token: str = Field(..., alias="INTERNAL_TOKEN", min_length=16)

    # --- Registry (Postgres) ---
    database_url: str = Field(..., alias="DATABASE_URL")
    database_pool_size: int = Field(default=5, alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=10, alias="DATABASE_MAX_OVERFLOW")
    auto_apply_migrations: bool = Field(default=True, alias="AUTO_APPLY_MIGRATIONS")

    # --- Feature store + emitter (Redis + derived stream) ---
    redis_url: str = Field(..., alias="REDIS_URL")
    derived_stream_base_key: str = Field(
        default="insight:stream:derived", alias="DERIVED_STREAM_BASE_KEY"
    )
    stream_partitions: int = Field(default=8, alias="STREAM_PARTITIONS")
    max_payload_bytes: int = Field(default=262_144, alias="MAX_PAYLOAD_BYTES")

    feature_hot_prefix: str = Field(
        default="atlas:features:", alias="FEATURE_HOT_PREFIX"
    )
    feature_hot_ttl_seconds: int = Field(default=3600, alias="FEATURE_HOT_TTL_SECONDS")
    inference_cache_prefix: str = Field(
        default="atlas:infer:", alias="INFERENCE_CACHE_PREFIX"
    )
    inference_cache_ttl_seconds: int = Field(
        default=10, alias="INFERENCE_CACHE_TTL_SECONDS"
    )

    # --- Anvil analytics API (Gateway mediated) ---
    anvil_api_base_url: str = Field(..., alias="ATLAS_ANVIL_API_BASE_URL")
    anvil_api_key: str = Field(..., alias="ATLAS_ANVIL_API_KEY", min_length=32)
    anvil_api_timeout_seconds: float = Field(
        default=8.0, alias="ATLAS_ANVIL_API_TIMEOUT_SECONDS"
    )

    # --- Workers ---
    feature_worker_interval_seconds: int = Field(
        default=30, alias="FEATURE_WORKER_INTERVAL_SECONDS"
    )
    feature_worker_enabled: bool = Field(default=True, alias="FEATURE_WORKER_ENABLED")

    # --- Models ---
    artifact_dir: str = Field(default="/var/atlas/artifacts", alias="ARTIFACT_DIR")
    training_device: str = Field(default="cpu", alias="ATLAS_TRAINING_DEVICE")
    inference_device: str = Field(default="cpu", alias="ATLAS_INFERENCE_DEVICE")
    historical_dataset_path: str = Field(
        default="/var/atlas/datasets/historical.jsonl",
        alias="ATLAS_HISTORICAL_DATASET_PATH",
    )
    intelligence_dataset_path: str = Field(
        default="/var/atlas/datasets/outcome_v4-mld6-20260623/matches.jsonl",
        alias="ATLAS_INTELLIGENCE_DATASET_PATH",
    )
    explorer_data_root: str = Field(
        default="/var/atlas/explorer", alias="ATLAS_EXPLORER_DATA_ROOT",
    )
    historical_train_until_year: int = Field(default=2022, alias="ATLAS_HISTORICAL_TRAIN_UNTIL_YEAR")
    historical_validation_year: int = Field(default=2023, alias="ATLAS_HISTORICAL_VALIDATION_YEAR")
    historical_test_year: int = Field(default=2024, alias="ATLAS_HISTORICAL_TEST_YEAR")
    # Sprint 0.1 bumped to 2 — engagement_rate removed from FEATURE_NAMES.
    # Models trained against v1 are filtered out by the engine's
    # schema-mismatch guard (atlas/inference/engine.py:_get) and stay
    # inert until retrained. No compatibility shim — vectors are
    # positional and dimension change is irreconcilable.
    feature_schema_version: int = Field(default=2, alias="FEATURE_SCHEMA_VERSION")

    # --- Region ---
    region_code: str = Field(default="GLOBAL", alias="REGION_CODE")

    # --- Sprint 5.1: canonical-event consumer ---
    # Atlas reads the Sports Hub's CanonicalSportsEvent envelopes off
    # Redis Streams. Disable via env in worker/training-only deployments
    # where this process should not consume.
    canonical_consumer_enabled: bool = Field(
        default=True, alias="CANONICAL_CONSUMER_ENABLED"
    )
    canonical_stream_match: str = Field(
        default="insight:stream:events:match", alias="CANONICAL_MATCH_STREAM"
    )
    canonical_stream_context: str = Field(
        default="insight:stream:events:context", alias="CANONICAL_CONTEXT_STREAM"
    )
    canonical_stream_odds: str = Field(
        default="insight:stream:events:odds", alias="CANONICAL_ODDS_STREAM"
    )
    # Odds history is a first-class dataset; the consumer subscribes to
    # the odds stream by default. Disable for deployments that should
    # not ingest market data.
    canonical_odds_enabled: bool = Field(
        default=True, alias="CANONICAL_ODDS_ENABLED"
    )

    # --- Odds hot stores (Redis) ---
    odds_hot_prefix: str = Field(default="atlas:odds:", alias="ODDS_HOT_PREFIX")
    odds_hot_ttl_seconds: int = Field(default=86_400, alias="ODDS_HOT_TTL_SECONDS")
    odds_history_limit: int = Field(default=500, alias="ODDS_HISTORY_LIMIT")

    # --- Sprint 6.2: real-time intelligence ---
    intelligence_enabled: bool = Field(default=True, alias="INTELLIGENCE_ENABLED")
    publication_min_confidence: float = Field(
        default=0.7, alias="PUBLICATION_MIN_CONFIDENCE"
    )
    publication_min_impact: str = Field(default="HIGH", alias="PUBLICATION_MIN_IMPACT")
    identity_tolerance_seconds: int = Field(
        default=5400, alias="IDENTITY_TOLERANCE_SECONDS"
    )
    match_context_ttl_seconds: int = Field(
        default=86_400, alias="MATCH_CONTEXT_TTL_SECONDS"
    )

    # --- Sprint 0 (Trend Intelligence Foundation) ---
    trends_enabled: bool = Field(default=True, alias="TRENDS_ENABLED")
    trend_stream_key: str = Field(
        default="insight:stream:trends", alias="TREND_STREAM_KEY"
    )
    trend_stream_maxlen: int = Field(default=100_000, alias="TREND_STREAM_MAXLEN")
    trend_cooldown_seconds: int = Field(default=120, alias="TREND_COOLDOWN_SECONDS")

    # --- Sprint 1.5: lifecycle + correlation + publish scoring ---
    trend_lifecycle_expiry_seconds: int = Field(
        default=1800, alias="TREND_LIFECYCLE_EXPIRY_SECONDS"
    )
    trend_correlation_window_seconds: int = Field(
        default=600, alias="TREND_CORRELATION_WINDOW_SECONDS"
    )

    # --- Sprint 3.6: continuous observation layer ---
    watchers_enabled: bool = Field(default=True, alias="WATCHERS_ENABLED")
    watcher_interval_seconds: int = Field(
        default=30, alias="ATLAS_WATCHER_INTERVAL_SECONDS"
    )
    # Absolute jitter applied around the interval (uniform ±jitter).
    watcher_jitter_seconds: float = Field(
        default=6.0, alias="ATLAS_WATCHER_JITTER_SECONDS"
    )
    watcher_window_seconds: int = Field(
        default=1800, alias="WATCHER_WINDOW_SECONDS"
    )

    # --- Consolidation Sprint 0 Task 0: watcher detection thresholds ---
    # Consensus implied-probability drift across the observation window
    # that earns a synthetic ODDS_SHIFT (probability points, 0-1).
    market_drift_threshold: float = Field(
        default=0.03, alias="ATLAS_MARKET_DRIFT_THRESHOLD", gt=0.0, lt=1.0
    )
    # Monotonic possession growth (percentage points) that earns a
    # synthetic PRESSURE_SPIKE.
    match_possession_growth_threshold: float = Field(
        default=10.0,
        alias="ATLAS_MATCH_POSSESSION_GROWTH_THRESHOLD",
        gt=0.0,
        le=100.0,
    )
    # Weighted card/foul/injury accumulation that earns a synthetic
    # risk MOMENTUM_SWING.
    risk_accumulation_threshold: float = Field(
        default=4.0, alias="ATLAS_RISK_ACCUMULATION_THRESHOLD", gt=0.0
    )
    # Monotonic community-confidence growth (0-1 scale) that earns a
    # synthetic narrative MOMENTUM_SWING.
    narrative_consensus_threshold: float = Field(
        default=0.2, alias="ATLAS_NARRATIVE_CONSENSUS_THRESHOLD", gt=0.0, le=1.0
    )
    janitor_inactivity_seconds: int = Field(
        default=1800, alias="JANITOR_INACTIVITY_SECONDS"
    )
    # --- ATLAS-SIM-A: live team-strength engine ---
    # Explorer's validated lake is the source of truth for match RESULTS
    # (there is no live "match finished N-M" canonical event — only
    # in-play signals flow through the Hub stream). The strength-sync
    # watcher self-throttles well above the shared 30s watcher interval
    # since re-scanning the whole lake every tick would be wasteful.
    strength_sync_enabled: bool = Field(
        default=True, alias="ATLAS_STRENGTH_SYNC_ENABLED"
    )
    strength_sync_min_interval_seconds: float = Field(
        default=1800.0, alias="ATLAS_STRENGTH_SYNC_MIN_INTERVAL_SECONDS", gt=0.0
    )
    # Frozen regression baseline (ATLAS_V1_FROZEN.md). Empty = no
    # baseline loaded, which is the historical behaviour: every replay
    # then reports quality WITHOUT a regression section, because there
    # is nothing to diff against. Record one with
    # `scripts/atlas_record_baseline.py` and point this at it to make
    # the Quality Gate's regression half actually able to fire.
    regression_baseline_path: str = Field(
        default="", alias="ATLAS_REGRESSION_BASELINE_PATH"
    )
    atlas_consumer_group: str = Field(
        default="insight-atlas", alias="ATLAS_CONSUMER_GROUP"
    )
    atlas_consumer_name: str = Field(
        default="atlas-1", alias="ATLAS_CONSUMER_NAME"
    )
    atlas_dlq_stream: str = Field(
        default="insight:stream:dlq", alias="ATLAS_DLQ_STREAM"
    )
    atlas_processed_event_prefix: str = Field(
        default="atlas:processed_events:", alias="ATLAS_PROCESSED_EVENT_PREFIX"
    )
    atlas_retry_key_prefix: str = Field(
        default="atlas:canonical_retry:", alias="ATLAS_RETRY_KEY_PREFIX"
    )
    # Idempotency-ledger + handler-retry-counter keys are per-event_id and
    # otherwise live forever (every event Atlas has ever processed leaves a
    # permanent Redis key). A production consumer never needs idempotency
    # protection older than a plausible redelivery/outage window; 7 days is
    # generous relative to XAUTOCLAIM's pending_reclaim_idle_ms (seconds).
    atlas_processed_ttl_seconds: int = Field(
        default=604_800, alias="ATLAS_PROCESSED_TTL_SECONDS"
    )
    atlas_pending_reclaim_idle_ms: int = Field(
        default=60_000, alias="ATLAS_PENDING_RECLAIM_IDLE_MS"
    )
    atlas_max_handler_attempts: int = Field(
        default=5, alias="ATLAS_MAX_HANDLER_ATTEMPTS"
    )

    def canonical_streams(self) -> list[str]:
        """Returns the ordered list of streams the consumer subscribes
        to. The odds stream is included when CANONICAL_ODDS_ENABLED is
        set (default on) — it is the operational home of the
        first-class odds-history dataset.
        """
        streams = [self.canonical_stream_match, self.canonical_stream_context]
        if self.canonical_odds_enabled:
            streams.append(self.canonical_stream_odds)
        return streams

    # --- Probes ---
    health_host: str = Field(default="0.0.0.0", alias="HEALTH_HOST")
    health_port: int = Field(default=8085, alias="HEALTH_PORT")

    # --- Observability ---
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    otel_service_name: str = Field(default="atlas", alias="OTEL_SERVICE_NAME")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator(
        "http_port",
        "health_port",
        "database_pool_size",
        "database_max_overflow",
        "stream_partitions",
        "max_payload_bytes",
        "feature_hot_ttl_seconds",
        "inference_cache_ttl_seconds",
        "feature_worker_interval_seconds",
        "feature_schema_version",
        "historical_train_until_year",
        "historical_validation_year",
        "historical_test_year",
        "atlas_pending_reclaim_idle_ms",
        "atlas_max_handler_attempts",
        "atlas_processed_ttl_seconds",
        "odds_hot_ttl_seconds",
        "odds_history_limit",
        "identity_tolerance_seconds",
        "match_context_ttl_seconds",
        "trend_stream_maxlen",
        "trend_cooldown_seconds",
        "trend_lifecycle_expiry_seconds",
        "trend_correlation_window_seconds",
        "watcher_interval_seconds",
        "watcher_window_seconds",
        "janitor_inactivity_seconds",
    )
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be positive")
        return v

    @model_validator(mode="after")
    def _watcher_jitter_fits_interval(self) -> Settings:
        if self.watcher_jitter_seconds < 0:
            raise ValueError("ATLAS_WATCHER_JITTER_SECONDS must be >= 0")
        if self.watcher_jitter_seconds >= self.watcher_interval_seconds:
            raise ValueError(
                "ATLAS_WATCHER_JITTER_SECONDS must be smaller than "
                "ATLAS_WATCHER_INTERVAL_SECONDS"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def _reset_settings_cache() -> None:
    get_settings.cache_clear()
