from explorer.pipelines.catalog import THEMES, build_catalog
from explorer.pipelines.estimate import estimate
from explorer.pipelines.seasons import resolve_seasons


def test_catalog_lists_all_registered_sources_and_recommends_high_medium_trust():
    catalog = build_catalog()
    names = {s["name"] for s in catalog["sources"]}
    assert {"espn", "fbref", "football_data", "wikipedia"} <= names
    recommended_names = {s["name"] for s in catalog["recommended"]["sources"]}
    assert "wikipedia" not in recommended_names  # low trust, not auto-recommended
    assert "espn" in recommended_names


def test_catalog_themes_and_durations_are_stable_taxonomies():
    catalog = build_catalog()
    assert catalog["themes"] == list(THEMES)
    assert catalog["durations"] == ["one-shot", "recurring", "custom"]
    # Odds and stats joined fixtures once `build_envelope` stopped forcing
    # entity_type="fixture" — Football-Data.co.uk carries all three in the CSV
    # it was already fetching. Lineups and injuries have contracts and no
    # producer, so they stay out of the recommendation.
    assert catalog["recommended"]["themes"] == ["fixtures", "odds", "stats"]


def test_catalog_competitions_cover_the_registry():
    catalog = build_catalog()
    keys = {c["key"] for c in catalog["competitions"]}
    assert "brasileirao_serie_a" in keys
    assert "world_cup" in keys


def test_resolve_seasons_one_shot_returns_single_season():
    assert len(resolve_seasons("brasileirao_serie_a", {"mode": "one-shot"})) == 1


def test_resolve_seasons_recurring_returns_three_seasons():
    assert len(resolve_seasons("brasileirao_serie_a", {"mode": "recurring"})) == 3


def test_resolve_seasons_world_cup_is_quadrennial():
    seasons = resolve_seasons("world_cup", {"mode": "recurring"})
    assert all(int(s) >= 2018 for s in seasons)
    assert all((int(s) - 2018) % 4 == 0 for s in seasons)


def test_resolve_seasons_cross_year_competition_format():
    seasons = resolve_seasons("premier_league", {"mode": "one-shot"})
    assert "-" in seasons[0]


def test_estimate_zero_when_no_collectible_theme():
    # `lineups`, not `odds`: odds became collectible. The invariant under test
    # is "a theme no adapter produces estimates to zero work", and it needs a
    # theme that is actually still in that state.
    draft = {"sources": [{"name": "espn", "enabled": True}], "competitions": ["brasileirao_serie_a"],
             "themes": ["lineups"], "duration": {"mode": "one-shot"}}
    result = estimate(draft)
    assert result["source_jobs"] == 0
    assert any("collectible" in w for w in result["warnings"])


def test_estimate_positive_for_fixtures():
    draft = {"sources": [{"name": "espn", "enabled": True}], "competitions": ["brasileirao_serie_a"],
             "themes": ["fixtures"], "duration": {"mode": "one-shot"}}
    result = estimate(draft)
    assert result["source_jobs"] == 1
    assert result["estimated_requests"] > 0
    assert result["estimated_runtime_hours"] > 0
    assert result["warnings"] == []


def test_estimate_scales_with_sources_and_competitions():
    draft = {
        "sources": [{"name": "espn", "enabled": True}, {"name": "fbref", "enabled": True}],
        "competitions": ["brasileirao_serie_a", "libertadores"],
        "themes": ["fixtures"], "duration": {"mode": "recurring"},
    }
    result = estimate(draft)
    assert result["source_jobs"] == 2 * 3 * 2  # sources * seasons(recurring) * competitions


def test_estimate_ignores_disabled_sources():
    draft = {"sources": [{"name": "espn", "enabled": False}], "competitions": ["brasileirao_serie_a"],
             "themes": ["fixtures"], "duration": {"mode": "one-shot"}}
    result = estimate(draft)
    assert result["source_jobs"] == 0
    assert "no enabled sources selected" in result["warnings"]
