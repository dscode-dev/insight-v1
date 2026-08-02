#!/usr/bin/env python3
"""ML-A schema validation — Sprint requirement: 'Executar somente
validações de schema se aplicável.'

1. Every explorer.*.v1.json is a valid JSON Schema (Draft 2020-12).
2. Each example envelope validates against explorer.envelope.v1, and
   its payload validates against explorer.<entity>.v1.
Cross-file $refs resolve through a local store (offline; no network).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, RefResolver

HERE = Path(__file__).resolve().parent
schemas = {p.name: json.loads(p.read_text()) for p in HERE.glob("explorer.*.json")}

# Store maps both $id and bare filename (examples $ref by filename).
store = {}
for name, doc in schemas.items():
    store[doc["$id"]] = doc
    store[name] = doc


def validator_for(doc):
    resolver = RefResolver(base_uri=doc["$id"], referrer=doc, store=store)
    return Draft202012Validator(doc, resolver=resolver)


ok = True
for name, doc in sorted(schemas.items()):
    try:
        Draft202012Validator.check_schema(doc)
        print(f"schema OK   {name}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"schema FAIL {name}: {e}")

env_validator = validator_for(schemas["explorer.envelope.v1.json"])
for ex in sorted((HERE / "examples").glob("*.json")):
    inst = json.loads(ex.read_text())
    errs = sorted(env_validator.iter_errors(inst), key=str)
    if errs:
        ok = False
        print(f"example FAIL {ex.name}: {errs[0].message}")
        continue
    et = inst["entity_type"]
    pv = validator_for(schemas[f"explorer.{et}.v1.json"])
    perrs = sorted(pv.iter_errors(inst["payload"]), key=str)
    if perrs:
        ok = False
        print(f"payload FAIL {ex.name} ({et}): {perrs[0].message}")
    else:
        print(f"example OK   {ex.name} (envelope + {et} payload)")

print("\nALL SCHEMAS + EXAMPLES VALID" if ok else "\nVALIDATION FAILED")
sys.exit(0 if ok else 1)
