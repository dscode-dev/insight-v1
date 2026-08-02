// Package clubregistry is the shared, embedded canonical football-club
// identity layer for the Insight platform (Club Registry Foundation).
//
// The registry JSON is generated offline by scripts/club_logo_crawler
// and embedded here so every Go service (Sport Hub, Gateway, …) resolves
// club identity + logo path WITHOUT a runtime dependency on a third-party
// logo API. Resolution is canonical: name / short / any alias →
// stable club_id.
package clubregistry

import (
	_ "embed"
	"encoding/json"
	"strings"
	"sync"
	"unicode"
)

//go:embed club_registry.json
var registryJSON []byte

// Club is one canonical club identity.
type Club struct {
	ClubID       string   `json:"club_id"`
	Name         string   `json:"name"`
	ShortName    string   `json:"short_name"`
	Country      string   `json:"country"`
	Competition  string   `json:"competition"`
	Competitions []string `json:"competitions"`
	LogoPath     string   `json:"logo_path"`
	Aliases      []string `json:"aliases"`
}

// Registry is the immutable, indexed club set.
type Registry struct {
	Version string
	clubs   map[string]Club // club_id -> club
	index   map[string]string // normalized alias/name/short -> club_id
}

var (
	defaultOnce sync.Once
	defaultReg  *Registry
)

// Default returns the process-wide embedded registry (parsed once).
func Default() *Registry {
	defaultOnce.Do(func() {
		r, err := parse(registryJSON)
		if err != nil {
			panic("clubregistry: embedded registry invalid: " + err.Error())
		}
		defaultReg = r
	})
	return defaultReg
}

func parse(raw []byte) (*Registry, error) {
	var doc struct {
		Version string `json:"version"`
		Clubs   []Club `json:"clubs"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		return nil, err
	}
	r := &Registry{
		Version: doc.Version,
		clubs:   make(map[string]Club, len(doc.Clubs)),
		index:   make(map[string]string),
	}
	for _, c := range doc.Clubs {
		r.clubs[c.ClubID] = c
		r.index[normalize(c.ClubID)] = c.ClubID
		r.index[normalize(c.Name)] = c.ClubID
		r.index[normalize(c.ShortName)] = c.ClubID
		for _, a := range c.Aliases {
			r.index[normalize(a)] = c.ClubID
		}
	}
	return r, nil
}

// Resolve maps any name / short code / alias to its canonical club_id.
// Returns ("", false) when unknown. Canonical examples:
//
//	"Manchester City", "Man City", "Manchester City FC" → "manchester_city"
func (r *Registry) Resolve(query string) (string, bool) {
	id, ok := r.index[normalize(query)]
	return id, ok
}

// Get returns the club by canonical id.
func (r *Registry) Get(clubID string) (Club, bool) {
	c, ok := r.clubs[clubID]
	return c, ok
}

// Lookup resolves any query and returns the full club in one step.
func (r *Registry) Lookup(query string) (Club, bool) {
	if id, ok := r.Resolve(query); ok {
		return r.Get(id)
	}
	return Club{}, false
}

// All returns every club (stable order is not guaranteed).
func (r *Registry) All() []Club {
	out := make([]Club, 0, len(r.clubs))
	for _, c := range r.clubs {
		out = append(out, c)
	}
	return out
}

// normalize folds case, strips accents + non-alphanumerics so
// "Atlético-MG", "atletico mg" and "AtleticoMG" collide.
func normalize(s string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(strings.TrimSpace(s)) {
		switch {
		case unicode.IsLetter(r) || unicode.IsDigit(r):
			b.WriteRune(foldAccent(r))
		default:
			// drop separators/punctuation entirely
		}
	}
	return b.String()
}

func foldAccent(r rune) rune {
	switch r {
	case 'á', 'à', 'â', 'ã', 'ä':
		return 'a'
	case 'é', 'è', 'ê', 'ë':
		return 'e'
	case 'í', 'ì', 'î', 'ï':
		return 'i'
	case 'ó', 'ò', 'ô', 'õ', 'ö':
		return 'o'
	case 'ú', 'ù', 'û', 'ü':
		return 'u'
	case 'ç':
		return 'c'
	case 'ñ':
		return 'n'
	}
	return r
}
