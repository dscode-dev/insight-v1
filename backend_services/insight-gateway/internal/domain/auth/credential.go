package auth

import (
	"context"
	"time"

	"github.com/google/uuid"
)

// Credential is the durable identity row. Mirrors the
// `auth_credentials` table (see migrations/00002_whatsapp_auth.sql).
//
// `PhoneE164` is the routing key — username is for display, user_id
// links back to the Social user.
type Credential struct {
	ID          uuid.UUID
	UserID      uuid.UUID
	PhoneE164   string
	Username    string
	CreatedAt   time.Time
	LastLoginAt *time.Time
	// Legal acceptance captured at registration (App Store / Play
	// requirement). Empty versions on a row predate the requirement.
	AcceptedTermsVersion     string
	AcceptedPrivacyVersion   string
	AcceptedUGCPolicyVersion string
	AcceptedLegalAt          *time.Time
}

// CredentialRepo is the port the application layer uses to persist
// and look up credential rows. Implementations live in
// internal/infrastructure/postgres.
type CredentialRepo interface {
	GetByPhone(ctx context.Context, phoneE164 string) (*Credential, error)
	GetByUserID(ctx context.Context, userID uuid.UUID) (*Credential, error)
	GetByUsername(ctx context.Context, username string) (*Credential, error)
	Insert(ctx context.Context, c *Credential) error
	TouchLastLogin(ctx context.Context, id uuid.UUID, t time.Time) error
}

// IsNotFound — repository implementations return this when a lookup
// finds nothing. Application layer checks via errors.Is so the actual
// driver error (pgx.ErrNoRows etc.) doesn't leak upward.
var ErrCredentialNotFound = errOf("credential_not_found")

func errOf(s string) error { return repoErr(s) }

type repoErr string

func (e repoErr) Error() string { return string(e) }
