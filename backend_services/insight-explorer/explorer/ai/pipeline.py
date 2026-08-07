"""AI-orchestrated quality pipeline (Steps 6/7/9).

Drives raw artifacts through the LangGraph node sequence, delegating every
decision to the deterministic validators and consulting the CrewAI agents
(local Qwen) on ambiguous cases. Guarantees:

- Every normalized object is an explorer.envelope.v1 (Non-negotiable).
- Nothing is silently dropped: rejects + review records are preserved with a
  reason and written to reports/ by the job runner (Step 9).
- Agents never write to validated/: they only annotate `_ai_*` advisory keys;
  the deterministic approve step decides.
- AI degrades with a ticket: if Qwen is unreachable the pipeline records one
  `ai_runtime_unavailable` ticket + ai_failures metric and continues on the
  deterministic path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from explorer.adapters.base import RawArtifact
from explorer.ai import graph as graphmod
from explorer.ai.crew import Crew
from explorer.ai.runtime import AIRuntimeUnavailable
from explorer.config import QUALITY_APPROVE_THRESHOLD
from explorer.normalizers.espn import NormalizationError
from explorer.normalizers.registry import normalize_artifact as normalize
from explorer.observability import metrics
from explorer.observability.telemetry import Telemetry
from explorer.tickets.tickets import TicketStore
from explorer.validators.consistency import check as consistency_check
from explorer.validators.dedup import deduplicate, duplication_ratio
from explorer.validators.quality import score as quality_score
from explorer.validators.schema import validate_envelope

# Consistency violations that are hard rejects vs. send-to-human-review.
_HARD_REJECT = {
    "same_team_both_sides",
    "implausible_score_home",
    "implausible_score_away",
    "scheduled_with_score",
}


@dataclass
class RunState:
    competition: str
    season: str
    source: str
    artifacts: list[RawArtifact] = field(default_factory=list)
    normalized: list[dict[str, Any]] = field(default_factory=list)
    validated: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    review: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


class QualityPipeline:
    def __init__(self, tickets: TicketStore, crew: Crew | None = None, use_ai: bool = True,
                 telemetry: Telemetry | None = None) -> None:
        self.tickets = tickets
        self.crew = crew or Crew()
        self.use_ai = use_ai
        self.ai_available = use_ai
        self._ai_checked = False
        self.telemetry = telemetry or Telemetry(tickets.dir.parent.parent)

    # --- AI helper (degrade-with-ticket) ---------------------------------

    def _ai(self, agent: str, task: str, context: dict[str, Any], state: RunState) -> dict[str, Any] | None:
        if not self.use_ai or not self.ai_available:
            return None
        try:
            if not self._ai_checked:
                self._ai_checked = True
                if not self.crew.health():
                    raise AIRuntimeUnavailable("Qwen model not present / Ollama unreachable")
            res = self.crew.ask(agent, task, context)
            metrics.ai_requests_total.labels(agent=agent, status="ok").inc()
            metrics.ai_tokens_total.labels(agent=agent, kind="prompt").inc(res.prompt_tokens)
            metrics.ai_tokens_total.labels(agent=agent, kind="completion").inc(res.completion_tokens)
            metrics.ai_latency_seconds.labels(agent=agent).observe(res.latency_s)
            self.telemetry.agent_call(
                agent=agent, backend=self.crew.backend, latency_s=res.latency_s,
                prompt_tokens=res.prompt_tokens, completion_tokens=res.completion_tokens,
                success=True, competition=state.competition, season=state.season,
                sample_input=task, sample_output=res.text)
            return {"agent": agent, "text": res.text}
        except AIRuntimeUnavailable as exc:
            self.ai_available = False  # stop hammering a dead runtime this run
            metrics.ai_requests_total.labels(agent=agent, status="error").inc()
            metrics.ai_failures_total.labels(agent=agent, reason="runtime_unavailable").inc()
            self.telemetry.agent_call(
                agent=agent, backend=self.crew.backend, latency_s=0.0, prompt_tokens=0,
                completion_tokens=0, success=False, competition=state.competition,
                season=state.season, sample_input=task, error=str(exc))
            self.tickets.open(
                error_type="ai_runtime_unavailable", source=state.source,
                competition=state.competition, season=state.season, entity_type="fixture",
                severity="high", sample_payload={"agent": agent, "error": str(exc)},
            )
            return None

    # --- nodes (thin delegates; see ai/graph.py NODE_SEQUENCE) -----------

    def collect(self, st: dict) -> dict:
        state: RunState = st["state"]
        # Source Analyst: advisory health/anomaly read of the raw batch.
        sample = [a.raw for a in state.artifacts[:3]]
        finding = self._ai(
            "source_analyst",
            f"Assess {len(state.artifacts)} raw {state.source} artifacts for "
            f"{state.competition} {state.season}. Flag layout drift or missing fields.",
            {"sample": sample}, state,
        )
        state.stats["source_analyst"] = bool(finding)
        return st

    def normalize(self, st: dict) -> dict:
        state: RunState = st["state"]
        for art in state.artifacts:
            try:
                state.normalized.append(normalize(art))
            except NormalizationError as exc:
                state.rejected.append({"stage": "normalize", "reason": str(exc),
                                       "raw_external_id": art.external_id})
                metrics.records_rejected_total.labels(
                    competition=state.competition, source=state.source,
                    entity_type="fixture", reason="normalization_error").inc()
        metrics.records_normalized_total.labels(
            competition=state.competition, source=state.source, entity_type="fixture",
        ).inc(len(state.normalized))
        return st

    def schema_validate(self, st: dict) -> dict:
        state: RunState = st["state"]
        kept = []
        for env in state.normalized:
            errors = validate_envelope(env)
            if errors:
                state.rejected.append({"stage": "schema_validate", "reason": "; ".join(errors[:3]),
                                       "external_id": env.get("external_id")})
                metrics.records_rejected_total.labels(
                    competition=state.competition, source=state.source,
                    entity_type=env.get("entity_type", "fixture"), reason="schema_invalid").inc()
                for e in errors[:3]:
                    metrics.validation_errors_total.labels(
                        competition=state.competition, source=state.source,
                        rule=e.split(":")[0]).inc()
            else:
                kept.append(env)
        state.normalized = kept
        return st

    def deduplicate(self, st: dict) -> dict:
        state: RunState = st["state"]
        total = len(state.normalized)
        unique, removed = deduplicate(state.normalized)
        state.normalized = unique
        state.stats["duplicates_removed"] = removed
        state.stats["duplication_ratio"] = round(duplication_ratio(total, removed), 4)
        return st

    def resolve_entities(self, st: dict) -> dict:
        """Club-name resolution, for the records that name clubs.

        Only FIXTURES carry `home_team`/`away_team`. A stats payload is
        `{external_fixture_id, home, away}` where home/away are counter
        objects, and an odds payload names a bookmaker and no club at all.

        This used to index `p["home_team"]` unconditionally. It was correct
        while fixtures were the only thing any adapter could produce, and it
        raised KeyError the moment one produced anything else — killing the
        worker thread mid-execution, after the raw layer had already been
        written. See the note on `_run_worker` about why that looked like a
        job running for eleven hours.
        """
        state: RunState = st["state"]
        for env in state.normalized:
            p = env["payload"]
            home, away = p.get("home_team"), p.get("away_team")
            if not isinstance(home, dict) or not isinstance(away, dict):
                # Not a club-bearing record. Nothing to resolve, and nothing
                # is wrong: entity resolution simply does not apply.
                continue
            unresolved = [t.get("name") for t in (home, away)
                          if isinstance(t, dict) and not t.get("club_id") and t.get("name")]
            if unresolved:
                finding = self._ai(
                    "entity_resolver",
                    f"Map these club names to a canonical id: {unresolved}",
                    {"names": unresolved}, state)
                env["_ai_entity_candidates"] = finding
                env["_needs_entity_review"] = True
                self.tickets.open(
                    error_type="entity_unresolved", source=state.source,
                    competition=state.competition, season=state.season,
                    entity_type=env.get("entity_type", "fixture"),
                    severity="medium", sample_payload={"unresolved": unresolved})
        return st

    def consistency_check(self, st: dict) -> dict:
        state: RunState = st["state"]
        kept = []
        for env in state.normalized:
            violations = consistency_check(env)
            hard = [v for v in violations if v in _HARD_REJECT]
            if hard:
                state.rejected.append({"stage": "consistency", "reason": ", ".join(hard),
                                       "external_id": env.get("external_id")})
                metrics.records_rejected_total.labels(
                    competition=state.competition, source=state.source,
                    entity_type=env.get("entity_type", "fixture"),
                    reason="inconsistent").inc()
                continue
            if violations:  # soft → ambiguous → Match Validator + human review
                env["_ai_match_review"] = self._ai(
                    "match_validator", f"Borderline record, violations={violations}. Advise.",
                    {"payload": env["payload"]}, state)
                env["_consistency_warnings"] = violations
            kept.append(env)
        state.normalized = kept
        return st

    def quality_score(self, st: dict) -> dict:
        state: RunState = st["state"]
        for env in state.normalized:
            sc, breakdown = quality_score(env)
            env["_quality_score"] = sc
            env["_quality_breakdown"] = breakdown
        return st

    def approve(self, st: dict) -> dict:
        state: RunState = st["state"]
        for env in state.normalized:
            below = env.get("_quality_score", 0.0) < QUALITY_APPROVE_THRESHOLD
            if env.get("_needs_entity_review") or env.get("_consistency_warnings") or below:
                reason = ("low_quality" if below else
                          "entity_unresolved" if env.get("_needs_entity_review") else
                          "consistency_warning")
                state.review.append({"stage": "approve", "reason": reason,
                                     "quality": env.get("_quality_score"), "envelope": env})
            else:
                state.validated.append(env)
                metrics.records_validated_total.labels(
                    competition=state.competition, source=state.source, entity_type="fixture").inc()
        # Dataset Auditor: advisory narrative over the validated batch.
        state.stats["dataset_auditor"] = bool(self._ai(
            "dataset_auditor",
            f"Audit {len(state.validated)} validated / {len(state.review)} in-review / "
            f"{len(state.rejected)} rejected records for {state.competition} {state.season}.",
            {"validated": len(state.validated), "review": len(state.review),
             "rejected": len(state.rejected)}, state))
        return st

    # --- run -------------------------------------------------------------

    def steps(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in graphmod.NODE_SEQUENCE}

    def run(self, artifacts: list[RawArtifact], competition: str, season: str, source: str) -> RunState:
        import time as _time
        import uuid as _uuid

        state = RunState(competition=competition, season=season, source=source, artifacts=artifacts)
        st = {"state": state}
        run_id = str(_uuid.uuid4())
        t0 = _time.monotonic()
        app = graphmod.build_graph(self.steps())
        if app is not None:  # real LangGraph execution (GPU host)
            app.invoke(st)
        else:  # identical node order, sequential (no langgraph installed)
            for name in graphmod.NODE_SEQUENCE:
                st = self.steps()[name](st)
        state.stats["ai_backend"] = self.crew.backend
        state.stats["ai_used"] = self.ai_available and self.use_ai
        state.stats["graph_engine"] = "langgraph" if app is not None else "sequential"
        self.telemetry.graph_run(
            run_id=run_id, competition=competition, season=season, source=source,
            engine=state.stats["graph_engine"], nodes=list(graphmod.NODE_SEQUENCE),
            validated=len(state.validated), rejected=len(state.rejected),
            review=len(state.review), duration_s=_time.monotonic() - t0,
            outcome="completed")
        return state
