"""explorer.envelope.v1 → ClickHouse rows for the historical tables.

One envelope maps to exactly one row in exactly one table, chosen by
`entity_type`. The Explorer's envelope already carries provenance
(source, trust_level, confidence, captured_at); it is copied through rather
than recomputed, because a confidence this service invented would be a
number nothing produced.

NULL vs 0. Every optional field maps to None when absent, never to a zero.
A fixture with no score has not been played; a stats row with no shot count
comes from a season the source did not record. Both become 0 the moment
someone writes `or 0`, and then a query for "matches with no shots" returns
every old season.
"""

from __future__ import annotations

from typing import Any, Mapping


class HistoricalMappingError(ValueError):
    """The envelope cannot become a row — missing identity, wrong shape."""


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _decimal_str(value: Any) -> str | None:
    """Decimals stay strings all the way into ClickHouse.

    clickhouse-connect converts a string to Decimal64 losslessly; going
    through float first would round 2.10 to 2.0999999 and put that in a
    column meant for a price.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return str(float(value))
    except (TypeError, ValueError):
        return None


def _identity(envelope: Mapping[str, Any]) -> tuple[str, str, str, str]:
    payload = envelope.get("payload") or {}
    fixture_id = payload.get("external_fixture_id") or envelope.get("external_id")
    if not fixture_id:
        raise HistoricalMappingError("envelope has no external_fixture_id")
    competition = (envelope.get("competition") or {}).get("competition_key") or ""
    season = envelope.get("season") or ""
    source = envelope.get("source") or ""
    if not competition or not season:
        # These two are the partition key. A row without them lands in a
        # partition named for empty strings, which no query for a real
        # competition will ever scan — present in the table and invisible.
        raise HistoricalMappingError(
            f"envelope missing competition_key/season (fixture {fixture_id})")
    return str(fixture_id), str(source), str(competition), str(season)


def _provenance(envelope: Mapping[str, Any]) -> tuple[str, str, Any]:
    return (
        str(envelope.get("trust_level") or "medium"),
        _decimal_str(envelope.get("confidence")) or "0.0",
        envelope.get("captured_at"),
    )


def map_fixture_row(envelope: Mapping[str, Any]) -> tuple[Any, ...]:
    fixture_id, source, competition, season = _identity(envelope)
    payload = envelope.get("payload") or {}
    home = payload.get("home_team") or {}
    away = payload.get("away_team") or {}
    score = payload.get("score") or {}
    trust, confidence, captured_at = _provenance(envelope)

    scheduled_at = payload.get("scheduled_at")
    if not scheduled_at:
        raise HistoricalMappingError(f"fixture {fixture_id} has no scheduled_at")

    return (
        fixture_id,
        source,
        competition,
        season,
        # match_id stays NULL until entity resolution links this to a live
        # match. Minting one here would create an identity nothing else can
        # reproduce, and the join would silently never match.
        None,
        scheduled_at,
        str(home.get("name") or ""),
        str(away.get("name") or ""),
        home.get("club_id"),
        away.get("club_id"),
        str(payload.get("status") or "unknown"),
        _int(score.get("home")),
        _int(score.get("away")),
        _int(score.get("halftime_home")),
        _int(score.get("halftime_away")),
        trust,
        confidence,
        captured_at,
    )


def map_odds_row(envelope: Mapping[str, Any]) -> tuple[Any, ...]:
    fixture_id, source, competition, season = _identity(envelope)
    payload = envelope.get("payload") or {}
    trust, confidence, _ = _provenance(envelope)

    bookmaker = payload.get("bookmaker")
    if not bookmaker:
        raise HistoricalMappingError(f"odds for {fixture_id} names no bookmaker")

    # captured_at from the PAYLOAD, not the envelope: for closing odds the
    # payload carries the match date and the envelope carries the download
    # time. Using the latter would place a 2020 market in 2026.
    captured_at = payload.get("captured_at") or envelope.get("captured_at")

    prices: dict[str, Any] = {}
    extra: list[tuple[str, str, Any]] = []
    for selection in payload.get("selections") or []:
        name = str(selection.get("name") or "").lower()
        price = _decimal_str(selection.get("price"))
        if price is None:
            continue
        if name in ("home", "draw", "away"):
            prices[name] = price
        else:
            # Totals and handicaps keep their line in `point`.
            extra.append((name, price, _decimal_str(selection.get("point"))))

    if not prices and not extra:
        raise HistoricalMappingError(f"odds for {fixture_id} carries no usable price")

    return (
        fixture_id,
        source,
        competition,
        season,
        str(bookmaker),
        str(payload.get("market") or "1x2"),
        captured_at,
        prices.get("home"),
        prices.get("draw"),
        prices.get("away"),
        extra,
        trust,
        confidence,
    )


# Contract field → (home column, away column). Named once so the row builder
# cannot drift from the DDL by a rename in one place.
_STAT_FIELDS: tuple[str, ...] = (
    "shots",
    "shots_on_target",
    "corners",
    "fouls",
    "offsides",
    "yellow_cards",
    "red_cards",
)


def map_stats_row(envelope: Mapping[str, Any]) -> tuple[Any, ...]:
    fixture_id, source, competition, season = _identity(envelope)
    payload = envelope.get("payload") or {}
    home = payload.get("home") or {}
    away = payload.get("away") or {}
    trust, confidence, captured_at = _provenance(envelope)

    if not home and not away:
        raise HistoricalMappingError(f"stats for {fixture_id} carries no counter")

    row: list[Any] = [fixture_id, source, competition, season]
    for side in (home, away):
        for field in _STAT_FIELDS:
            row.append(_int(side.get(field)))
        row.append(_decimal_str(side.get("possession")))
        row.append(_decimal_str(side.get("expected_goals")))
    row.extend([trust, confidence, captured_at])
    return tuple(row)


MAPPERS = {
    "fixture": map_fixture_row,
    "odds_snapshot": map_odds_row,
    "stats": map_stats_row,
}
