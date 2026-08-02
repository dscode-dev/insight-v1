package auth

import (
	"context"
	"time"

	"github.com/google/uuid"
)

// OtpChallenge mirrors the `auth_otp_challenges` table.
//
// Lifecycle:
//  1. request_otp inserts with `ConsumedAt = nil`, `Attempts = 0`.
//  2. verify_otp fetches the freshest unconsumed row for the phone,
//     increments Attempts, sets ConsumedAt on a code match.
//  3. expired rows are filtered at query time.
type OtpChallenge struct {
	ID                uuid.UUID
	PhoneE164         string
	CodeHash          string
	Provider          string
	ProviderMessageID *string
	Attempts          int
	MaxAttempts       int
	CreatedAt         time.Time
	ExpiresAt         time.Time
	ConsumedAt        *time.Time
}

// IsExpired returns true when ExpiresAt is in the past.
func (c *OtpChallenge) IsExpired(now time.Time) bool {
	return c.ExpiresAt.Before(now)
}

// IsConsumed reports whether the challenge has been consumed.
func (c *OtpChallenge) IsConsumed() bool { return c.ConsumedAt != nil }

// IsExhausted reports whether the attempt counter hit the cap.
func (c *OtpChallenge) IsExhausted() bool { return c.Attempts >= c.MaxAttempts }

// OtpChallengeRepo — port for the OTP table.
type OtpChallengeRepo interface {
	// Insert a new challenge. Caller assigns ID + ExpiresAt.
	Insert(ctx context.Context, ch *OtpChallenge) error

	// FreshestUnconsumed returns the most recent unconsumed challenge
	// for the phone, or (nil, ErrChallengeNotFound) if none exists.
	// Expired-but-unconsumed rows ARE returned — the caller checks
	// IsExpired so the user gets a 410 (gone) rather than 401 (invalid).
	FreshestUnconsumed(ctx context.Context, phoneE164 string) (*OtpChallenge, error)

	// MostRecentCreatedAt returns the timestamp of the freshest
	// challenge for the phone, used to enforce the resend cooldown.
	// Returns zero time when none exists.
	MostRecentCreatedAt(ctx context.Context, phoneE164 string) (time.Time, error)

	// IncrementAttempts bumps the counter by 1.
	IncrementAttempts(ctx context.Context, id uuid.UUID) error

	// MarkConsumed sets ConsumedAt = t.
	MarkConsumed(ctx context.Context, id uuid.UUID, t time.Time) error
}

// ErrChallengeNotFound — repo returns this when no row matches.
var ErrChallengeNotFound = errOf("otp_challenge_not_found")
