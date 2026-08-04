"""Central, source-agnostic configuration for the Explorer service.

Adding a competition is a config row here (Step 1: no architectural change).
Nothing in this module imports the AI stack or the network layer, so it is
safe to import everywhere (tests, CLI, API).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# --- Data lake -----------------------------------------------------------

DATA_LAKE_ROOT = Path(os.environ.get("EXPLORER_DATA_LAKE", "/home/insight/data/explorer"))

LAKE_LAYERS = ("raw", "normalized", "validated", "training", "exports", "reports", "signals")


# --- AI runtime (Ollama + local Qwen) ------------------------------------

OLLAMA_HOST = os.environ.get("EXPLORER_OLLAMA_HOST", "http://localhost:11434")
QWEN_MODEL = os.environ.get("EXPLORER_QWEN_MODEL", "qwen2.5")
AI_REQUEST_TIMEOUT_S = float(os.environ.get("EXPLORER_AI_TIMEOUT", "60"))
# Hard rule (Step 8): no cloud LLMs, no fallback providers. The only model
# is local Qwen via Ollama. If it is unreachable the job degrades + tickets.


# --- Competition registry (Step 0/1 — patched with Libertadores) ---------


@dataclass(frozen=True)
class Competition:
    """A collectable competition. `espn_league` is the only source-specific
    field; a source that does not know a competition simply skips it."""

    competition_key: str
    name: str
    espn_league: str | None
    default_trust: str = "medium"


COMPETITIONS: dict[str, Competition] = {
    "brasileirao_serie_a": Competition(
        "brasileirao_serie_a", "Campeonato Brasileiro Série A", "bra.1"
    ),
    "copa_do_brasil": Competition("copa_do_brasil", "Copa do Brasil", "bra.copa_do_brazil"),
    "libertadores": Competition(  # Step 0 addition
        "libertadores", "CONMEBOL Libertadores", "conmebol.libertadores"
    ),
    "premier_league": Competition("premier_league", "Premier League", "eng.1"),
    "la_liga": Competition("la_liga", "La Liga", "esp.1"),
    "champions_league": Competition("champions_league", "UEFA Champions League", "uefa.champions"),
    "world_cup": Competition("world_cup", "FIFA World Cup", "fifa.world"),
}


# --- Collector behaviour (Step 5) ----------------------------------------


@dataclass(frozen=True)
class CollectorConfig:
    request_timeout_s: float = 12.0
    max_retries: int = 4
    backoff_base_s: float = 0.6
    backoff_max_s: float = 8.0
    polite_delay_s: float = 0.15  # between requests to the same source
    user_agents: tuple[str, ...] = field(
        default_factory=lambda: (
            "InsightExplorer/0.1 (+https://konohalabs.com.br; research)",
            "Mozilla/5.0 (X11; Linux x86_64) InsightExplorer/0.1",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) InsightExplorer/0.1",
        )
    )


COLLECTOR = CollectorConfig()


# --- Quality / ticket thresholds (Step 9/12) -----------------------------

REJECT_RATE_TICKET_THRESHOLD = 0.20
DUPLICATION_RATIO_TICKET_THRESHOLD = 0.50
QUALITY_APPROVE_THRESHOLD = 0.70
CONSECUTIVE_JOB_FAILURE_TICKET = 3


# --- Real-time signals (ML-D Phase B) -------------------------------------
# The lake write (signals/ layer) is always authoritative; Redis publish is
# best-effort on top of it — see explorer/realtime/publisher.py.

EXPLORER_REDIS_URL = os.environ.get("EXPLORER_REDIS_URL", "")
EXPLORER_SIGNAL_STREAM_KEY = os.environ.get("EXPLORER_SIGNAL_STREAM_KEY", "insight:stream:events:signals")
EXPLORER_MAX_CONCURRENT_REALTIME_PIPELINES = int(
    os.environ.get("EXPLORER_MAX_CONCURRENT_REALTIME_PIPELINES", "5")
)
