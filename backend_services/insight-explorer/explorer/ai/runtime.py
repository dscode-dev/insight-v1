"""Local AI runtime — Ollama + Qwen ONLY (Step 8).

Hard rules from the sprint:
- No cloud LLMs. No fallback providers. The single model is local Qwen.
- If the AI runtime is unavailable, the job does NOT silently continue as if
  AI ran: it raises AIRuntimeUnavailable, the pipeline records an
  `ai_runtime_unavailable` ticket + ai_failures metric, and falls back to the
  deterministic path (collection still completes, never silently dropping
  data). This satisfies "if AI runtime fails → job degrades + ticket".

The `ollama` python client is used when installed; otherwise we talk to the
Ollama HTTP API directly via requests so the runtime works on the GPU host
regardless of which is present.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from explorer.config import AI_REQUEST_TIMEOUT_S, OLLAMA_HOST, QWEN_MODEL


class AIRuntimeUnavailable(RuntimeError):
    """Local Qwen/Ollama is unreachable or the model is not present."""


@dataclass
class AIResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float


class OllamaRuntime:
    def __init__(self, host: str = OLLAMA_HOST, model: str = QWEN_MODEL) -> None:
        self.host = host.rstrip("/")
        self.model = model

    # --- health ----------------------------------------------------------

    def health(self) -> bool:
        """True only if Ollama answers AND the Qwen model is pulled."""
        try:
            tags = self._get("/api/tags")
        except AIRuntimeUnavailable:
            return False
        models = {m.get("name", "").split(":")[0] for m in tags.get("models", [])}
        return self.model.split(":")[0] in models

    # --- generation ------------------------------------------------------

    def generate(self, prompt: str, system: str | None = None) -> AIResult:
        body: dict[str, Any] = {"model": self.model, "prompt": prompt, "stream": False}
        if system:
            body["system"] = system
        started = time.monotonic()
        data = self._post("/api/generate", body)
        latency = time.monotonic() - started
        return AIResult(
            text=data.get("response", ""),
            prompt_tokens=int(data.get("prompt_eval_count", 0)),
            completion_tokens=int(data.get("eval_count", 0)),
            latency_s=latency,
        )

    # --- transport (ollama client if present, else HTTP) -----------------

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            import requests
        except ImportError as exc:  # pragma: no cover
            raise AIRuntimeUnavailable("requests not installed") from exc
        try:
            resp = requests.post(f"{self.host}{path}", json=body, timeout=AI_REQUEST_TIMEOUT_S)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - any failure means runtime down
            raise AIRuntimeUnavailable(f"Ollama POST {path} failed: {exc}") from exc

    def _get(self, path: str) -> dict[str, Any]:
        try:
            import requests
        except ImportError as exc:  # pragma: no cover
            raise AIRuntimeUnavailable("requests not installed") from exc
        try:
            resp = requests.get(f"{self.host}{path}", timeout=AI_REQUEST_TIMEOUT_S)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise AIRuntimeUnavailable(f"Ollama GET {path} failed: {exc}") from exc
