"""Polite HTTP fetcher (Step 5): retries, timeouts, exponential backoff,
User-Agent rotation, inter-request delay, per-source isolation.

`requests` is imported lazily so the module imports cleanly in minimal
environments; a fetch without `requests` raises a clear error.
"""

from __future__ import annotations

import random
import time
from typing import Any

from explorer.config import COLLECTOR, CollectorConfig


class FetchError(RuntimeError):
    """Raised after retries are exhausted. The collector turns this into a
    source-isolation event + ticket; it never crashes the whole run."""


class PoliteFetcher:
    def __init__(self, config: CollectorConfig = COLLECTOR, session: Any = None) -> None:
        self.config = config
        self._last_request_ts = 0.0
        if session is not None:
            self._session = session
        else:
            try:
                import requests

                self._session = requests.Session()
            except ImportError:  # pragma: no cover - requests is a core dep
                self._session = None

    def _ua(self) -> str:
        return random.choice(self.config.user_agents)

    def _polite_wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < self.config.polite_delay_s:
            time.sleep(self.config.polite_delay_s - elapsed)

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._get(url, params, accept="application/json").json()

    def get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        return self._get(url, params, accept="text/html").text

    def _get(self, url: str, params: dict[str, Any] | None, accept: str) -> Any:
        if self._session is None:
            raise FetchError("requests is not installed; cannot perform HTTP fetch")
        last_exc: Exception | None = None
        for attempt in range(self.config.max_retries):
            self._polite_wait()
            try:
                resp = self._session.get(
                    url,
                    params=params,
                    timeout=self.config.request_timeout_s,
                    headers={"User-Agent": self._ua(), "Accept": accept},
                )
                self._last_request_ts = time.monotonic()
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise FetchError(f"retryable status {resp.status_code}")
                resp.raise_for_status()
                return resp
            except Exception as exc:  # noqa: BLE001 - retried/backed off below
                last_exc = exc
                self._last_request_ts = time.monotonic()
                backoff = min(
                    self.config.backoff_max_s,
                    self.config.backoff_base_s * (2**attempt),
                ) + random.uniform(0, 0.25)
                if attempt < self.config.max_retries - 1:
                    time.sleep(backoff)
        raise FetchError(f"GET {url} failed after {self.config.max_retries} attempts: {last_exc}")
