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


def test_short_name_never_matches_as_a_substring():
    """`Ath Madrid` is Atlético Madrid — not Athletic Bilbao, whose code is ATH.

    The token-subset fallback used to accept any registry key contained in
    the input, and 194 of 220 clubs carry a three-letter code. That filed 76
    Atlético Madrid matches under `athletic_bilbao`, silently: a wrong
    club_id never reaches the review queue the way a None does.
    """
    assert resolve_club("Ath Madrid") == "atletico_madrid"
    assert resolve_club("Ath Bilbao") == "athletic_bilbao"
    # The code still resolves when it IS the whole name.
    assert resolve_club("ATH") == "athletic_bilbao"


def test_city_rival_is_not_absorbed_by_the_bigger_club():
    """Espanyol contains "Barcelona" and is not Barcelona (58 matches' worth)."""
    assert resolve_club("RCD Espanyol de Barcelona") == "espanyol"
    assert resolve_club("Espanyol") == "espanyol"
    assert resolve_club("FC Barcelona") == "barcelona"


def test_ambiguous_subset_refuses_rather_than_guessing():
    """Two clubs equally explaining a name means neither is established.

    None routes to human review; picking one writes an unverified fact into
    every baseline computed from it.
    """
    assert resolve_club("Barcelona Espanyol") is None


def test_longest_subset_key_wins():
    """"real betis" is a better explanation than "betis" — and both are the
    same club here, so the value of ordering is that it is not arbitrary."""
    assert resolve_club("Real Betis Balompié") == "real_betis"


def test_decorated_names_still_resolve_by_subset():
    assert resolve_club("Sociedade Esportiva Palmeiras") == "palmeiras"
    assert resolve_club("Club Atlético de Madrid") == "atletico_madrid"
