"""Anvil worker entrypoint.

Wires Anvil's own streaming + observability primitives to its
handler + batch inserter. The worker:

  1. Configures structured logging and OTel tracing (env-driven, no-op safe).
  2. Applies ClickHouse migrations (idempotent; can be disabled per env).
  3. Builds a ClickHouse client + BatchInserter + DerivedEventHandler.
  4. Wires the MultiStreamConsumer onto the derived-event streams.
  5. Installs SIGTERM/SIGINT for graceful shutdown — consumer.stop() +
     buffer drain + ClickHouse close.
  6. Serves /live, /ready (CH ping), /metrics on the health port.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from anvil.runtime.logging import configure_logging
from anvil.runtime.tracing import init_tracing
from anvil.runtime.health import HealthServer, HealthServerConfig
from anvil.runtime.redis_factory import create_redis_client
from anvil.streaming.consumer_multi import MultiStreamConsumer, RetryPolicy

from anvil.batch import BatchInserter
from anvil.clickhouse.client import AsyncClickHouseClient, run_migrations
from anvil.config import get_settings
from anvil.handlers import DerivedEventHandler
from anvil.features import FeatureQueryService


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, stop_callbacks: list) -> None:
    """Graceful shutdown on SIGTERM/SIGINT."""
    triggered = {"once": False}

    def _signal_received(signame: str) -> None:
        if triggered["once"]:
            logging.getLogger(__name__).warning(
                "anvil_shutdown_signal_repeat_ignored", extra={"signal": signame}
            )
            return
        triggered["once"] = True
        logging.getLogger(__name__).info(
            "anvil_shutdown_signal_received_draining", extra={"signal": signame}
        )
        for cb in stop_callbacks:
            try:
                cb()
            except Exception:
                logging.getLogger(__name__).exception("anvil_shutdown_callback_failed")

    for sig_name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, sig_name)
        try:
            loop.add_signal_handler(sig, _signal_received, sig_name)
        except NotImplementedError:
            signal.signal(sig, lambda *_: _signal_received(sig_name))


async def main() -> None:
    configure_logging(service="anvil")
    init_tracing(service_name="anvil")
    logger = logging.getLogger(__name__)

    settings = get_settings()

    # ---------- ClickHouse ------------------------------------------------
    ch = AsyncClickHouseClient(settings=settings)
    if settings.auto_apply_migrations:
        logger.info("anvil_applying_migrations")
        try:
            await run_migrations(ch, settings)
        except Exception:
            logger.exception("anvil_migrations_failed")
            raise

    inserter = BatchInserter(
        client=ch,
        max_rows=settings.batch_max_rows,
        per_table_cap=settings.batch_per_table_cap,
        max_age_ms=settings.batch_max_age_ms,
    )
    handler = DerivedEventHandler(inserter=inserter)

    # ---------- Redis -----------------------------------------------------
    r = create_redis_client()

    async def readiness_check() -> tuple[bool, dict]:
        try:
            pong = await r.ping()
        except Exception:
            logger.exception("readiness_check_redis_failed")
            return False, {"redis": "error"}
        try:
            ch_ok = await ch.ping()
        except Exception:
            logger.exception("readiness_check_clickhouse_failed")
            return False, {"redis": "ok" if pong else "not_ok", "clickhouse": "error"}
        return bool(pong) and ch_ok, {
            "redis": "ok" if pong else "not_ok",
            "clickhouse": "ok" if ch_ok else "not_ok",
        }

    health_server = HealthServer(
        cfg=HealthServerConfig(
            host=settings.health_host,
            port=settings.health_port,
            readiness_timeout_seconds=settings.readiness_timeout_seconds,
        ),
        readiness_check=readiness_check,
        feature_api_key=settings.feature_api_key,
        feature_snapshot=FeatureQueryService(ch).snapshot,
    )
    health_task = asyncio.create_task(health_server.serve_forever())

    # ---------- Consumer --------------------------------------------------
    retry_policy = RetryPolicy(
        max_retries=settings.consumer_max_retries,
        backoff_seconds=settings.consumer_backoff_list,
        retry_hash_prefix=settings.consumer_retry_hash_prefix,
        retry_ttl_seconds=settings.consumer_retry_ttl_seconds,
    )

    consumer = MultiStreamConsumer(
        redis_client=r,
        stream_keys=settings.derived_stream_keys,
        group_name=settings.derived_group_name,
        consumer_name=settings.consumer_name,
        dlq_key=settings.dlq_derived_key,
        retry_policy=retry_policy,
        block_ms=settings.consumer_block_ms,
        read_count=settings.consumer_count,
        claim_idle_ms=settings.consumer_claim_idle_ms,
        claim_count=settings.consumer_claim_count,
        pending_quota=settings.consumer_pending_quota,
        new_quota=settings.consumer_new_quota,
        max_payload_bytes=settings.max_payload_bytes,
    )

    # ---------- Buffer-age flusher ----------------------------------------
    # A small background task that asks the inserter to flush whenever the
    # oldest buffered row is older than `batch_max_age_ms`. Without this, a
    # quiet stream would let the last few rows sit until traffic resumes.
    stop_age_flusher = asyncio.Event()

    async def _age_flusher() -> None:
        sleep_interval = max(0.1, settings.batch_max_age_ms / 1000.0 / 4)
        while not stop_age_flusher.is_set():
            try:
                await inserter.maybe_flush_age()
            except Exception:
                logger.exception("anvil_age_flush_failed")
            try:
                await asyncio.wait_for(stop_age_flusher.wait(), timeout=sleep_interval)
            except asyncio.TimeoutError:
                pass

    age_task = asyncio.create_task(_age_flusher())

    # ---------- Graceful shutdown ----------------------------------------
    loop = asyncio.get_running_loop()
    _install_signal_handlers(
        loop,
        stop_callbacks=[consumer.stop, stop_age_flusher.set],
    )

    logger.info(
        "anvil_worker_starting",
        extra={
            "streams": settings.derived_stream_keys,
            "group": settings.derived_group_name,
            "consumer": settings.consumer_name,
            "clickhouse_host": settings.clickhouse_host,
            "clickhouse_database": settings.clickhouse_database,
        },
    )

    try:
        await consumer.start(handler.handle)
    finally:
        # Drain the inserter so the in-flight buffer reaches ClickHouse.
        try:
            await inserter.close()
        except Exception:
            logger.exception("anvil_inserter_close_failed")
        stop_age_flusher.set()
        age_task.cancel()
        try:
            await age_task
        except (asyncio.CancelledError, Exception):
            pass
        health_task.cancel()
        try:
            await health_server.close()
        except Exception:
            logger.exception("anvil_health_server_close_failed")
        try:
            await ch.close()
        except Exception:
            logger.exception("anvil_clickhouse_close_failed")
        try:
            await r.aclose()
        except Exception:
            logger.exception("anvil_redis_close_failed")


if __name__ == "__main__":
    asyncio.run(main())
