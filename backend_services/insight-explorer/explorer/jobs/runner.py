"""Job runner (Steps 5/9/10/14).

One job = one (source, competition, season). The runner:
  1. probes source health (→ explorer_sources_online, source_offline ticket),
  2. collects raw artifacts with source isolation (FetchError → ticket,
     never crashes the run),
  3. preserves every raw response in the raw/ layer (replay-safe),
  4. runs the AI-orchestrated QualityPipeline,
  5. writes validated envelopes to validated/ and ALL rejected/review
     records to reports/rejected/ (Step 9 — never silently dropped),
  6. emits metrics + a structured job record persisted to reports/jobs/.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from explorer.adapters.base import RawArtifact, SourceAdapter
from explorer.ai.crew import Crew
from explorer.ai.pipeline import QualityPipeline
from explorer.collectors.http import FetchError
from explorer.config import DUPLICATION_RATIO_TICKET_THRESHOLD, REJECT_RATE_TICKET_THRESHOLD
from explorer.datalake.lake import DataLake
from explorer.observability import metrics
from explorer.observability.logging import get_logger
from explorer.tickets.tickets import TicketStore


@dataclass
class JobRecord:
    source: str
    competition: str
    season: str
    entity_type: str = "fixture"
    status: str = "pending"
    records_collected: int = 0
    records_normalized: int = 0
    records_validated: int = 0
    records_rejected: int = 0
    records_review: int = 0
    duplicates_removed: int = 0
    duration_ms: int = 0
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: str = ""
    finished_at: str = ""
    error: str | None = None
    ai_backend: str = ""
    ai_used: bool = False
    graph_engine: str = ""
    execution_id: str = ""  # set when run as part of a Mission Center pipeline execution


class JobRunner:
    def __init__(self, lake: DataLake | None = None, tickets: TicketStore | None = None,
                 use_ai: bool = True, crew: Crew | None = None) -> None:
        self.lake = lake or DataLake()
        self.tickets = tickets or TicketStore(self.lake.root)
        self.use_ai = use_ai
        self.crew = crew or Crew()
        self.log = get_logger("explorer.job")

    def run(self, adapter: SourceAdapter, competition: str, season: str,
            execution_id: str = "") -> JobRecord:
        rec = JobRecord(source=adapter.name, competition=competition, season=season,
                        status="running", started_at=_now(), execution_id=execution_id)
        log = self.log.bind(job_id=rec.job_id, source=rec.source,
                            competition=competition, season=season)
        log.info("job_started")
        t0 = time.monotonic()

        if not adapter.supports(competition):
            rec.status = "skipped"
            rec.error = "adapter does not support competition"
            log.warning("job_skipped", reason=rec.error)
            self._finish(rec, t0)
            return rec

        # 1. health probe
        online = _safe_health(adapter)
        metrics.sources_online.labels(source=adapter.name).set(1 if online else 0)
        if not online:
            metrics.sources_failed.labels(source=adapter.name).inc()
            self.tickets.open(error_type="source_offline", source=adapter.name,
                              competition=competition, season=season, entity_type="fixture",
                              severity="high")
            rec.status = "failed"
            rec.error = "source offline"
            log.error("source_offline")
            self._finish(rec, t0)
            return rec

        # 2/3. collect + preserve raw (source-isolated)
        artifacts: list[RawArtifact] = []
        try:
            for art in adapter.fetch_season(competition, season):
                artifacts.append(art)
        except FetchError as exc:
            metrics.sources_failed.labels(source=adapter.name).inc()
            self.tickets.open(error_type="source_offline", source=adapter.name,
                              competition=competition, season=season, entity_type="fixture",
                              severity="high", sample_payload={"error": str(exc)},
                              retry_count=1)
            log.error("collect_failed", error=str(exc))
        except Exception as exc:  # noqa: BLE001 - crawler crash → ticket, keep partial
            self.tickets.open(error_type="collector_crash", source=adapter.name,
                              competition=competition, season=season, entity_type="fixture",
                              severity="high", sample_payload={"error": str(exc)})
            log.error("collector_crash", error=str(exc))

        rec.records_collected = len(artifacts)
        for art in artifacts:
            metrics.records_collected_total.labels(
                competition=competition, source=adapter.name, entity_type=art.entity_type).inc()
        if artifacts:
            self.lake.append("raw", competition, season, adapter.name, "fixture",
                             ({"_checksum": _cs(a.raw), **_raw_record(a)} for a in artifacts))
        log.info("collected", records=rec.records_collected)

        # 4. AI-orchestrated quality pipeline
        pipeline = QualityPipeline(self.tickets, crew=self.crew, use_ai=self.use_ai)
        state = pipeline.run(artifacts, competition, season, adapter.name)
        rec.records_normalized = len(state.normalized) + len(state.validated) + len(state.review)
        rec.records_validated = len(state.validated)
        rec.records_review = len(state.review)
        rec.records_rejected = len(state.rejected)
        rec.duplicates_removed = state.stats.get("duplicates_removed", 0)
        rec.ai_backend = state.stats.get("ai_backend", "")
        rec.ai_used = bool(state.stats.get("ai_used"))
        rec.graph_engine = state.stats.get("graph_engine", "")

        # 5. write validated + preserve rejected/review (never drop)
        if state.validated:
            self.lake.append("validated", competition, season, adapter.name, "fixture", state.validated)
        if state.rejected:
            self.lake.append_report_lines(
                "rejected", competition, season, adapter.name, f"{rec.job_id}.jsonl",
                records=[{**r, "_class": "rejected"} for r in state.rejected])
        # Review backlog (ML-C Part 5): keep the FULL envelope so an operator can
        # promote/reject from the queue. Append-only per competition/season/source.
        if state.review:
            self.lake.append_report_lines(
                "review", competition, season, adapter.name, "queue.jsonl",
                records=[{"reason": r.get("reason"), "stage": r.get("stage"),
                          "quality": r.get("quality"), "job_id": rec.job_id,
                          "status": "pending",
                          "external_id": (r.get("envelope") or {}).get("external_id"),
                          "envelope": r.get("envelope")} for r in state.review])

        # threshold tickets
        considered = rec.records_validated + rec.records_rejected
        reject_rate = rec.records_rejected / considered if considered else 0.0
        if reject_rate > REJECT_RATE_TICKET_THRESHOLD:
            self.tickets.open(error_type="validation_threshold", source=adapter.name,
                              competition=competition, season=season, entity_type="fixture",
                              severity="medium", sample_payload={"reject_rate": round(reject_rate, 3)})
        if state.stats.get("duplication_ratio", 0) > DUPLICATION_RATIO_TICKET_THRESHOLD:
            self.tickets.open(error_type="mass_duplication", source=adapter.name,
                              competition=competition, season=season, entity_type="fixture",
                              severity="medium",
                              sample_payload={"ratio": state.stats["duplication_ratio"]})

        rec.status = "completed"
        self._finish(rec, t0)
        for layer in ("raw", "validated"):
            metrics.dataset_size_bytes.labels(layer=layer).set(self.lake.layer_size_bytes(layer))
        metrics.jobs_total.labels(competition=competition, source=adapter.name,
                                  status=rec.status).inc()
        metrics.job_duration_seconds.labels(competition=competition,
                                             source=adapter.name).observe(rec.duration_ms / 1000)
        log.info("job_completed", validated=rec.records_validated, rejected=rec.records_rejected,
                 review=rec.records_review, duration_ms=rec.duration_ms)
        return rec

    def _finish(self, rec: JobRecord, t0: float) -> None:
        rec.finished_at = _now()
        rec.duration_ms = int((time.monotonic() - t0) * 1000)
        d = self.lake.root / "reports" / "jobs"
        d.mkdir(parents=True, exist_ok=True)
        with (d / "jobs.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(rec), ensure_ascii=False, default=str) + "\n")


def _raw_record(a: RawArtifact) -> dict[str, Any]:
    return {"external_id": a.external_id, "competition_key": a.competition_key,
            "season": a.season, "source": a.source, "provider": a.provider,
            "url": a.url, "retrieved_at": a.retrieved_at, "raw": a.raw}


def _cs(obj: Any) -> str:
    from explorer.datalake.lake import checksum

    return checksum(obj)


def _safe_health(adapter: SourceAdapter) -> bool:
    try:
        return adapter.health()
    except Exception:  # noqa: BLE001
        return False


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
