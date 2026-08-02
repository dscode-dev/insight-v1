import base64
import io
import json

import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from atlas.datasets.service import _parse_request, _validation


def payload(records, category="fixtures", filename="sample.json"):
    return {
        "filename": filename,
        "format": filename.rsplit(".", 1)[-1],
        "category": category,
        "content_base64": base64.b64encode(json.dumps(records).encode()).decode(),
    }


def test_manual_fixture_dataset_validation_is_deterministic():
    body = payload([{
        "competition": "premier_league",
        "home_team": "arsenal",
        "away_team": "liverpool",
        "scheduled_at": "2026-06-25T20:00:00Z",
        "source": "customer",
    }])
    first = _validation(_parse_request(body))
    second = _validation(_parse_request(body))
    assert first["status"] == "valid"
    assert first["valid_rows"] == 1
    assert first["checksum"] == second["checksum"]
    assert first["optional_fields"] == ["source"]


def test_dataset_validation_reports_invalid_rows():
    result = _validation(_parse_request(payload([{"competition": "x"}])))
    assert result["status"] == "invalid"
    assert result["invalid_rows"] == 1
    assert "missing:home_team" in result["invalid"][0]["errors"]


def test_dataset_rejects_unsupported_category():
    with pytest.raises(ValueError, match="unsupported_dataset_request"):
        _parse_request(payload([], category="predictions"))


@pytest.mark.parametrize("fmt", ["csv", "ndjson", "parquet"])
def test_supported_formats_are_parsed(fmt):
    record = {
        "competition": "premier_league",
        "home_team": "arsenal",
        "away_team": "liverpool",
        "scheduled_at": "2026-06-25T20:00:00Z",
    }
    if fmt == "csv":
        content = (
            "competition,home_team,away_team,scheduled_at\n"
            "premier_league,arsenal,liverpool,2026-06-25T20:00:00Z\n"
        ).encode()
    elif fmt == "ndjson":
        content = (json.dumps(record) + "\n").encode()
    else:
        buffer = io.BytesIO()
        pq.write_table(pa.Table.from_pylist([record]), buffer)
        content = buffer.getvalue()
    body = {
        "filename": f"sample.{fmt}",
        "format": fmt,
        "category": "fixtures",
        "content_base64": base64.b64encode(content).decode(),
    }
    result = _validation(_parse_request(body))
    assert result["status"] == "valid"
    assert result["valid_rows"] == 1
