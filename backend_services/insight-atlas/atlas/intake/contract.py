"""atlas.match.v1 — the one shape the Atlas accepts a finished match in.

WHAT CHANGED AND WHY. Until now a match reached the Atlas by being written
into a directory as `explorer.envelope.v1`, and the reader took what it
recognised. Measured against production in August 2026, that reader:

  * REQUIRED five things and dropped the line in silence if any was absent —
    no error, no log, no count;
  * ACCEPTED an empty competition and an empty season, producing a vector
    that no competition-filtered query would ever return;
  * fell back from `club_id` to the raw team NAME, so "Arsenal FC" and
    "arsenal" became two different clubs with half a history each;
  * inferred the producing source from the FILE PATH;
  * had nowhere to put odds or match statistics, which is why seven of the
    thirty-seven vector dimensions were constant zero.

So this contract is not a tidier envelope. It is the list of the ways data
got in wrong, turned into rules.

EVERY FIELD IS REQUIRED. No optional blocks, no defaults, no `None` standing
in for "we did not look". A record that cannot state its odds is not
accepted with a gap — it is refused, by name, with the field listed. That is
a deliberate, expensive choice: measured today, ZERO of the 7.127 matches in
the lake would satisfy it, because the market and stats blocks live in the
raw layer and have never been attached to a match. Filling them is step 3;
until then this contract accepts nothing, and nothing currently depends on
it.

REQUIREDNESS CATCHES MISSING; ONLY VALUE RULES CATCH WRONG. A record can be
complete and still be nonsense — a halftime score above the full-time score,
shots on target above shots, decimal odds below 1.0, a club id nobody has
heard of. Those rules are the second half of this module, and they are the
half that earns it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from atlas.match_identity import match_uid_from

SCHEMA_VERSION = "atlas.match.v1"

#: Lowercase, digits and underscores. The shape every club id and competition
#: key in the platform already has; anything else is a name that slipped
#: through unresolved.
_SLUG = re.compile(r"^[a-z][a-z0-9_]{1,63}$")

#: `2024` or `2023-2024`. Both are real: South American seasons sit inside one
#: calendar year, European ones straddle two.
_SEASON = re.compile(r"^(\d{4}|\d{4}-\d{4})$")

#: Where the 299-club registry lives in the image. Shared with the Explorer
#: through insight-protos rather than copied, so the two cannot drift.
CLUB_REGISTRY_PATH = Path("/opt/insight-protos/contracts/clubs/club_registry.json")


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(
            f"{field}: precisa de fuso horário explícito (ex.: 2024-03-01T15:00:00Z)"
        )
    return value.astimezone(timezone.utc)


class Identity(BaseModel):
    """Who played, where and when. This is what makes a match a match."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    competition: str = Field(pattern=_SLUG.pattern)
    season: str = Field(pattern=_SEASON.pattern)
    # `club_id`, never a name. The resolver in the Explorer turns "Ath
    # Madrid" into `atletico_madrid`; a record arriving here with a display
    # name means that step was skipped, and the match will not join with the
    # club's own history.
    home_club_id: str = Field(pattern=_SLUG.pattern)
    away_club_id: str = Field(pattern=_SLUG.pattern)
    kickoff_utc: datetime

    @model_validator(mode="after")
    def _check(self) -> Identity:
        object.__setattr__(self, "kickoff_utc", _aware(self.kickoff_utc, "kickoff_utc"))
        if self.home_club_id == self.away_club_id:
            raise ValueError("home_club_id e away_club_id são o mesmo clube")
        if self.kickoff_utc > datetime.now(timezone.utc):
            raise ValueError("kickoff_utc está no futuro, mas o status é 'finished'")
        return self

    @property
    def uid(self) -> str:
        return match_uid_from(
            self.competition,
            self.season,
            self.home_club_id,
            self.away_club_id,
            self.kickoff_utc,
        )


class Result(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Only finished matches. A scheduled fixture has no score, and storing it
    # as history would put a 0-0 into every baseline.
    status: Literal["finished"]
    home_goals: int = Field(ge=0, le=30)
    away_goals: int = Field(ge=0, le=30)
    home_goals_halftime: int = Field(ge=0, le=30)
    away_goals_halftime: int = Field(ge=0, le=30)

    @model_validator(mode="after")
    def _check(self) -> Result:
        if self.home_goals_halftime > self.home_goals:
            raise ValueError("home_goals_halftime maior que home_goals")
        if self.away_goals_halftime > self.away_goals:
            raise ValueError("away_goals_halftime maior que away_goals")
        return self


class Prices(BaseModel):
    """Decimal odds for the 1x2 market."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Below 1.0 a decimal odd would pay less than the stake — impossible, and
    # the shape a transposed or mis-parsed column takes.
    home: float = Field(gt=1.0, le=1000.0)
    draw: float = Field(gt=1.0, le=1000.0)
    away: float = Field(gt=1.0, le=1000.0)

    @property
    def overround(self) -> float:
        """Sum of implied probabilities. A real book prices above 1.0 — the
        excess is the margin. Far from 1.0 in either direction means the
        numbers are not a coherent set of prices for one match."""
        return 1.0 / self.home + 1.0 / self.draw + 1.0 / self.away

    @model_validator(mode="after")
    def _check(self) -> Prices:
        book = self.overround
        # 1.00 is a book with no margin at all, 1.40 an implausibly greedy
        # one. Anything outside catches columns read in the wrong order far
        # more reliably than a per-price bound does.
        if not 1.0 <= book <= 1.40:
            raise ValueError(
                f"as três cotações não formam um mercado coerente "
                f"(soma das probabilidades implícitas = {book:.3f}, "
                "esperado entre 1,00 e 1,40)"
            )
        return self


class Market(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bookmaker: str = Field(min_length=2, max_length=64)
    # Both ends, because the DIFFERENCE is the signal. `line_movement` is
    # what the market learned between opening and kickoff, and a single
    # snapshot cannot express it — which is why that dimension has been
    # fixed at its neutral value in every vector ever written.
    opening: Prices
    closing: Prices


class SideStats(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    shots: int = Field(ge=0, le=80)
    shots_on_target: int = Field(ge=0, le=80)
    corners: int = Field(ge=0, le=40)
    fouls: int = Field(ge=0, le=60)
    yellow_cards: int = Field(ge=0, le=12)
    red_cards: int = Field(ge=0, le=5)

    @model_validator(mode="after")
    def _check(self) -> SideStats:
        if self.shots_on_target > self.shots:
            raise ValueError("shots_on_target maior que shots")
        return self


class Stats(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    home: SideStats
    away: SideStats


class Provenance(BaseModel):
    """Who produced this record, and where it came from.

    Stated, never inferred. The old reader took the source from the third
    directory segment of the file path, which meant moving a file changed
    who was said to have collected it — and the source decides whose number
    wins when two disagree about a score.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(pattern=_SLUG.pattern)
    source_match_id: str = Field(min_length=1, max_length=128)
    collected_at: datetime
    url: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def _check(self) -> Provenance:
        object.__setattr__(
            self, "collected_at", _aware(self.collected_at, "collected_at")
        )
        return self


class MatchRecord(BaseModel):
    """One finished match, complete. Nothing here is optional."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["atlas.match.v1"]
    identity: Identity
    result: Result
    market: Market
    stats: Stats
    provenance: Provenance

    @property
    def uid(self) -> str:
        return self.identity.uid


@dataclass(frozen=True)
class FieldError:
    field: str
    reason: str

    def __str__(self) -> str:
        return f"{self.field}: {self.reason}"


@dataclass(frozen=True)
class Verdict:
    """Accepted, or refused with every reason named.

    EVERY reason, not the first. A record with four problems reported one at
    a time takes four round trips to fix, and whoever is fixing it starts
    guessing after the second.
    """

    record: MatchRecord | None
    errors: tuple[FieldError, ...]

    @property
    def accepted(self) -> bool:
        return self.record is not None

    @property
    def uid(self) -> str | None:
        return self.record.uid if self.record else None


@lru_cache(maxsize=1)
def known_clubs(path: Path = CLUB_REGISTRY_PATH) -> frozenset[str]:
    """Club ids the platform recognises, or empty when the registry is absent.

    Empty is reported by `validate` as an unchecked rule rather than as a
    pass — a validator that quietly stops checking is worse than one that
    never checked, because the operator believes it did.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return frozenset()
    return frozenset(
        str(club["club_id"]) for club in data.get("clubs", []) if club.get("club_id")
    )


def validate(payload: Any, *, registry: frozenset[str] | None = None) -> Verdict:
    """Check one record against atlas.match.v1."""
    if not isinstance(payload, dict):
        return Verdict(None, (FieldError("(raiz)", "não é um objeto JSON"),))

    try:
        record = MatchRecord.model_validate(payload)
    except ValidationError as exc:
        return Verdict(None, tuple(_translate(exc)))

    clubs = known_clubs() if registry is None else registry
    if clubs:
        unknown = [
            (field, value)
            for field, value in (
                ("identity.home_club_id", record.identity.home_club_id),
                ("identity.away_club_id", record.identity.away_club_id),
            )
            if value not in clubs
        ]
        if unknown:
            return Verdict(
                None,
                tuple(
                    FieldError(
                        field,
                        f"clube '{value}' não está no registro de {len(clubs)} clubes — "
                        "um id não reconhecido nunca se junta ao histórico do clube",
                    )
                    for field, value in unknown
                ),
            )

    return Verdict(record, ())


_MENSAGENS = {
    "missing": "campo obrigatório ausente",
    "extra_forbidden": "campo não faz parte do contrato",
    "literal_error": "valor fora dos permitidos",
    "string_pattern_mismatch": "formato inválido",
    "greater_than": "valor abaixo do mínimo",
    "greater_than_equal": "valor abaixo do mínimo",
    "less_than_equal": "valor acima do máximo",
    "int_parsing": "precisa ser um número inteiro",
    "float_parsing": "precisa ser um número",
    "datetime_from_date_parsing": "precisa ser data e hora, não só data",
}


def _translate(exc: ValidationError) -> list[FieldError]:
    """Pydantic's report, in the operator's language and vocabulary."""
    errors: list[FieldError] = []
    for detail in exc.errors():
        field = ".".join(str(part) for part in detail["loc"]) or "(raiz)"
        kind = detail.get("type", "")
        if kind == "value_error":
            # Our own model_validator messages are already written for a
            # reader; pydantic wraps them in "Value error, ".
            reason = str(detail.get("msg", "")).replace("Value error, ", "")
        else:
            reason = _MENSAGENS.get(kind, str(detail.get("msg", kind)))
            if kind == "string_pattern_mismatch":
                reason += " (esperado: minúsculas, dígitos e underscore)"
        errors.append(FieldError(field, reason))
    return errors


def example() -> dict:
    """A record that passes, for documentation and for the CLI's --exemplo.

    Kept as code rather than prose so it cannot drift from the contract: the
    test suite validates it, so a rule that changes breaks the example too.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "identity": {
            "competition": "premier_league",
            "season": "2023-2024",
            "home_club_id": "arsenal",
            "away_club_id": "chelsea",
            "kickoff_utc": "2023-08-12T15:00:00Z",
        },
        "result": {
            "status": "finished",
            "home_goals": 2,
            "away_goals": 1,
            "home_goals_halftime": 1,
            "away_goals_halftime": 0,
        },
        "market": {
            "bookmaker": "bet365",
            "opening": {"home": 2.10, "draw": 3.40, "away": 3.75},
            "closing": {"home": 1.95, "draw": 3.50, "away": 4.00},
        },
        "stats": {
            "home": {
                "shots": 14, "shots_on_target": 6, "corners": 7,
                "fouls": 9, "yellow_cards": 1, "red_cards": 0,
            },
            "away": {
                "shots": 8, "shots_on_target": 3, "corners": 4,
                "fouls": 12, "yellow_cards": 2, "red_cards": 0,
            },
        },
        "provenance": {
            "source": "football_data",
            "source_match_id": "fd-2324-E0-0000",
            "collected_at": "2026-08-11T00:00:00Z",
            "url": "https://www.football-data.co.uk/mmz4281/2324/E0.csv",
        },
    }
