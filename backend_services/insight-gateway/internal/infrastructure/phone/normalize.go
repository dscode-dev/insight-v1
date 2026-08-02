// Package phone implements the auth.PhoneNormalizer port using
// `github.com/nyaruka/phonenumbers`. Defaults to BR when the user
// submits a number without an international prefix.
package phone

import (
	"github.com/konoha-labs/insight-gateway/internal/domain/auth"
	"github.com/nyaruka/phonenumbers"
)

type Normalizer struct {
	DefaultRegion string // ISO-3166-1 alpha-2 (e.g. "BR")
}

func New(defaultRegion string) *Normalizer {
	if defaultRegion == "" {
		defaultRegion = "BR"
	}
	return &Normalizer{DefaultRegion: defaultRegion}
}

// Normalize parses + validates + formats to E.164. Rejects landlines
// (which can't receive SMS in BR) along with anything unparseable.
func (n *Normalizer) Normalize(raw string) (string, error) {
	parsed, err := phonenumbers.Parse(raw, n.DefaultRegion)
	if err != nil {
		return "", auth.ErrInvalidPhone
	}
	if !phonenumbers.IsPossibleNumber(parsed) {
		return "", auth.ErrInvalidPhone
	}
	if !phonenumbers.IsValidNumber(parsed) {
		return "", auth.ErrInvalidPhone
	}
	t := phonenumbers.GetNumberType(parsed)
	if t != phonenumbers.MOBILE && t != phonenumbers.FIXED_LINE_OR_MOBILE {
		return "", auth.ErrInvalidPhone
	}
	return phonenumbers.Format(parsed, phonenumbers.E164), nil
}
