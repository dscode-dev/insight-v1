"""Live Qwen runtime visibility (ML-B.6 Part 7).

Pulls real numbers from the Ollama runtime (`/api/ps`, `/api/tags`) and, when
GPU access is available in the container, from NVML (pynvml) for utilization /
VRAM / temperature. No screenshots, no static values — every field is queried
live and absence is reported honestly.
"""

from __future__ import annotations

from typing import Any

from explorer.config import OLLAMA_HOST, QWEN_MODEL


def _ollama(path: str) -> dict[str, Any] | None:
    try:
        import requests

        r = requests.get(f"{OLLAMA_HOST.rstrip('/')}{path}", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:  # noqa: BLE001
        return None


def _gpu() -> dict[str, Any]:
    try:
        import pynvml

        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(h)
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        util = pynvml.nvmlDeviceGetUtilizationRates(h)
        temp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
        out = {
            "available": True,
            "name": name.decode() if isinstance(name, bytes) else name,
            "vram_total_mb": round(mem.total / 1e6),
            "vram_used_mb": round(mem.used / 1e6),
            "utilization_pct": util.gpu,
            "temperature_c": temp,
        }
        pynvml.nvmlShutdown()
        return out
    except Exception as exc:  # noqa: BLE001 - no GPU access in container → honest
        return {"available": False, "reason": str(exc)[:120]}


def runtime() -> dict[str, Any]:
    tags = _ollama("/api/tags") or {}
    ps = _ollama("/api/ps") or {}
    models = [m.get("name") for m in tags.get("models", [])]
    loaded = [
        {"name": m.get("name"), "vram_mb": round(m.get("size_vram", 0) / 1e6),
         "expires_at": m.get("expires_at")}
        for m in ps.get("models", [])
    ]
    return {
        "provider": "ollama",
        "host": OLLAMA_HOST,
        "configured_model": QWEN_MODEL,
        "reachable": bool(_ollama("/api/tags") is not None),
        "models_installed": models,
        "models_loaded": loaded,
        "gpu": _gpu(),
    }
