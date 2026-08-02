package notification

import (
	"fmt"
	"strings"

	"github.com/google/uuid"
)

// DedupKey builds a DETERMINISTIC, content-addressed dedup key — never
// timestamp-based. Same event ⇒ same key ⇒ at most one notification per
// recipient (ON CONFLICT DO NOTHING). Shape: "<verb>:<scope...>".
//
// Examples:
//   reaction:discussion:842:user:18
//   reply:discussion:842:comment:991
//   mention:discussion:842:user:55
//   join:community:12:user:7
//
// Parts are lowercased and joined by ':'; empty parts are dropped so callers
// can't accidentally create ambiguous keys.
func DedupKey(parts ...string) string {
	cleaned := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.ToLower(strings.TrimSpace(p))
		if p != "" {
			cleaned = append(cleaned, p)
		}
	}
	return strings.Join(cleaned, ":")
}

// IDPart renders a uuid as a dedup-key segment.
func IDPart(id uuid.UUID) string { return id.String() }

// Ref is a convenience for the common "<kind>:<id>" scope segment.
func Ref(kind string, id uuid.UUID) string {
	return fmt.Sprintf("%s:%s", strings.ToLower(kind), id.String())
}
