from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NAMESPACE = UUID("176ca682-b8e3-4fa1-a185-cae663e7b95c")
CATEGORIES = {
    "fixtures": ("competition", "home_team", "away_team", "scheduled_at"),
    "statistics": ("competition", "team", "observed_at"),
    "odds": ("competition", "home_team", "away_team", "observed_at", "home", "draw", "away"),
    "behaviors": ("competition", "behavior", "observed_at"),
    "memory": ("competition", "home_team", "away_team", "observed_at"),
    "signals": ("competition", "signal_family", "observed_at"),
}
FORMATS = {"csv", "json", "ndjson", "parquet"}


class AtlasDatasetService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], root: Path) -> None:
        self._sf = session_factory
        self.root = root / "registered"
        self.root.mkdir(parents=True, exist_ok=True)

    async def validate(self, body: dict[str, Any]) -> dict[str, Any]:
        parsed = _parse_request(body)
        return _validation(parsed)

    async def register(self, body: dict[str, Any], actor: str) -> dict[str, Any]:
        parsed = _parse_request(body)
        validation = _validation(parsed)
        if validation["invalid_rows"]:
            raise ValueError("dataset_contains_invalid_rows")
        checksum = validation["checksum"]
        dataset_id = uuid5(NAMESPACE, checksum)
        target = self.root / str(dataset_id)
        target.mkdir(parents=True, exist_ok=True)
        original = target / parsed["filename"]
        if not original.exists():
            original.write_bytes(parsed["content"])
        canonical = target / "records.ndjson"
        canonical.write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in parsed["rows"]),
            "utf-8",
        )
        now = datetime.now(timezone.utc).isoformat()
        lineage = {
            "source_type": body.get("source_type", "manual"),
            "source_reference": body.get("source_reference"),
            "registered_by": actor,
            "registered_at": now,
            "original_filename": parsed["filename"],
        }
        manifest = {
            "dataset_id": str(dataset_id),
            "name": body.get("name") or parsed["filename"],
            "category": parsed["category"],
            "format": parsed["format"],
            "checksum": checksum,
            "rows": len(parsed["rows"]),
            "valid_rows": validation["valid_rows"],
            "invalid_rows": validation["invalid_rows"],
            "required_fields": validation["required_fields"],
            "optional_fields": validation["optional_fields"],
            "files": {
                "original": str(original),
                "canonical": str(canonical),
            },
            "lineage": lineage,
        }
        (target / "manifest.json").write_text(json.dumps(manifest, indent=2), "utf-8")
        async with self._sf() as session:
            await session.execute(text("""
                INSERT INTO atlas.dataset_registry (
                    dataset_id, name, category, format, source_type,
                    source_reference, checksum, status, row_count, valid_rows,
                    invalid_rows, manifest, lineage, storage_path, registered_by
                ) VALUES (
                    :dataset_id, :name, :category, :format, :source_type,
                    :source_reference, :checksum, 'registered', :rows, :valid_rows,
                    :invalid_rows, CAST(:manifest AS jsonb), CAST(:lineage AS jsonb),
                    :storage_path, :actor
                ) ON CONFLICT (checksum) DO NOTHING
            """), {
                "dataset_id": dataset_id, "name": manifest["name"],
                "category": parsed["category"], "format": parsed["format"],
                "source_type": lineage["source_type"],
                "source_reference": lineage["source_reference"],
                "checksum": checksum, "rows": len(parsed["rows"]),
                "valid_rows": validation["valid_rows"],
                "invalid_rows": validation["invalid_rows"],
                "manifest": json.dumps(manifest), "lineage": json.dumps(lineage),
                "storage_path": str(target), "actor": actor,
            })
            for index, row in enumerate(parsed["rows"], 1):
                await session.execute(text("""
                    INSERT INTO atlas.dataset_records (
                        dataset_id, row_number, category, record, valid, errors
                    ) VALUES (
                        :dataset_id, :row_number, :category, CAST(:record AS jsonb),
                        true, '[]'::jsonb
                    ) ON CONFLICT DO NOTHING
                """), {
                    "dataset_id": dataset_id, "row_number": index,
                    "category": parsed["category"], "record": json.dumps(row),
                })
            await session.commit()
        return manifest | {"status": "registered"}

    async def register_explorer(self, body: dict[str, Any], actor: str) -> dict[str, Any]:
        generation_id = str(body["generation_id"])
        manifest = body.get("manifest") or {}
        record = {
            "competition": "manifest",
            "home_team": "not_applicable",
            "away_team": "not_applicable",
            "scheduled_at": body.get("completed_at") or datetime.now(timezone.utc).isoformat(),
            "generation_id": generation_id,
            "generation_manifest": manifest,
        }
        content = json.dumps([record], sort_keys=True, separators=(",", ":")).encode()
        payload = {
            "name": body.get("name") or generation_id,
            "filename": f"{generation_id}.json",
            "format": "json",
            "category": "fixtures",
            "content_base64": base64.b64encode(content).decode(),
            "source_type": "explorer",
            "source_reference": generation_id,
        }
        return await self.register(payload, actor)

    async def list(self, category: str | None, limit: int, offset: int) -> dict[str, Any]:
        where = "WHERE category = :category" if category else ""
        params = {"category": category, "limit": limit, "offset": offset}
        async with self._sf() as session:
            result = (await session.execute(text(f"""
                SELECT dataset_id, name, category, format, source_type,
                       source_reference, checksum, status, row_count, valid_rows,
                       invalid_rows, manifest, lineage, registered_by, registered_at
                FROM atlas.dataset_registry {where}
                ORDER BY registered_at DESC LIMIT :limit OFFSET :offset
            """), params)).mappings().all()
            total = (await session.execute(text(
                f"SELECT count(*) FROM atlas.dataset_registry {where}"
            ), params)).scalar_one()
        return {"items": [dict(row) for row in result], "total": total, "limit": limit, "offset": offset}

    async def records(self, dataset_id: UUID, valid: bool | None, limit: int, offset: int) -> dict[str, Any]:
        where = "AND valid = :valid" if valid is not None else ""
        params = {"dataset_id": dataset_id, "valid": valid, "limit": limit, "offset": offset}
        async with self._sf() as session:
            result = (await session.execute(text(f"""
                SELECT row_number, category, record, valid, errors
                FROM atlas.dataset_records WHERE dataset_id = :dataset_id {where}
                ORDER BY row_number LIMIT :limit OFFSET :offset
            """), params)).mappings().all()
            total = (await session.execute(text(f"""
                SELECT count(*) FROM atlas.dataset_records
                WHERE dataset_id = :dataset_id {where}
            """), params)).scalar_one()
        return {"items": [dict(row) for row in result], "total": total, "limit": limit, "offset": offset}


def _parse_request(body: dict[str, Any], rows_override: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    filename = Path(str(body.get("filename", ""))).name
    category = str(body.get("category", ""))
    fmt = str(body.get("format") or filename.rsplit(".", 1)[-1]).lower()
    if not filename or fmt not in FORMATS or category not in CATEGORIES:
        raise ValueError("unsupported_dataset_request")
    try:
        content = base64.b64decode(body["content_base64"], validate=True)
    except Exception as exc:
        raise ValueError("invalid_base64_content") from exc
    if len(content) > 25 * 1024 * 1024:
        raise ValueError("dataset_exceeds_25mb")
    rows = rows_override if rows_override is not None else _rows(content, fmt)
    return {"filename": filename, "format": fmt, "category": category, "content": content, "rows": rows}


def _rows(content: bytes, fmt: str) -> list[dict[str, Any]]:
    if fmt == "csv":
        return [dict(row) for row in csv.DictReader(io.StringIO(content.decode("utf-8-sig")))]
    if fmt == "ndjson":
        return [json.loads(line) for line in content.decode().splitlines() if line.strip()]
    if fmt == "json":
        body = json.loads(content)
        if isinstance(body, dict):
            body = body.get("records", [body])
        if not isinstance(body, list):
            raise ValueError("json_records_must_be_array")
        return body
    if fmt == "parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise ValueError("parquet_support_unavailable") from exc
        return pq.read_table(io.BytesIO(content)).to_pylist()
    raise ValueError("unsupported_file_type")


def _validation(parsed: dict[str, Any]) -> dict[str, Any]:
    required = CATEGORIES[parsed["category"]]
    invalid = []
    fields: set[str] = set()
    for index, row in enumerate(parsed["rows"], 1):
        if not isinstance(row, dict):
            invalid.append({"row": index, "errors": ["row_must_be_object"]})
            continue
        fields.update(row)
        missing = [field for field in required if row.get(field) in (None, "")]
        if missing:
            invalid.append({"row": index, "errors": [f"missing:{field}" for field in missing]})
    checksum = "sha256:" + hashlib.sha256(parsed["content"]).hexdigest()
    return {
        "filename": parsed["filename"], "format": parsed["format"],
        "category": parsed["category"], "checksum": checksum,
        "rows": len(parsed["rows"]), "valid_rows": len(parsed["rows"]) - len(invalid),
        "invalid_rows": len(invalid), "invalid": invalid[:100],
        "required_fields": list(required),
        "optional_fields": sorted(fields - set(required)),
        "supported_categories": sorted(CATEGORIES),
        "preview": parsed["rows"][:10],
        "status": "valid" if not invalid else "invalid",
    }
