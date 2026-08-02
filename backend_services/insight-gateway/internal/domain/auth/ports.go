package auth

import (
	"context"
	"time"

	"github.com/google/uuid"
)

// SmsProvider — port for OTP delivery. Implementations live in
// internal/infrastructure/sms (Null/Zenvia/Twilio).
type SmsProvider interface {
	// Name identifies the provider in audit logs + the OtpChallenge
	// row's `Provider` column ("null", "zenvia", "twilio").
	Name() string

	// SendOtp dispatches the body to phoneE164. Returns the upstream
	// message id (Zenvia: "id", Twilio: "sid") when available — stored
	// on OtpChallenge for support workflows.
	SendOtp(ctx context.Context, phoneE164, body string) (providerMessageID string, err error)
}

// PhoneNormalizer — port for E.164 normalization. Single implementation
// today uses `nyaruka/phonenumbers`; abstracted for tests.
type PhoneNormalizer interface {
	Normalize(raw string) (string, error)
}

// PhoneAuthProvider — Gateway-owned phone verification provider.
//
// Implementations send and verify an OTP with an upstream provider (Supabase,
// future Twilio Verify/MessageBird/etc.). The provider only proves phone
// ownership; it never owns Insight identity, users, roles, or sessions.
type PhoneAuthProvider interface {
	Name() string
	SendCode(ctx context.Context, phoneE164 string) (providerMessageID string, err error)
	VerifyCode(ctx context.Context, phoneE164, code string) error
}

// RefreshSession is one server-side refresh-token record (Auth-A Part 7).
// We store only the SHA-256 hash of the refresh token, never the raw token.
type RefreshSession struct {
	ID        uuid.UUID
	UserID    uuid.UUID
	TokenHash string
	IssuedAt  time.Time
	ExpiresAt time.Time
	RevokedAt *time.Time // nil = live
}

// RefreshSessionStore — port for the server-side refresh-token store that
// makes refresh tokens revocable + rotatable (Auth-A Part 7). Stateless JWT
// refresh remains the wire format; this layer gates whether a given refresh
// token is still honored. Postgres implementation in infrastructure/postgres.
type RefreshSessionStore interface {
	// Create persists a new live session for a freshly issued refresh token.
	Create(ctx context.Context, userID uuid.UUID, tokenHash string, expiresAt time.Time) error
	// Lookup returns the session for a token hash, or ErrRefreshNotFound.
	Lookup(ctx context.Context, tokenHash string) (*RefreshSession, error)
	// Revoke marks the session for a token hash revoked. Idempotent: revoking
	// an unknown or already-revoked hash is not an error.
	Revoke(ctx context.Context, tokenHash string) error
	// RevokeAllForUser revokes every live session for a user (full logout /
	// credential compromise). Returns the number revoked.
	RevokeAllForUser(ctx context.Context, userID uuid.UUID) (int64, error)
}

// CodeHasher — HMAC-SHA256 over the OTP, salted by phone. Pulled out
// as a port so the application code doesn't import crypto directly.
type CodeHasher interface {
	Hash(code, phoneE164 string) string
	Verify(code, expectedHash, phoneE164 string) bool
}

// TokenCodec — issues + verifies JWTs for the 3 token kinds (access,
// refresh, registration). Implementations live in
// internal/infrastructure/jwt.
type TokenCodec interface {
	IssueAccess(userID uuid.UUID, now time.Time) (token string, ttl time.Duration, err error)
	IssueRefresh(userID uuid.UUID, now time.Time) (token string, ttl time.Duration, err error)
	IssueRegistration(phoneE164 string, now time.Time) (token string, ttl time.Duration, err error)

	// DecodeAccess / DecodeRefresh return the user_id when the token
	// is valid (signature + iss + aud + exp + typ all match).
	DecodeAccess(token string) (uuid.UUID, error)
	DecodeRefresh(token string) (uuid.UUID, error)
	DecodeRegistration(token string) (phoneE164 string, err error)
}

// UserCreator — port the gateway uses to create the Social user
// during complete_registration. The production implementation is the
// social.v1.UserService gRPC client adapter
// (infrastructure/socialclient.UserCreator). Implementations map a
// username conflict to ErrUsernameTaken so the application layer can
// errors.Is it.
type UserCreator interface {
	CreateUser(ctx context.Context, username, displayName string, accentColor *string) (uuid.UUID, error)
}

// CooldownStore — Redis-backed sliding window for resend cooldown.
// Abstracted as a port so unit tests can use an in-memory fake.
type CooldownStore interface {
	// LastRequestAt returns the timestamp of the most recent successful
	// request for the phone, or zero time when none.
	LastRequestAt(ctx context.Context, phoneE164 string) (time.Time, error)
	MarkRequested(ctx context.Context, phoneE164 string, at time.Time, ttl time.Duration) error
}
