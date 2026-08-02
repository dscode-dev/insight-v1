import pytest

from explorer.tickets.tickets import TicketStore


def test_open_and_dedup_increments_occurrences(tmp_path):
    store = TicketStore(tmp_path)
    t1 = store.open(error_type="source_offline", source="espn",
                    competition="brasileirao_serie_a", season="2022", entity_type="fixture")
    t2 = store.open(error_type="source_offline", source="espn",
                    competition="brasileirao_serie_a", season="2022", entity_type="fixture")
    assert t1.ticket_id == t2.ticket_id
    assert t2.occurrences == 2
    assert len(store.all()) == 1


def test_distinct_keys_are_distinct_tickets(tmp_path):
    store = TicketStore(tmp_path)
    store.open(error_type="source_offline", source="espn", competition="brasileirao_serie_a",
               season="2022", entity_type="fixture")
    store.open(error_type="ai_runtime_unavailable", source="espn",
               competition="brasileirao_serie_a", season="2022", entity_type="fixture")
    assert len(store.all()) == 2


def test_unknown_error_type_rejected(tmp_path):
    store = TicketStore(tmp_path)
    with pytest.raises(ValueError):
        store.open(error_type="not_a_real_type", source="espn",
                   competition="x", season="2022", entity_type="fixture")


def test_flush_persists_jsonl(tmp_path):
    store = TicketStore(tmp_path)
    store.open(error_type="source_offline", source="espn", competition="x",
               season="2022", entity_type="fixture")
    path = store.flush()
    assert path is not None and path.exists()
