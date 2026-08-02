from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


from atlas.emitters import ContextEmitter
from atlas.inference.output import ContextOutput, MatchContextResponse


class StubPublisher:
    def __init__(self) -> None:
        self.published: list = []

    async def publish(self, envelope):
        self.published.append(envelope)
        return "1-0"


async def test_emit_skips_empty_response() -> None:
    pub = StubPublisher()
    emitter = ContextEmitter(publisher=pub, region_code="GLOBAL")
    response = MatchContextResponse(
        match_id=uuid4(), feature_schema_version=1
    )
    out = await emitter.emit(response)
    assert out is None
    assert pub.published == []


async def test_emit_publishes_envelope_with_correct_event_type() -> None:
    pub = StubPublisher()
    emitter = ContextEmitter(publisher=pub, region_code="GLOBAL")
    match_id = uuid4()
    response = MatchContextResponse(
        match_id=match_id,
        feature_schema_version=1,
        classifier=ContextOutput(
            match_id=match_id,
            family="classifier",
            context_confidence=0.7,
            headline="x",
            feature_schema_version=1,
            generated_at=datetime.now(timezone.utc),
        ),
    )
    msg_id = await emitter.emit(response)
    assert msg_id == "1-0"
    assert len(pub.published) == 1
    env = pub.published[0]
    assert env.event_type == "ML_CONTEXT"
    assert str(env.match_id) == str(match_id)
    # Payload carries one populated family and nulls for the others.
    assert env.payload["classifier"] is not None
    assert env.payload["anomaly"] is None
