"""Redis client factory — connection pool tuned for a stream-IO-bound
service. Configuration is explicit (no hidden settings import) so the
caller's settings object stays the single source of truth.
"""

from __future__ import annotations

from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool


def create_redis_client(
    url: str,
    *,
    max_connections: int = 50,
    socket_timeout_seconds: float = 5.0,
    health_check_interval_seconds: int = 30,
    retry_on_timeout: bool = True,
) -> Redis:
    pool = ConnectionPool.from_url(
        url,
        max_connections=max_connections,
        socket_timeout=socket_timeout_seconds,
        health_check_interval=health_check_interval_seconds,
        retry_on_timeout=retry_on_timeout,
        decode_responses=False,  # bytes for perf + cross-service compat
    )
    return Redis(connection_pool=pool)
