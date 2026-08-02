// Package sport declares the supported sports universe.
//
// V1 is football-only. The enum exists so every downstream contract
// (RawSportsEvent, CanonicalSportsEvent, FeatureSnapshot in Atlas)
// references the same string literals — never magic strings. Adding
// a new sport is additive-only: append the new constant + extend the
// validator. Never reorder or remove.
package sport

import "errors"

// Sport identifies which sport an event/match belongs to. The string
// value is the wire form — DO NOT change existing values.
type Sport string

const (
	Football Sport = "football"
)

// Supported returns every sport the Hub currently accepts. The
// validator uses this set to reject unsupported sports per the Sprint
// 0 quarantine rule.
func Supported() map[Sport]struct{} {
	return map[Sport]struct{}{
		Football: {},
	}
}

// ErrUnsupportedSport is the canonical error for any event whose
// sport isn't in Supported(). Wrapped by the validation layer with
// the offending value via fmt.Errorf("%w: %s", ErrUnsupportedSport, s).
var ErrUnsupportedSport = errors.New("sport: unsupported")

// IsSupported is a convenience predicate. Validators that need to
// emit a structured error should still consult Supported() so the
// failure can include the rejected value.
func IsSupported(s Sport) bool {
	_, ok := Supported()[s]
	return ok
}

// Parse normalises an inbound string into a Sport. Lowercases + trims;
// returns ErrUnsupportedSport when the result isn't in Supported().
// Use this at every external boundary (HTTP, message ingestion) so
// the domain layer NEVER sees a Sport value that hasn't been vetted.
func Parse(raw string) (Sport, error) {
	s := Sport(normalize(raw))
	if !IsSupported(s) {
		return s, ErrUnsupportedSport
	}
	return s, nil
}

func normalize(s string) string {
	// Manual trim + lowercase to keep the package zero-dependency.
	// stdlib strings would be fine but introducing it here just to
	// trim is overkill for one call site.
	out := make([]byte, 0, len(s))
	start := 0
	end := len(s)
	for start < end && (s[start] == ' ' || s[start] == '\t' || s[start] == '\n') {
		start++
	}
	for end > start && (s[end-1] == ' ' || s[end-1] == '\t' || s[end-1] == '\n') {
		end--
	}
	for i := start; i < end; i++ {
		c := s[i]
		if c >= 'A' && c <= 'Z' {
			c += 'a' - 'A'
		}
		out = append(out, c)
	}
	return string(out)
}
