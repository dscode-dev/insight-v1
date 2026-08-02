// Package preferences holds the UserPreferences aggregate (Sprint D).
//
// 1:1 with User. Lazy-created on first read by the repo using an
// INSERT ... ON CONFLICT DO NOTHING pattern, so the application code
// never has to think about "does the user have prefs yet" — Get
// always returns a row.
//
// Locale storage: BCP 47 string. We don't validate the format
// strictly (the set of acceptable codes is large + open-ended); we
// only cap the length so the column stays small.
//
// digest_frequency: enum-like varchar with a CHECK constraint at the
// schema level. Validated again here so the application layer can
// emit a typed error before paying the DB round-trip.
package preferences

import (
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
)

const (
	MaxLocaleLen = 8

	DigestDaily  = "daily"
	DigestWeekly = "weekly"
	DigestNever  = "never"

	DefaultLocale          = "pt-BR"
	DefaultDigestFrequency = DigestDaily
)

var (
	ErrInvalidLocale          = errors.New("preferences: invalid locale")
	ErrInvalidDigestFrequency = errors.New("preferences: invalid digest_frequency")
)

type Preferences struct {
	UserID          uuid.UUID
	Locale          string
	PushEnabled     bool
	EmailEnabled    bool
	DigestFrequency string
	UpdatedAt       time.Time
}

// Update is the patch type for partial updates. nil means "leave as
// is". The repo merges it into the existing row in a single SQL
// statement so we avoid the read-modify-write race.
type Update struct {
	Locale          *string
	PushEnabled     *bool
	EmailEnabled    *bool
	DigestFrequency *string
}

// Validate runs the field-level checks before the repo round-trip.
// Returns nil when every set field passes; the first failure short-
// circuits so the caller's error chain stays single-cause.
func (u *Update) Validate() error {
	if u.Locale != nil {
		if err := ValidateLocale(*u.Locale); err != nil {
			return err
		}
	}
	if u.DigestFrequency != nil {
		if err := ValidateDigestFrequency(*u.DigestFrequency); err != nil {
			return err
		}
	}
	return nil
}

func ValidateLocale(locale string) error {
	if locale == "" {
		return fmt.Errorf("%w: empty", ErrInvalidLocale)
	}
	if len(locale) > MaxLocaleLen {
		return fmt.Errorf("%w: length %d > %d", ErrInvalidLocale, len(locale), MaxLocaleLen)
	}
	return nil
}

func ValidateDigestFrequency(s string) error {
	switch s {
	case DigestDaily, DigestWeekly, DigestNever:
		return nil
	default:
		return fmt.Errorf("%w: %q (want daily|weekly|never)", ErrInvalidDigestFrequency, s)
	}
}
