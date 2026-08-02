"""Read-model service for the Console (Step 11).

Pure data access over the data lake reports/ — no FastAPI dependency, so it
is unit-testable and the HTTP layer (app.py) is a thin wrapper. The Console
reads these APIs only, never the lake directly (ML_A_CONSOLE_OPERATIONS).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from explorer.clubs import registry_size as _registry_size
from explorer.config import DATA_LAKE_ROOT
from explorer.observability import metrics
from explorer.observability.telemetry import Telemetry

_LAYERS = ("raw", "normalized", "validated", "reports")


class ExplorerReadService:
    def __init__(self, root: Path | str = DATA_LAKE_ROOT) -> None:
        self.root = Path(root)
        self.telemetry = Telemetry(self.root)

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        out = []
        for line in path.read_text("utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def jobs(self, status: str | None = None, competition: str | None = None,
             season: str | None = None) -> list[dict[str, Any]]:
        rows = self._read_jsonl(self.root / "reports" / "jobs" / "jobs.jsonl")
        if status:
            rows = [r for r in rows if r.get("status") == status]
        if competition:
            rows = [r for r in rows if r.get("competition") == competition]
        if season:
            rows = [r for r in rows if r.get("season") == season]
        return rows

    def job(self, job_id: str) -> dict[str, Any] | None:
        return next((r for r in self.jobs() if r.get("job_id") == job_id), None)

    def tickets(self, status: str | None = "open") -> list[dict[str, Any]]:
        d = self.root / "reports" / "tickets"
        rows: list[dict[str, Any]] = []
        if d.exists():
            for f in sorted(d.glob("*.jsonl")):
                rows.extend(self._read_jsonl(f))
        # latest snapshot wins per ticket_id
        latest: dict[str, dict[str, Any]] = {}
        for r in rows:
            latest[r.get("ticket_id", id(r))] = r
        out = list(latest.values())
        if status:
            out = [r for r in out if r.get("status") == status]
        return out

    def scheduler_state(self) -> dict[str, Any]:
        path = self.root / "reports" / "scheduler_state.json"
        if not path.exists():
            return {"status": "not_started", "completed": [], "current": None, "remaining": []}
        state = json.loads(path.read_text("utf-8"))
        from explorer.scheduler import PLAN

        completed = {tuple(t) for t in state.get("completed", [])}
        remaining = [list(t) for t in PLAN if tuple(t) not in completed]
        state["remaining"] = remaining
        state["plan_total"] = len(PLAN)
        return state

    # --- ML-B.6 operations read model ------------------------------------

    def jobs_active(self) -> list[dict[str, Any]]:
        return self.jobs(status="running")

    def jobs_history(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.jobs()
        rows.sort(key=lambda r: r.get("finished_at") or r.get("started_at") or "", reverse=True)
        return rows[:limit]

    def status(self) -> dict[str, Any]:
        sched = self.scheduler_state()
        jobs = self.jobs()
        done = [j for j in jobs if j.get("status") == "completed"]
        return {
            "service": "insight-explorer",
            "version": "0.0.2",
            "scheduler_status": sched.get("status"),
            "current": sched.get("current"),
            "plan_total": sched.get("plan_total"),
            "plan_completed": len(sched.get("completed", [])),
            "plan_remaining": len(sched.get("remaining", [])),
            "jobs_total": len(jobs),
            "jobs_completed": len(done),
            "records_validated": sum(j.get("records_validated", 0) for j in done),
            "records_review": sum(j.get("records_review", 0) for j in done),
            "records_rejected": sum(j.get("records_rejected", 0) for j in done),
            "open_tickets": len(self.tickets(status="open")),
            "ai_backend": next((j.get("ai_backend") for j in reversed(jobs) if j.get("ai_backend")), None),
        }

    # --- datasets (Part 4) ----------------------------------------------

    def _iter_partitions(self, layer: str):
        base = self.root / layer
        if not base.exists():
            return
        for comp in sorted(p for p in base.iterdir() if p.is_dir()):
            for season in sorted(p for p in comp.iterdir() if p.is_dir()):
                for source in sorted(p for p in season.iterdir() if p.is_dir()):
                    for entity in sorted(p for p in source.iterdir() if p.is_dir()):
                        yield comp.name, season.name, source.name, entity.name, entity

    @staticmethod
    def _count_lines(d: Path) -> tuple[int, int, int]:
        files = list(d.glob("*.jsonl"))
        records = 0
        last = 0.0
        for f in files:
            with f.open("rb") as fh:
                records += sum(1 for _ in fh)
            last = max(last, f.stat().st_mtime)
        return len(files), records, int(last)

    def datasets(self) -> list[dict[str, Any]]:
        jobs = self.jobs()
        # index validated/review/rejected per (competition, season, source)
        agg: dict[tuple, dict[str, int]] = {}
        for j in jobs:
            k = (j.get("competition"), j.get("season"), j.get("source"))
            a = agg.setdefault(k, {"validated": 0, "review": 0, "rejected": 0})
            a["validated"] += j.get("records_validated", 0)
            a["review"] += j.get("records_review", 0)
            a["rejected"] += j.get("records_rejected", 0)
        out = []
        for comp, season, source, entity, d in self._iter_partitions("validated"):
            files, records, last = self._count_lines(d)
            counts = agg.get((comp, season, source), {})
            out.append({
                "competition": comp, "season": season, "source": source,
                "entity_type": entity, "files": files, "records": records,
                "validated": counts.get("validated", records),
                "review": counts.get("review", 0), "rejected": counts.get("rejected", 0),
                "storage_bytes": sum(f.stat().st_size for f in d.glob("*.jsonl")),
                "last_update": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last)) if last else None,
            })
        return out

    def dataset_detail(self, competition: str) -> dict[str, Any]:
        rows = [d for d in self.datasets() if d["competition"] == competition]
        seasons = sorted({d["season"] for d in rows})
        sources = sorted({d["source"] for d in rows})
        return {
            "competition": competition, "seasons": seasons, "sources": sources,
            "partitions": rows,
            "totals": {
                "records": sum(d["records"] for d in rows),
                "validated": sum(d["validated"] for d in rows),
                "review": sum(d["review"] for d in rows),
                "rejected": sum(d["rejected"] for d in rows),
                "storage_bytes": sum(d["storage_bytes"] for d in rows),
            },
        }

    # --- sources (Part 4 health) ----------------------------------------

    def sources(self) -> list[dict[str, Any]]:
        from explorer.ops import runtime_config
        from explorer.sources import build_default_registry

        cfg = runtime_config.load(self.root)
        jobs = self.jobs()
        out = []
        for adapter in build_default_registry():
            sjobs = [j for j in jobs if j.get("source") == adapter.name]
            out.append({
                "name": adapter.name,
                "trust_level": getattr(adapter, "trust_level", "unknown"),
                "enabled": cfg.source_enabled(adapter.name),
                "jobs_run": len(sjobs),
                "records_collected": sum(j.get("records_collected", 0) for j in sjobs),
                "records_validated": sum(j.get("records_validated", 0) for j in sjobs),
                "last_run": max((j.get("finished_at", "") for j in sjobs), default=None),
            })
        return out

    # --- agents / CrewAI (Part 5) ---------------------------------------

    def agents(self) -> dict[str, Any]:
        from explorer.ai.crew import AGENTS

        rows = self.telemetry.read("agents.jsonl")
        per: dict[str, dict[str, Any]] = {}
        for name, spec in AGENTS.items():
            per[name] = {"agent": name, "role": spec.role, "tasks_executed": 0,
                         "prompt_tokens": 0, "completion_tokens": 0, "successes": 0,
                         "failures": 0, "latency_sum": 0.0, "last_execution": None,
                         "last_backend": None, "examples": []}
        for r in rows:
            a = per.get(r.get("agent"))
            if not a:
                continue
            a["tasks_executed"] += 1
            a["prompt_tokens"] += r.get("prompt_tokens", 0)
            a["completion_tokens"] += r.get("completion_tokens", 0)
            a["successes"] += 1 if r.get("success") else 0
            a["failures"] += 0 if r.get("success") else 1
            a["latency_sum"] += r.get("latency_s", 0.0)
            a["last_execution"] = r.get("ts")
            a["last_backend"] = r.get("backend")
            if r.get("success") and len(a["examples"]) < 3:
                a["examples"].append({"input": r.get("sample_input"), "output": r.get("sample_output"),
                                      "ts": r.get("ts")})
        for a in per.values():
            n = a["tasks_executed"]
            a["avg_latency_s"] = round(a["latency_sum"] / n, 3) if n else 0.0
            a["success_rate"] = round(a["successes"] / n, 3) if n else None
            a["failure_rate"] = round(a["failures"] / n, 3) if n else None
            a.pop("latency_sum")
        return {"agents": list(per.values()),
                "total_calls": sum(a["tasks_executed"] for a in per.values())}

    # --- LangGraph (Part 6) ---------------------------------------------

    def langgraph(self) -> dict[str, Any]:
        from explorer.ai.graph import NODE_SEQUENCE, describe

        runs = self.telemetry.read("graph.jsonl")
        completed = [r for r in runs if r.get("outcome") == "completed"]
        failed = [r for r in runs if r.get("outcome") == "failed"]
        tot_v = sum(r.get("validated", 0) for r in completed)
        tot_r = sum(r.get("rejected", 0) for r in completed)
        tot_rev = sum(r.get("review", 0) for r in completed)
        approvable = tot_v + tot_r + tot_rev
        durs = [r.get("duration_s", 0.0) for r in completed]
        return {
            "graph": describe(),
            "node_sequence": list(NODE_SEQUENCE),
            "workflows_total": len(runs),
            "workflows_completed": len(completed),
            "workflows_failed": len(failed),
            "avg_duration_s": round(sum(durs) / len(durs), 3) if durs else 0.0,
            "approval_rate": round(tot_v / approvable, 3) if approvable else None,
            "rejection_rate": round(tot_r / approvable, 3) if approvable else None,
            "review_rate": round(tot_rev / approvable, 3) if approvable else None,
            "latest_runs": runs[-10:],
        }

    # --- Qwen (Part 7) --------------------------------------------------

    def qwen(self) -> dict[str, Any]:
        from explorer.ops.qwen import runtime

        rt = runtime()
        agents = self.agents()
        rt["ai_requests"] = agents["total_calls"]
        rt["ai_tokens"] = sum(a["prompt_tokens"] + a["completion_tokens"] for a in agents["agents"])
        rt["ai_failures"] = sum(a["failures"] for a in agents["agents"])
        lat = [a["avg_latency_s"] for a in agents["agents"] if a["tasks_executed"]]
        rt["avg_latency_s"] = round(sum(lat) / len(lat), 3) if lat else 0.0
        return rt

    # --- quality (Part 9) -----------------------------------------------

    def quality(self) -> dict[str, Any]:
        jobs = [j for j in self.jobs() if j.get("status") == "completed"]
        coll = sum(j.get("records_collected", 0) for j in jobs)
        val = sum(j.get("records_validated", 0) for j in jobs)
        rev = sum(j.get("records_review", 0) for j in jobs)
        rej = sum(j.get("records_rejected", 0) for j in jobs)
        dup = sum(j.get("duplicates_removed", 0) for j in jobs)
        considered = val + rev + rej
        recon = self._reconciliation_summaries()
        agree = sum(r.get("agreements", 0) for r in recon)
        multi = sum(r.get("multi_source_matches", 0) for r in recon)
        trend = [{"competition": j.get("competition"), "season": j.get("season"),
                  "source": j.get("source"),
                  "validation_rate": round(j.get("records_validated", 0) /
                                           max(1, j.get("records_validated", 0) + j.get("records_review", 0)
                                               + j.get("records_rejected", 0)), 3)}
                 for j in self.jobs_history(20)]
        return {
            "records_collected": coll, "records_validated": val, "records_review": rev,
            "records_rejected": rej, "duplicates_removed": dup,
            "validation_rate": round(val / considered, 3) if considered else None,
            "review_rate": round(rev / considered, 3) if considered else None,
            "rejection_rate": round(rej / considered, 3) if considered else None,
            "duplicate_rate": round(dup / coll, 3) if coll else None,
            "entity_resolution_success_rate": round(val / (val + rev), 3) if (val + rev) else None,
            "source_agreement_rate": round(agree / multi, 3) if multi else None,
            "multi_source_matches": multi,
            "quality_trend": trend,
        }

    def _reconciliation_summaries(self) -> list[dict[str, Any]]:
        base = self.root / "reports" / "reconciliation"
        out = []
        if base.exists():
            for f in base.rglob("*.json"):
                try:
                    out.append(json.loads(f.read_text("utf-8")).get("summary", {}))
                except json.JSONDecodeError:
                    continue
        return out

    # --- storage (Part 10) ----------------------------------------------

    def storage(self) -> dict[str, Any]:
        layers = {}
        total = 0
        for layer in _LAYERS:
            base = self.root / layer
            size = sum(f.stat().st_size for f in base.rglob("*") if f.is_file()) if base.exists() else 0
            layers[layer] = size
            total += size
        # growth estimate from job history span
        hist = self.jobs_history(1000)
        return {
            "layers_bytes": layers,
            "total_bytes": total,
            "total_mb": round(total / 1e6, 2),
            "completed_tasks": len([j for j in hist if j.get("status") == "completed"]),
            "note": "raw preserves every source response; validated holds envelopes",
        }

    # --- runtime (Part 2 /runtime) --------------------------------------

    def runtime(self) -> dict[str, Any]:
        from explorer.ops import runtime_config

        cfg = runtime_config.load(self.root)
        return {
            "status": self.status(),
            "scheduler": self.scheduler_state(),
            "sources": self.sources(),
            "qwen": self.qwen(),
            "storage": self.storage(),
            "config": {"disabled_sources": cfg.disabled_sources,
                       "scheduler_paused": cfg.scheduler_paused, "use_ai": cfg.use_ai},
        }

    def audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.telemetry.read("audit.jsonl", limit=limit)

    # --- ML-C: entity resolution center (Part 3) ------------------------

    def entity_resolution(self) -> dict[str, Any]:
        jobs = [j for j in self.jobs() if j.get("status") == "completed"]
        validated = sum(j.get("records_validated", 0) for j in jobs)  # both teams resolved
        review = sum(j.get("records_review", 0) for j in jobs)        # ≥1 unresolved
        from explorer.ops.review import ReviewStore

        rev = ReviewStore(self.root)
        unresolved = [r for r in rev.queue(status="pending", limit=100000)
                      if r.get("reason") == "entity_unresolved"]
        # AI (CrewAI Entity Resolver) calls = human-augmented resolution attempts.
        agent_rows = [a for a in self.agents()["agents"] if a["agent"] == "entity_resolver"]
        ai_attempts = agent_rows[0]["tasks_executed"] if agent_rows else 0
        total = validated + review
        return {
            "resolved": validated,                       # deterministic registry hits
            "ambiguous": 0,
            "unresolved": len(unresolved),
            "auto_resolved": validated,                  # via Club Registry, no human
            "human_reviewed": review,                    # routed to operator review
            "ai_resolution_attempts": ai_attempts,       # CrewAI Entity Resolver (Qwen)
            "resolution_rate": round(validated / total, 4) if total else None,
            "registry_size": _registry_size(),
            "explanations": [
                {"competition": r["competition"], "season": r["season"],
                 "external_id": r["external_id"],
                 "explanation": "one or both teams not found in the Club Registry → "
                                "routed to human review (never dropped/fabricated)"}
                for r in unresolved[:25]
            ],
        }

    # --- ML-C: duplicate detection (Part 6) -----------------------------

    def duplicates(self) -> dict[str, Any]:
        jobs = [j for j in self.jobs() if j.get("status") == "completed"]
        by_entity: dict[str, dict[str, int]] = {}
        total_dups = total_coll = 0
        for j in jobs:
            et = j.get("entity_type", "fixture")
            d = by_entity.setdefault(et, {"collected": 0, "duplicates_removed": 0})
            d["collected"] += j.get("records_collected", 0)
            d["duplicates_removed"] += j.get("duplicates_removed", 0)
            total_dups += j.get("duplicates_removed", 0)
            total_coll += j.get("records_collected", 0)
        for d in by_entity.values():
            d["duplicate_rate"] = round(d["duplicates_removed"] / d["collected"], 4) if d["collected"] else 0.0
        return {
            "by_entity_type": by_entity,
            "total_duplicates_removed": total_dups,
            "overall_duplicate_rate": round(total_dups / total_coll, 4) if total_coll else 0.0,
            "method": "checksum (provenance.checksum) + logical key (source+external_id); "
                      "replay-safe lake append dedup",
        }

    # --- ML-C: dataset quality engine (Part 4) --------------------------

    def quality_datasets(self) -> dict[str, Any]:
        from explorer.ops.quality_engine import score_dataset

        jobs = [j for j in self.jobs() if j.get("status") == "completed"]
        recon = {(r.get("competition"), r.get("season")): r for r in self._reconciliation_summaries()}

        def agreement_for(comp: str, season: str) -> float | None:
            r = recon.get((comp, season))
            if not r or not r.get("multi_source_matches"):
                return None
            return round(r.get("agreements", 0) / r["multi_source_matches"], 4)

        per_dataset = []
        groups: dict[tuple, list] = {}
        for j in jobs:
            groups.setdefault((j["competition"], j["season"], j["source"]), []).append(j)
        for (comp, season, source), js in sorted(groups.items()):
            sc = score_dataset(js, agreement_for(comp, season))
            per_dataset.append({"competition": comp, "season": season, "source": source, **sc})

        per_comp = []
        cgroups: dict[str, list] = {}
        for j in jobs:
            cgroups.setdefault(j["competition"], []).append(j)
        for comp, js in sorted(cgroups.items()):
            sc = score_dataset(js, None)
            per_comp.append({"competition": comp, **sc})

        overall = score_dataset(jobs, None)["quality_score"] if jobs else 0.0
        return {"overall_quality_score": overall, "per_competition": per_comp,
                "per_dataset": per_dataset}

    # --- ML-C: review backlog (Part 5) ----------------------------------

    def review_queue(self, status: str = "pending", competition: str | None = None) -> dict[str, Any]:
        from explorer.ops.review import ReviewStore

        rev = ReviewStore(self.root)
        return {"items": rev.queue(status=status, competition=competition),
                "stats": rev.stats()}

    # --- ML-C: historical analytics (Part 7) ----------------------------

    def analytics(self) -> dict[str, Any]:
        jobs = [j for j in self.jobs() if j.get("status") == "completed"]
        per_comp: dict[str, dict[str, int]] = {}
        per_season: dict[str, dict[str, int]] = {}
        per_source: dict[str, int] = {}
        for j in jobs:
            for key, bucket in ((j["competition"], per_comp), (j["season"], per_season)):
                b = bucket.setdefault(key, {"validated": 0, "review": 0, "rejected": 0, "collected": 0})
                b["validated"] += j.get("records_validated", 0)
                b["review"] += j.get("records_review", 0)
                b["rejected"] += j.get("records_rejected", 0)
                b["collected"] += j.get("records_collected", 0)
            per_source[j["source"]] = per_source.get(j["source"], 0) + j.get("records_validated", 0)
        history = self.jobs_history(60)
        return {
            "records_per_competition": per_comp,
            "records_per_season": per_season,
            "source_contribution": per_source,
            "validation_trend": [
                {"competition": h["competition"], "season": h["season"], "source": h["source"],
                 "validated": h.get("records_validated", 0), "review": h.get("records_review", 0),
                 "finished_at": h.get("finished_at")}
                for h in history
            ],
            "totals": {
                "validated": sum(b["validated"] for b in per_comp.values()),
                "review": sum(b["review"] for b in per_comp.values()),
                "rejected": sum(b["rejected"] for b in per_comp.values()),
            },
        }

    def metrics_text(self) -> bytes:
        return metrics.render()
