"""Redis client factory bound to Anvil's own settings (the legacy
version read the retired Playmaker service's settings)."""

from __future__ import annotations

from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool

from anvil.config import get_settings


def create_redis_client() -> Redis:
    settings = get_settings()
    pool = ConnectionPool.from_url(
        settings.redis_url,
        max_connections=settings.redis_max_connections,
        socket_timeout=settings.redis_socket_timeout_seconds,
        health_check_interval=settings.redis_health_check_interval_seconds,
        retry_on_timeout=settings.redis_retry_on_timeout,
        decode_responses=False,  # bytes for perf + cross-service compat
    )
    return Redis(connection_pool=pool)
