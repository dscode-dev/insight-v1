"""Streaming subsystem — Sprint 5.1.

Atlas consumes canonical events emitted by the Sports Data Hub on
the Redis Stream `insight:stream:events:{match,context}`. The
consumer here is the ONLY place Atlas reads upstream data — no
direct provider HTTP and no Sports Hub HTTP/gRPC path.
"""

from atlas.streaming.canonical_consumer import (  # noqa: F401
    CanonicalConsumer,
    CanonicalEnvelope,
    ConsumerConfig,
    MalformedEnvelopeError,
    ProcessedEventStore,
    UnsupportedSchemaError,
)
