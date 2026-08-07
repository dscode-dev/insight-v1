"""Historical baselines must filter teams by club_id, never by a source's spelling.

Three sources store the same club under three names — `Barcelona`,
`FC Barcelona`; `Betis`, `Real Betis`, `Real Betis Balompié` — and all of
them are kept, because the raw name is what the source actually said.
Filtering on it answers with whichever subset happens to share the caller's
spelling: `home_team_name = 'Barcelona'` matched 92 of Barcelona's 236
matches, and the reply carried a sample_size of 92 with nothing to suggest
the other 144 existed.

A wrong number that looks reasonable is the failure mode worth a test. This
one reads the SQL rather than running it, so it holds without a ClickHouse.
"""

from __future__ import annotations

import re
from pathlib import Path

_SERVICE = (
    Path(__file__).resolve().parents[1]
    / "anvil" / "features" / "historical_service.py"
)

_SOURCE = _SERVICE.read_text(encoding="utf-8")


def _queries(source: str) -> list[str]:
    """The SQL only — every `f\"\"\"...\"\"\"` block, minus its `--` comments.

    Reading the whole module instead would let prose satisfy these
    assertions: the docstrings name `home_team_name` repeatedly, since
    explaining the rule means naming what it forbids.
    """
    blocks = re.findall(r'f"""(.*?)"""', source, re.DOTALL)
    return [re.sub(r"--.*$", "", block, flags=re.MULTILINE) for block in blocks]


_SQL = "\n".join(_queries(_SOURCE))


def _predicates(column: str, sql: str = _SQL) -> list[str]:
    """Every comparison of `column` against a bound parameter."""
    return re.findall(rf"\b{column}\s*=\s*\{{\{{\w+:String\}}\}}", sql)


def test_team_filters_use_club_id():
    assert _predicates("home_club_id"), "nenhum filtro por home_club_id"
    assert _predicates("away_club_id"), "nenhum filtro por away_club_id"


def test_no_query_filters_on_the_raw_team_name():
    offenders = _predicates("home_team_name") + _predicates("away_team_name")
    assert not offenders, (
        "filtro por nome cru reintroduzido: "
        f"{offenders} — use home_club_id/away_club_id"
    )


def test_raw_names_are_still_selected_for_the_caller():
    """Dropping them would be an over-correction: a resenha names the club
    the way the source did, and an id is not a display name."""
    assert "home_team_name" in _SQL
    assert "away_team_name" in _SQL


def test_optional_query_params_do_not_go_through_the_required_helper():
    """`_first` raises on absence, so `_first(q, k) or None` never reaches the
    `or` — head-to-head's optional competition filter answered 400 to every
    call that left it out."""
    routes = (
        _SERVICE.parent.parent / "runtime" / "health.py"
    ).read_text(encoding="utf-8")
    dispatch = routes.split("_historical_query")[1].split("async def start")[0]
    assert '_first(query, "competition_key") or None' not in dispatch
    assert '_optional(query, "competition_key")' in dispatch


def test_head_to_head_collapses_the_sources_of_one_meeting():
    """Ungrouped, three sources made three rows of one meeting — so `limit=10`
    returned about three meetings and counted them as ten."""
    body = _SOURCE.split("async def head_to_head")[1].split("\n    async def")[0]
    sql = "\n".join(_queries(body))
    assert sql, "head_to_head sem query"
    assert "GROUP BY" in sql
    assert "match_day" in sql, "a data e o que identifica o confronto"
    assert "groupUniqArray(source)" in sql, (
        "quais fontes cobriram o confronto deve viajar com a resposta"
    )
