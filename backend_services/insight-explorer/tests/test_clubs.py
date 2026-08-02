from explorer.clubs import registry_size, resolve_club


def test_registry_loads_expanded_clubs():
    # ML-A seeded 101; ML-C expanded with CONMEBOL clubs + national teams.
    assert registry_size() >= 185


def test_resolves_aliases_and_variants():
    assert resolve_club("Man City") == "manchester_city"
    assert resolve_club("Manchester City FC") == "manchester_city"
    assert resolve_club("Atlético-MG") == "atletico_mineiro"
    assert resolve_club("Sociedade Esportiva Palmeiras") == "palmeiras"
    assert resolve_club("Real Madrid") == "real_madrid"


def test_unresolvable_returns_none():
    assert resolve_club("Some Unknown FC 12345") is None
    assert resolve_club("") is None
