"""What makes two records the same match. One rule, one place.

    match_uid("premier_league", "2023-2024", "arsenal", "chelsea", "2023-08-12")

THE RULE. A match is identified by competition, season, home club, away club
and the UTC day it kicked off. Deliberately NOT by the source's own row id:
Football-Data calls the 2020-11-07 Barcelona–Betis `fd-2021-SP1-0075`,
openfootball calls it `of-es.1-2020-21-0075`, StatsBomb `sb-3773477`. One
match, three ids — and anything keyed on them counts it three times.

WHY THE DAY AND NOT THE FULL KICKOFF. Sources agree on the date and disagree
on the clock: Football-Data publishes no time and the normaliser writes
00:00, openfootball carries the real 19:30. Truncating to the UTC date makes
those one match without needing a tolerance window.

WHY NOT DROP THE DATE. A league plays each ordered pair once a season, which
would make the date redundant — but a Champions League side can host the same
opponent in the group stage and again in a semi-final. The date separates
them.

WHY THIS MODULE EXISTS AT ALL. The rule was fixed in
`atlas.intelligence.corpus` in August 2026 and NOT in `atlas.strength.lake`,
which kept keying on `external_id`. The consequence was invisible and
expensive: 1.554 matches folded into Elo, head-to-head and the league table
two or three times each — 10.156 ledger rows for 7.127 real matches. Nothing
failed; the ratings were simply wrong. A rule that decides identity cannot
live in two copies, so it now lives in none of them.

NOT `atlas.identity`. That package resolves PROVIDER observations of a live
match into a canonical id, for the streaming path — a different problem, and
its `atlas.canonical_match` table is empty. This is the offline rule, for
records that already carry club ids. If the two are ever unified, this
docstring is the place to say so.
"""

from __future__ import annotations

import uuid
from datetime import datetime

#: Shared with `atlas/outcome/train.py`. Changing it re-keys every historical
#: match, which orphans every stored vector — the uid is the primary key of
#: `atlas.atlas_vector_memory`.
NAMESPACE = uuid.UUID("00000000-0000-0000-0000-0000a71a5dee")


def match_uid(
    competition: str, season: str, home: str, away: str, day: str
) -> str:
    """The uid for one real match. `day` is an ISO date (YYYY-MM-DD)."""
    return str(uuid.uuid5(NAMESPACE, f"{competition}|{season}|{home}|{away}|{day}"))


def match_uid_from(
    competition: str, season: str, home: str, away: str, kickoff: datetime
) -> str:
    """Same rule, taking the kickoff instant and truncating it here.

    Offered so no caller has to remember that the date is UTC and that the
    clock is dropped — the two mistakes that would silently split a match.
    """
    return match_uid(competition, season, home, away, kickoff.date().isoformat())
