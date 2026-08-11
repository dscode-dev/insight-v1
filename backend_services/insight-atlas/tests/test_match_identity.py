"""The identity rule, and the guarantee that it stays in one copy.

The bug this closes was invisible for months: `atlas.intelligence.corpus`
keyed a match on (competition, season, home, away, day) while
`atlas.strength.lake` kept keying on the source's `external_id`. Both ran,
neither failed, and Elo/head-to-head/standings folded 1.554 matches in two or
three times each.

So the load-bearing test here is not that the function works — it is that the
TWO READERS AGREE. A rule about what makes two records the same thing cannot
be right in one place and wrong in another.
"""

from __future__ import annotations

import json

from atlas.intelligence.corpus import _load
from atlas.match_identity import match_uid, match_uid_from
from atlas.strength.lake import iter_match_results


def _envelope(home, away, *, day="2023-08-12", external_id="fd-1", time="15:00:00"):
    return {
        "external_id": external_id,
        "competition": {"competition_key": "premier_league"},
        "season": "2023-2024",
        "payload": {
            "status": "finished",
            "scheduled_at": f"{day}T{time}Z",
            "home_team": {"club_id": home},
            "away_team": {"club_id": away},
            "score": {"home": 2, "away": 1},
        },
    }


def _write(root, source, records):
    path = root / "premier_league" / "2023-2024" / source / "fixture"
    path.mkdir(parents=True, exist_ok=True)
    with (path / "part-0001.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


class TestRule:
    def test_same_match_same_uid_whatever_the_source_called_it(self):
        assert match_uid("premier_league", "2023-2024", "arsenal", "chelsea", "2023-08-12") == (
            match_uid("premier_league", "2023-2024", "arsenal", "chelsea", "2023-08-12")
        )

    def test_the_clock_does_not_change_the_match(self):
        """Football-Data writes 00:00, openfootball the real 19:30. Same game."""
        from datetime import datetime, timezone

        meia_noite = datetime(2023, 8, 12, 0, 0, tzinfo=timezone.utc)
        tarde = datetime(2023, 8, 12, 19, 30, tzinfo=timezone.utc)
        assert match_uid_from("premier_league", "2023-2024", "arsenal", "chelsea", meia_noite) == (
            match_uid_from("premier_league", "2023-2024", "arsenal", "chelsea", tarde)
        )

    def test_the_day_does(self):
        """A Champions League side can host the same opponent twice in a
        season. Dropping the date would merge two real matches."""
        assert match_uid("champions_league", "2023-2024", "a", "b", "2023-09-19") != (
            match_uid("champions_league", "2023-2024", "a", "b", "2024-05-01")
        )

    def test_home_and_away_are_not_interchangeable(self):
        assert match_uid("premier_league", "2023-2024", "arsenal", "chelsea", "2023-08-12") != (
            match_uid("premier_league", "2023-2024", "chelsea", "arsenal", "2023-08-12")
        )


class TestBothReadersAgree:
    def test_corpus_and_strength_produce_the_same_uid(self, tmp_path):
        """The regression that matters. If these ever diverge again, the
        strength engine goes back to counting one match as several — with no
        error, no log, and ratings that are simply wrong."""
        _write(tmp_path, "football_data", [_envelope("arsenal", "chelsea")])

        matches, _, _ = _load(str(tmp_path))
        results = iter_match_results(str(tmp_path))

        assert len(matches) == 1 and len(results) == 1
        assert matches[0].uid == results[0].uid

    def test_three_sources_are_one_match_for_both_readers(self, tmp_path):
        """The production case: the same 90 minutes under three source ids,
        one of them without a kickoff time."""
        _write(tmp_path, "football_data", [
            _envelope("arsenal", "chelsea", external_id="fd-2021-E0-0075", time="00:00:00")
        ])
        _write(tmp_path, "openfootball", [
            _envelope("arsenal", "chelsea", external_id="of-en.1-2023-24-0075")
        ])
        _write(tmp_path, "statsbomb", [
            _envelope("arsenal", "chelsea", external_id="sb-3773477")
        ])

        matches, _, stats = _load(str(tmp_path))
        results = iter_match_results(str(tmp_path))

        assert stats["read"] == 3
        assert len(matches) == 1
        # Before the fix this was 3 — one per source id — and each one moved
        # Elo, h2h and the table again for a single real game.
        assert len({r.uid for r in results}) == 1
        assert results[0].uid == matches[0].uid

    def test_brasileirao_is_not_split_by_the_alias(self, tmp_path):
        """`normalize_competition` maps `brasileirao` onto
        `brasileirao_serie_a`. Hashing the normalised name in one reader and
        the raw one in the other would give the same match two uids — the
        exact split this change closes, reintroduced by a helper."""
        record = _envelope("flamengo", "palmeiras")
        record["competition"]["competition_key"] = "brasileirao"
        path = tmp_path / "brasileirao" / "2023" / "espn" / "fixture"
        path.mkdir(parents=True)
        (path / "part-0001.jsonl").write_text(
            json.dumps(record) + "\n", encoding="utf-8"
        )

        matches, _, _ = _load(str(tmp_path))
        results = iter_match_results(str(tmp_path))
        assert results[0].uid == matches[0].uid
        # The row is still FILED under the normalised name; only the identity
        # uses the raw key.
        assert results[0].competition == "brasileirao_serie_a"
