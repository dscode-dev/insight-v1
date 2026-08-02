from __future__ import annotations

from functools import lru_cache

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Redis (derived streams) ---------------------------------------
    redis_url: str = Field(..., alias="REDIS_URL")
    redis_max_connections: int = Field(default=100, alias="REDIS_MAX_CONNECTIONS")
    redis_socket_timeout_seconds: int = Field(default=5, alias="REDIS_SOCKET_TIMEOUT_SECONDS")
    redis_health_check_interval_seconds: int = Field(default=30, alias="REDIS_HEALTH_CHECK_INTERVAL_SECONDS")
    redis_retry_on_timeout: bool = Field(default=True, alias="REDIS_RETRY_ON_TIMEOUT")

    # --- Stream consumption -------------------------------------------
    derived_stream_base_key: str = Field(default="insight:stream:derived", alias="DERIVED_STREAM_BASE_KEY")
    stream_partitions: int = Field(default=8, alias="STREAM_PARTITIONS")
    derived_group_name: str = Field(default="insight:group:anvil:derived", alias="DERIVED_GROUP_NAME")
    consumer_name: str = Field(default="anvil-1", alias="CONSUMER_NAME")

    # Consumer loop (knobs tuned for the analytics
    # workload which is more batch-friendly than the hot-path consumer).
    consumer_block_ms: int = Field(default=2000, alias="CONSUMER_BLOCK_MS")
    consumer_count: int = Field(default=200, alias="CONSUMER_COUNT")
    consumer_claim_idle_ms: int = Field(default=60_000, alias="CONSUMER_CLAIM_IDLE_MS")
    consumer_claim_count: int = Field(default=200, alias="CONSUMER_CLAIM_COUNT")
    consumer_pending_quota: int = Field(default=400, alias="CONSUMER_PENDING_QUOTA")
    consumer_new_quota: int = Field(default=800, alias="CONSUMER_NEW_QUOTA")

    consumer_max_retries: int = Field(default=5, alias="CONSUMER_MAX_RETRIES")
    consumer_backoff_seconds: str = Field(default="1,3,10,30,120", alias="CONSUMER_BACKOFF_SECONDS")
    consumer_retry_hash_prefix: str = Field(default="insight:retry:anvil", alias="CONSUMER_RETRY_HASH_PREFIX")
    consumer_retry_ttl_seconds: int = Field(default=3600, alias="CONSUMER_RETRY_TTL_SECONDS")
    dlq_derived_key: str = Field(default="insight:stream:dlq:derived:anvil", alias="DLQ_DERIVED_KEY")

    max_payload_bytes: int = Field(default=200_000, alias="MAX_PAYLOAD_BYTES")

    # --- ClickHouse ----------------------------------------------------
    clickhouse_host: str = Field(..., alias="CLICKHOUSE_HOST")
    clickhouse_port: int = Field(default=8123, alias="CLICKHOUSE_PORT")
    clickhouse_user: str = Field(default="default", alias="CLICKHOUSE_USER")
    clickhouse_password: str = Field(default="", alias="CLICKHOUSE_PASSWORD")
    clickhouse_database: str = Field(default="insight", alias="CLICKHOUSE_DATABASE")
    clickhouse_secure: bool = Field(default=False, alias="CLICKHOUSE_SECURE")
    clickhouse_query_timeout_seconds: int = Field(default=15, alias="CLICKHOUSE_QUERY_TIMEOUT_SECONDS")

    # --- Batch inserter ------------------------------------------------
    # Two flush triggers: size and age. Whichever fires first.
    batch_max_rows: int = Field(default=500, alias="BATCH_MAX_ROWS")
    batch_max_age_ms: int = Field(default=1000, alias="BATCH_MAX_AGE_MS")
    # Per-table buffer cap. Flush early when one table is hot even if total
    # batch size is below batch_max_rows.
    batch_per_table_cap: int = Field(default=250, alias="BATCH_PER_TABLE_CAP")

    # --- Retention (TTL applied via DDL; this is just for observability) ---
    retention_days_market_snapshots: int = Field(default=90, alias="RETENTION_DAYS_MARKET_SNAPSHOTS")
    retention_days_metric_ticks: int = Field(default=90, alias="RETENTION_DAYS_METRIC_TICKS")
    retention_days_human_signals: int = Field(default=180, alias="RETENTION_DAYS_HUMAN_SIGNALS")

    # --- Probes / observability ---------------------------------------
    health_host: str = Field(default="0.0.0.0", alias="HEALTH_HOST")
    health_port: int = Field(default=8081, alias="HEALTH_PORT")  # 8081 to avoid colliding with Atlas in dev
    readiness_timeout_seconds: float = Field(default=2.0, alias="READINESS_TIMEOUT_SECONDS")
    feature_api_key: str = Field(default="", alias="ANVIL_FEATURE_API_KEY")

    # Migrations applied on startup. Turn off in environments where DDL is
    # owned by an out-of-band migrator (Liquibase, Atlas, etc.).
    auto_apply_migrations: bool = Field(default=True, alias="AUTO_APPLY_MIGRATIONS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @computed_field
    @property
    def derived_stream_keys(self) -> list[str]:
        return [f"{self.derived_stream_base_key}:p{i}" for i in range(self.stream_partitions)]

    @computed_field
    @property
    def consumer_backoff_list(self) -> list[int]:
        return _parse_backoff(self.consumer_backoff_seconds)

    @field_validator(
        "redis_max_connections",
        "stream_partitions",
        "consumer_count",
        "consumer_claim_count",
        "consumer_pending_quota",
        "consumer_new_quota",
        "consumer_max_retries",
        "consumer_retry_ttl_seconds",
        "max_payload_bytes",
        "batch_max_rows",
        "batch_per_table_cap",
        "batch_max_age_ms",
        "health_port",
        "clickhouse_port",
        "clickhouse_query_timeout_seconds",
        "retention_days_market_snapshots",
        "retention_days_metric_ticks",
        "retention_days_human_signals",
    )
    @classmethod
    def _must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be positive")
        return value

    @field_validator("consumer_backoff_seconds")
    @classmethod
    def _backoff_guard(cls, value: str) -> str:
        parsed = _parse_backoff(value)
        if not parsed:
            raise ValueError("consumer_backoff_seconds must not be empty")
        if any(v <= 0 for v in parsed):
            raise ValueError("consumer_backoff_seconds values must be positive")
        return value


def _parse_backoff(csv: str) -> list[int]:
    return [int(x.strip()) for x in csv.split(",") if x.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def _reset_settings_cache() -> None:
    """Test-only: clear the cached settings instance."""
    get_settings.cache_clear()
