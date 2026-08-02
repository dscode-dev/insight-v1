"""JSON Schema validation against the ML-A contracts (Step 9).

Uses jsonschema 4.17 RefResolver with a store keyed by both $id and
filename so the cross-file $ref in explorer.match.v1.json resolves offline.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, RefResolver

_CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"


@lru_cache(maxsize=1)
def _store() -> dict[str, Any]:
    store: dict[str, Any] = {}
    for path in _CONTRACTS.glob("*.json"):
        schema = json.loads(path.read_text("utf-8"))
        if "$id" in schema:
            store[schema["$id"]] = schema
        store[path.name] = schema
    return store


@lru_cache(maxsize=1)
def _envelope_validator() -> Draft202012Validator:
    store = _store()
    envelope = store["explorer.envelope.v1.json"]
    resolver = RefResolver(base_uri=envelope.get("$id", ""), referrer=envelope, store=store)
    return Draft202012Validator(envelope, resolver=resolver)


@lru_cache(maxsize=8)
def _payload_validator(entity_type: str) -> Draft202012Validator:
    store = _store()
    schema = store[f"explorer.{entity_type}.v1.json"]
    resolver = RefResolver(base_uri=schema.get("$id", ""), referrer=schema, store=store)
    return Draft202012Validator(schema, resolver=resolver)


def validate_envelope(envelope: dict[str, Any]) -> list[str]:
    """Return a list of human-readable violations ([] == valid). Validates
    both the envelope and the entity payload against its schema."""
    errors: list[str] = []
    for err in sorted(_envelope_validator().iter_errors(envelope), key=str):
        errors.append(f"envelope: {err.message}")
    entity_type = envelope.get("entity_type")
    payload = envelope.get("payload")
    entity_types = {"fixture", "match", "event", "stats", "lineup", "injury", "odds_snapshot"}
    if entity_type in entity_types and isinstance(payload, dict):
        try:
            for err in sorted(_payload_validator(entity_type).iter_errors(payload), key=str):
                errors.append(f"payload[{entity_type}]: {err.message}")
        except KeyError:
            errors.append(f"payload[{entity_type}]: no schema for entity_type")
    return errors
