"""CrewAI agents for the quality layer (Step 7).

Five agents — Source Analyst, Entity Resolver, Match Validator, Data
Enricher, Dataset Auditor — each with a role/goal/backstory and the local
Qwen runtime as its LLM. **Agents never write to validated/ directly**: they
return advisory findings that the LangGraph approval node consumes. The
deterministic validators remain the source of truth; agents add reasoning on
ambiguous cases and a dataset-level narrative.

CrewAI is an optional dependency. When it is not installed the same agent
*roster* is exercised through the raw Qwen runtime (`OllamaRuntime`), so the
multi-agent logic runs identically on the GPU host with or without the
crewai package — and degrades to deterministic-only when Qwen is absent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from explorer.ai.runtime import AIResult, AIRuntimeUnavailable, OllamaRuntime


@dataclass(frozen=True)
class AgentSpec:
    name: str
    role: str
    goal: str
    backstory: str


AGENTS: dict[str, AgentSpec] = {
    "source_analyst": AgentSpec(
        "source_analyst",
        "Source Analyst",
        "Judge whether a batch of raw source artifacts looks healthy or shows "
        "layout drift / missing fields, and flag anomalies.",
        "A veteran data engineer who has seen every way a sports feed breaks.",
    ),
    "entity_resolver": AgentSpec(
        "entity_resolver",
        "Entity Resolver",
        "Map ambiguous club name variants (e.g. 'Man City') to a canonical "
        "Club Registry id. Propose candidates ONLY for names the deterministic "
        "resolver could not match; never override a registry hit.",
        "A football historian fluent in club naming across leagues and eras.",
    ),
    "match_validator": AgentSpec(
        "match_validator",
        "Match Validator",
        "Inspect borderline records (odd scores, status/score mismatch) and "
        "advise approve / review / reject with a reason.",
        "A meticulous match-data referee who trusts evidence over vibes.",
    ),
    "data_enricher": AgentSpec(
        "data_enricher",
        "Data Enricher",
        "Suggest normalized values for missing OPTIONAL fields (short names, "
        "venue) without ever fabricating scores or results.",
        "A careful archivist who annotates gaps but never invents facts.",
    ),
    "dataset_auditor": AgentSpec(
        "dataset_auditor",
        "Dataset Auditor",
        "Summarize the validated dataset's coverage, gaps and quality, and "
        "recommend whether it is fit for training.",
        "A QA lead who signs off datasets and owns the consequences.",
    ),
}


class Crew:
    """Runs an agent via local Qwen. Uses crewai's Agent/Task wiring when the
    package is installed; otherwise calls the Qwen runtime directly with the
    agent's role/goal as the system prompt. Either way the LLM is local Qwen.
    """

    def __init__(self, runtime: OllamaRuntime | None = None, force_backend: str | None = None) -> None:
        self.runtime = runtime or OllamaRuntime()
        self._crewai = None if force_backend == "qwen-direct" else _maybe_import_crewai()
        self._agents: dict[str, Any] = {}
        self._last_backend = "qwen-direct"

    @property
    def backend(self) -> str:
        """The backend that actually executed the most recent call (or would)."""
        return self._last_backend if self._agents else ("crewai" if self._crewai else "qwen-direct")

    def ask(self, agent: str, task: str, context: dict[str, Any] | None = None) -> AIResult:
        """Execute one agent task on local Qwen. Raises AIRuntimeUnavailable
        if Qwen is unreachable (caller degrades + tickets)."""
        spec = AGENTS[agent]
        prompt = task if not context else f"{task}\n\nCONTEXT:\n{json.dumps(context, default=str)[:3000]}"
        if self._crewai is not None:
            try:
                res = self._kickoff_crewai(spec, prompt)
                self._last_backend = "crewai"
                return res
            except AIRuntimeUnavailable:
                raise
            except Exception:  # noqa: BLE001 - crewai/litellm hiccup → degrade to direct Qwen
                pass
        system = (f"You are the {spec.role}. Goal: {spec.goal}\nBackstory: {spec.backstory}\n"
                  "Answer strictly as compact JSON.")
        self._last_backend = "qwen-direct"
        return self.runtime.generate(prompt, system=system)

    def _kickoff_crewai(self, spec: AgentSpec, prompt: str) -> AIResult:
        """Build a real CrewAI Agent+Task+Crew bound to local Qwen and kick it
        off. The LLM is `ollama/<model>` via the local Ollama host — no cloud."""
        import os
        import time

        from crewai import LLM, Agent, Crew, Task

        os.environ.setdefault("OLLAMA_API_BASE", self.runtime.host)
        llm = LLM(model=f"ollama/{self.runtime.model}", base_url=self.runtime.host)
        crew_agent = self._agents.get(spec.name)
        if crew_agent is None:
            crew_agent = Agent(role=spec.role, goal=spec.goal, backstory=spec.backstory,
                               llm=llm, allow_delegation=False, verbose=False)
            self._agents[spec.name] = crew_agent
        crew_task = Task(description=prompt, expected_output="Compact JSON with the finding.",
                         agent=crew_agent)
        crew = Crew(agents=[crew_agent], tasks=[crew_task], verbose=False)
        started = time.monotonic()
        out = crew.kickoff()
        latency = time.monotonic() - started
        text = getattr(out, "raw", None) or str(out)
        usage = getattr(out, "token_usage", None)
        pt = int(getattr(usage, "prompt_tokens", 0) or 0)
        ct = int(getattr(usage, "completion_tokens", 0) or 0)
        return AIResult(text=text, prompt_tokens=pt, completion_tokens=ct, latency_s=latency)

    def health(self) -> bool:
        return self.runtime.health()


def _maybe_import_crewai() -> Any:
    try:
        import crewai  # noqa: F401

        return crewai
    except ImportError:
        return None


__all__ = ["Crew", "AgentSpec", "AGENTS", "AIRuntimeUnavailable"]
