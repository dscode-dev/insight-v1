from explorer.datalake.lake import DataLake, checksum


def test_checksum_is_stable_and_order_independent():
    assert checksum({"a": 1, "b": 2}) == checksum({"b": 2, "a": 1})
    assert checksum({"a": 1}) != checksum({"a": 2})


def test_append_and_read_roundtrip(tmp_path):
    lake = DataLake(tmp_path)
    recs = [{"external_id": "x1", "v": 1}, {"external_id": "x2", "v": 2}]
    res = lake.append("validated", "brasileirao_serie_a", "2022", "espn", "fixture", recs)
    assert res == {"written": 2, "skipped": 0}
    read = list(lake.read("validated", "brasileirao_serie_a", "2022", "espn", "fixture"))
    assert len(read) == 2
    assert all("_checksum" in r for r in read)


def test_append_is_replay_safe(tmp_path):
    lake = DataLake(tmp_path)
    recs = [{"external_id": "x1", "v": 1}]
    lake.append("raw", "brasileirao_serie_a", "2022", "espn", "fixture", recs)
    res = lake.append("raw", "brasileirao_serie_a", "2022", "espn", "fixture", recs)
    assert res == {"written": 0, "skipped": 1}  # idempotent re-run
    assert len(list(lake.read("raw", "brasileirao_serie_a", "2022", "espn", "fixture"))) == 1


def test_partition_layout(tmp_path):
    lake = DataLake(tmp_path)
    p = lake.partition("validated", "brasileirao_serie_a", "2022", "espn", "fixture")
    assert p == tmp_path / "validated" / "brasileirao_serie_a" / "2022" / "espn" / "fixture"


def test_rejected_report_lines(tmp_path):
    lake = DataLake(tmp_path)
    path = lake.append_report_lines("rejected", "brasileirao_serie_a", "2022", "espn", "j1.jsonl",
                                    records=[{"reason": "schema_invalid"}])
    assert path.exists()
    assert lake.layer_size_bytes("reports") > 0
