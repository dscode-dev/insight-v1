package clubregistry

import "testing"

func TestCanonicalResolution(t *testing.T) {
	r := Default()
	cases := []struct {
		query string
		want  string
	}{
		{"Manchester City", "manchester_city"},
		{"Man City", "manchester_city"},
		{"Manchester City FC", "manchester_city"},
		{"manchester_city", "manchester_city"},
		{"MCI", "manchester_city"},
		{"Flamengo", "flamengo"},
		{"CR Flamengo", "flamengo"},
		{"Clube de Regatas do Flamengo", "flamengo"},
		{"Atlético Mineiro", "atletico_mineiro"},
		{"Atlético-MG", "atletico_mineiro"},
		{"Barça", "barcelona"},
		{"FC Bayern München", "bayern_munich"},
	}
	for _, c := range cases {
		got, ok := r.Resolve(c.query)
		if !ok || got != c.want {
			t.Errorf("Resolve(%q) = %q,%v; want %q", c.query, got, ok, c.want)
		}
	}
}

func TestLookupCarriesLogoPath(t *testing.T) {
	r := Default()
	club, ok := r.Lookup("Real Madrid CF")
	if !ok {
		t.Fatal("Real Madrid CF must resolve")
	}
	if club.ClubID != "real_madrid" {
		t.Fatalf("club_id = %q", club.ClubID)
	}
	if club.LogoPath != "/clubs/real_madrid.png" {
		t.Fatalf("logo_path = %q", club.LogoPath)
	}
}

func TestUnknownIsNotFound(t *testing.T) {
	if _, ok := Default().Resolve("Some Unlisted FC"); ok {
		t.Error("unknown club must not resolve")
	}
}

func TestEveryClubHasLogoAndAliases(t *testing.T) {
	r := Default()
	all := r.All()
	if len(all) < 50 {
		t.Fatalf("registry too small: %d", len(all))
	}
	for _, c := range all {
		if c.LogoPath == "" || c.ClubID == "" || c.ShortName == "" {
			t.Errorf("incomplete club: %+v", c)
		}
		// self-resolution invariant
		if id, ok := r.Resolve(c.Name); !ok || id != c.ClubID {
			t.Errorf("name %q does not resolve to %q", c.Name, c.ClubID)
		}
	}
}
