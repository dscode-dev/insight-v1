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
    polite_delay_s: float = 1.0  # between requests to the same source
    user_agents: tuple[str, ...] = field(
        default_factory=lambda: (
            # Browser-shaped — and the reason recorded here was WRONG, so
            # read this before trusting it.
            #
            # THE CLAIM THAT USED TO BE HERE: "identifying yourself politely
            # gets 403 from ESPN, verified by controlling for request order".
            # That is why the self-identifying
            # "InsightExplorer/0.1 (+https://konohalabs.com.br; research)"
            # was replaced by these three.
            #
            # WHAT MEASUREMENT ON 2026-08-08 ACTUALLY SHOWED, against
            # site.api.espn.com from two different hosts:
            #
            #     curl/8.0              -> 200
            #     Python-urllib/3.11    -> 200
            #     Chrome 124 (below)    -> 403
            #     no User-Agent at all  -> 200, then 403 two minutes later
            #
            # The last line is the important one. The SAME request answered
            # differently minutes apart, which no User-Agent rule can explain.
            # ESPN is throttling, and every "UA X is blocked" reading — the
            # original one and the inverse — is a snapshot of a moving target.
            #
            # WHY THESE ARE STILL BROWSER-SHAPED. Not because the old reason
            # holds, but because FBRef genuinely does serve HTML behind an
            # anti-scraping edge, and this tuple is shared by every source.
            # Changing it to fix ESPN would be the same mistake in the other
            # direction: a global change justified by one source, unverified
            # against the rest.
            #
            # WHAT WOULD SETTLE IT: a per-source User-Agent, in the shape
            # SOURCE_POLITE_DELAY_S already uses below, decided by N spaced
            # requests per candidate rather than by a handful of consecutive
            # ones. Until someone runs that, this comment describes an open
            # question, not a rule.
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
    )
    # Sent on every request so a source operator can reach us.
    contact: str = "research@konohalabs.com.br"


COLLECTOR = CollectorConfig()

# Per-source delay, in seconds, overriding `polite_delay_s`.
#
# Static files served from a CDN cost the publisher nothing; a rendered page
# costs them a request they did not ask for. The scraped sources therefore get
# a delay measured in seconds, not milliseconds — the collection takes longer
# and stays within what a small site can absorb.
SOURCE_POLITE_DELAY_S: dict[str, float] = {
    "openfootball": 0.2,   # raw.githubusercontent.com, static JSON
    "statsbomb": 0.2,      # raw.githubusercontent.com, static JSON
    "football_data": 0.5,  # static CSV
    "espn": 1.5,           # public JSON API, rate-limits by IP
    "fbref": 6.0,          # scraped HTML
    "wikipedia": 2.0,      # scraped HTML
    "odds_api": 1.0,       # metered API — the quota is the real limit
    "api_football": 1.0,   # metered API
}


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
