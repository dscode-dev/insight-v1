from __future__ import annotations

from redis.asyncio import Redis

from atlas.streaming.envelope import EventEnvelope
from atlas.streaming.jsonx import dumps
from atlas.streaming.streams import StreamPartitioning


class DerivedPublisher:
    """
    Publica eventos derivados no stream derived:pN.
    """

    def __init__(
        self,
        redis_client: Redis,
        *,
        partitioning: StreamPartitioning,
        max_payload_bytes: int,
        stream_maxlen_approx: int,
    ):
        self._r = redis_client
        self._streams = partitioning
        self._max_payload_bytes = max_payload_bytes
        self._maxlen = int(stream_maxlen_approx)

    async def publish(self, envelope: EventEnvelope) -> str:
        payload_bytes = dumps(envelope.payload)
        if len(payload_bytes) > self._max_payload_bytes:
            raise ValueError(f"payload_too_large bytes={len(payload_bytes)} max={self._max_payload_bytes}")

        stream_key = self._streams.key_for_match(envelope.match_id)
        fields = envelope.to_redis_dict()

        msg_id = await self._r.xadd(
            name=stream_key,
            fields=fields,
            maxlen=self._maxlen,
            approximate=True,
        )

        return msg_id.decode() if isinstance(msg_id, (bytes, bytearray)) else str(msg_id)
