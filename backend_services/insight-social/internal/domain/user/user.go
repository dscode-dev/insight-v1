// Package user holds the User aggregate root.
//
// Invariants enforced here (not at the DB):
//   - username: 3..32 chars, ASCII [a-z0-9_], lowercased on creation
//   - display_name: 1..64 chars after trim
//   - initials: derived from display_name; up to 4 chars uppercase
//   - accent_color: #RRGGBB; auto-derived from username when empty
//   - reputation: 0..100 (clamped at the edges by domain rules)
//
// The aggregate is constructed two ways:
//   - New() — applies invariants and assigns defaults. Used when the
//     application layer is creating a fresh user.
//   - Reconstitute() — trusts persisted data, no validation. Used by
//     repositories when hydrating from Postgres rows.
package user

import (
	"fmt"
	"hash/crc32"
	"regexp"
	"strings"
	"time"
	"unicode"

	"github.com/google/uuid"
)

// Palette used to derive a stable accent_color when the caller didn't
// supply one. Order matters — once a username's hash maps to an index,
// removing or reordering entries would shift existing users' colors.
// Append-only when extending.
var accentPalette = []string{
	"#5BA8FF", // azul (default)
	"#FF7A59", // coral
	"#FFC857", // âmbar
	"#56C596", // verde
	"#B388EB", // lavanda
	"#FF6B9D", // rosa
	"#4ECDC4", // turquesa
	"#F4A261", // ocre
}

var (
	usernameRE = regexp.MustCompile(`^[a-z0-9_]{3,32}$`)
	hexColorRE = regexp.MustCompile(`^#[0-9A-Fa-f]{6}$`)
)

type User struct {
	id          uuid.UUID
	username    string
	displayName string
	initials    string
	accentColor string
	reputation  int
	tier        Tier
	createdAt   time.Time
	avatarURL   string // Sprint C — empty when no upload yet
}

// New validates inputs + assigns derived fields. accentColor may be
// empty — in that case derive from username.
func New(username, displayName, accentColor string) (*User, error) {
	username = strings.ToLower(strings.TrimSpace(username))
	displayName = strings.TrimSpace(displayName)

	if !usernameRE.MatchString(username) {
		return nil, fmt.Errorf("%w: must match %s", ErrInvalidUsername, usernameRE.String())
	}
	if l := len(displayName); l < 1 || l > 64 {
		return nil, fmt.Errorf("%w: length %d out of 1..64", ErrInvalidDisplayName, l)
	}
	if accentColor == "" {
		accentColor = deriveAccent(username)
	} else if !hexColorRE.MatchString(accentColor) {
		return nil, fmt.Errorf("%w: %q is not #RRGGBB", ErrInvalidAccentColor, accentColor)
	}

	const defaultReputation = 50
	return &User{
		id:          uuid.New(),
		username:    username,
		displayName: displayName,
		initials:    deriveInitials(displayName),
		accentColor: accentColor,
		reputation:  defaultReputation,
		tier:        TierForScore(defaultReputation),
		createdAt:   time.Now().UTC(),
	}, nil
}

// Reconstitute rehydrates an aggregate from persisted state. No
// invariant checks — repository contract guarantees a row already
// satisfied them when it was written.
//
// Sprint C added avatarURL. Existing callers can pass "" — it
// behaves identically to a pre-Sprint-C user.
func Reconstitute(id uuid.UUID, username, displayName, initials, accentColor string,
	reputation int, tier Tier, createdAt time.Time, avatarURL string) *User {
	return &User{
		id:          id,
		username:    username,
		displayName: displayName,
		initials:    initials,
		accentColor: accentColor,
		reputation:  reputation,
		tier:        tier,
		createdAt:   createdAt,
		avatarURL:   avatarURL,
	}
}

// ---- accessors (read-only — aggregates own their state) ----
func (u *User) ID() uuid.UUID        { return u.id }
func (u *User) Username() string     { return u.username }
func (u *User) DisplayName() string  { return u.displayName }
func (u *User) Initials() string     { return u.initials }
func (u *User) AccentColor() string  { return u.accentColor }
func (u *User) Reputation() int      { return u.reputation }
func (u *User) Tier() Tier           { return u.tier }
func (u *User) CreatedAt() time.Time { return u.createdAt }
func (u *User) AvatarURL() string    { return u.avatarURL }

// ChangeAccent updates the accent color; validates format.
func (u *User) ChangeAccent(accentColor string) error {
	if err := ValidateAccentColor(accentColor); err != nil {
		return err
	}
	u.accentColor = accentColor
	return nil
}

// ValidateAccentColor is exported so the application layer can guard
// inputs (e.g. UpdateAccent use-case) without instantiating an
// aggregate just to throw it away.
func ValidateAccentColor(accentColor string) error {
	if !hexColorRE.MatchString(accentColor) {
		return fmt.Errorf("%w: %q is not #RRGGBB", ErrInvalidAccentColor, accentColor)
	}
	return nil
}

// ValidateAvatarURL guards the UpdateAvatar input. Empty is allowed
// (clears the avatar). Otherwise we require an absolute http(s) URL —
// not the full picture of allowed sources, but a sane minimum that
// catches accidental relative paths from a misconfigured client.
//
// Length cap (2KB) keeps the column small and avoids storing data
// URIs (someone trying to inline image bytes in the URL field).
const MaxAvatarURLLen = 2048

func ValidateAvatarURL(avatarURL string) error {
	if avatarURL == "" {
		return nil
	}
	if len(avatarURL) > MaxAvatarURLLen {
		return fmt.Errorf("%w: length %d > %d", ErrInvalidAvatarURL, len(avatarURL), MaxAvatarURLLen)
	}
	if !(strings.HasPrefix(avatarURL, "http://") || strings.HasPrefix(avatarURL, "https://")) {
		return fmt.Errorf("%w: must be an absolute http(s) URL", ErrInvalidAvatarURL)
	}
	return nil
}

// ChangeAvatar updates the URL on the aggregate. The repo handles
// persistence + the NULL-on-empty mapping at the SQL layer.
func (u *User) ChangeAvatar(avatarURL string) error {
	if err := ValidateAvatarURL(avatarURL); err != nil {
		return err
	}
	u.avatarURL = avatarURL
	return nil
}

// ---- derivations ----

// deriveAccent picks a palette slot deterministically from the
// username. crc32 is plenty — we don't need cryptographic mixing,
// we need a stable, fast bucket assignment that survives restarts.
func deriveAccent(username string) string {
	h := crc32.ChecksumIEEE([]byte(username))
	return accentPalette[int(h)%len(accentPalette)]
}

// deriveInitials: first letter of first 2 whitespace-separated words,
// uppercased. If only one word, first 2 letters of that word.
func deriveInitials(displayName string) string {
	words := strings.FieldsFunc(displayName, unicode.IsSpace)
	switch len(words) {
	case 0:
		return ""
	case 1:
		runes := []rune(words[0])
		if len(runes) >= 2 {
			return strings.ToUpper(string(runes[:2]))
		}
		return strings.ToUpper(string(runes))
	default:
		first := []rune(words[0])
		second := []rune(words[1])
		return strings.ToUpper(string(first[0]) + string(second[0]))
	}
}
