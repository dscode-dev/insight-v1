from _helpers import FakeCrewDown, make_artifact, make_espn_event

from explorer.ai import graph as graphmod
from explorer.ai.pipeline import QualityPipeline
from explorer.tickets.tickets import TicketStore


def test_graph_describe_node_order():
    spec = graphmod.describe()
    assert spec["nodes"][0] == "collect"
    assert spec["nodes"][-1] == "approve"
    assert "deduplicate" in spec["nodes"]
    # linear chain edges
    assert ("collect", "normalize") in spec["edges"]
    assert ("quality_score", "approve") in spec["edges"]


def test_pipeline_validates_clean_records_without_ai(tmp_path, sample_artifacts):
    store = TicketStore(tmp_path)
    pipe = QualityPipeline(store, use_ai=False)
    state = pipe.run(sample_artifacts, "brasileirao_serie_a", "2022", "espn")
    assert len(state.validated) == 2
    assert state.rejected == []
    assert state.stats["graph_engine"] in {"sequential", "langgraph"}


def test_pipeline_rejects_inconsistent_record(tmp_path):
    store = TicketStore(tmp_path)
    bad = make_artifact(make_espn_event(event_id="700", home="Flamengo", away="Flamengo"))
    pipe = QualityPipeline(store, use_ai=False)
    state = pipe.run([bad], "brasileirao_serie_a", "2022", "espn")
    assert len(state.validated) == 0
    assert any(r["stage"] == "consistency" for r in state.rejected)


def test_pipeline_degrades_with_ticket_when_qwen_down(tmp_path, sample_artifacts):
    store = TicketStore(tmp_path)
    pipe = QualityPipeline(store, crew=FakeCrewDown(), use_ai=True)
    state = pipe.run(sample_artifacts, "brasileirao_serie_a", "2022", "espn")
    # Collection still completes deterministically …
    assert len(state.validated) == 2
    # … and a single ai_runtime_unavailable ticket was opened (degrade).
    assert any(t.error_type == "ai_runtime_unavailable" for t in store.all())
    assert pipe.ai_available is False


def test_unresolved_entity_goes_to_review_not_dropped(tmp_path):
    store = TicketStore(tmp_path)
    art = make_artifact(make_espn_event(event_id="800", home="Unknown Club ABC",
                                        away="Internacional"))
    pipe = QualityPipeline(store, use_ai=False)
    state = pipe.run([art], "brasileirao_serie_a", "2022", "espn")
    assert len(state.validated) == 0
    assert len(state.review) == 1  # preserved for human review, never silently dropped
