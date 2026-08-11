"""How a finished match gets into the Atlas.

One contract (`atlas.match.v1`), one validator, and — from step 2 — two doors
onto it: an HTTP endpoint and a CLI. The directory watcher that used to be
the only way in is going away; a job that notices a folder changed cannot say
what changed, whether it was valid, or why a line was dropped.

NOT `atlas.ingestion`. That package carries `explorer-atlas.ingest.v1`, a
different contract for Explorer's intelligence observations, whose four
tables hold zero rows. The similar name is unfortunate and predates this;
what belongs here is match data, and only match data.
"""

from atlas.intake.contract import (
    SCHEMA_VERSION,
    FieldError,
    MatchRecord,
    Verdict,
    example,
    known_clubs,
    validate,
)

__all__ = [
    "SCHEMA_VERSION",
    "FieldError",
    "MatchRecord",
    "Verdict",
    "example",
    "known_clubs",
    "validate",
]
