package postgres

import (
	"context"
	"database/sql"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/konoha-labs/insight-gateway/internal/domain/auth"
)

type CredentialRepo struct {
	pool *pgxpool.Pool
}

func NewCredentialRepo(pool *pgxpool.Pool) *CredentialRepo {
	return &CredentialRepo{pool: pool}
}

const credentialColumns = `
	id, user_id, phone_e164, username, created_at, last_login_at,
	accepted_terms_version, accepted_privacy_version,
	accepted_ugc_policy_version, accepted_legal_at
`

func (r *CredentialRepo) GetByPhone(ctx context.Context, phoneE164 string) (*auth.Credential, error) {
	const q = `SELECT ` + credentialColumns + ` FROM auth_credentials WHERE phone_e164 = $1`
	return r.scanOne(ctx, q, phoneE164)
}

func (r *CredentialRepo) GetByUserID(ctx context.Context, userID uuid.UUID) (*auth.Credential, error) {
	const q = `SELECT ` + credentialColumns + ` FROM auth_credentials WHERE user_id = $1`
	return r.scanOne(ctx, q, userID)
}

func (r *CredentialRepo) GetByUsername(ctx context.Context, username string) (*auth.Credential, error) {
	const q = `SELECT ` + credentialColumns + ` FROM auth_credentials WHERE username = $1`
	return r.scanOne(ctx, q, username)
}

func (r *CredentialRepo) Insert(ctx context.Context, c *auth.Credential) error {
	const q = `
		INSERT INTO auth_credentials
		    (id, user_id, phone_e164, username, created_at, last_login_at,
		     accepted_terms_version, accepted_privacy_version,
		     accepted_ugc_policy_version, accepted_legal_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
	`
	var termsVersion *string
	if c.AcceptedTermsVersion != "" {
		termsVersion = &c.AcceptedTermsVersion
	}
	var privacyVersion *string
	if c.AcceptedPrivacyVersion != "" {
		privacyVersion = &c.AcceptedPrivacyVersion
	}
	var ugcVersion *string
	if c.AcceptedUGCPolicyVersion != "" {
		ugcVersion = &c.AcceptedUGCPolicyVersion
	}
	_, err := r.pool.Exec(ctx, q,
		c.ID, c.UserID, c.PhoneE164, c.Username, c.CreatedAt, c.LastLoginAt,
		termsVersion, privacyVersion, ugcVersion, c.AcceptedLegalAt,
	)
	return err
}

func (r *CredentialRepo) TouchLastLogin(ctx context.Context, id uuid.UUID, t time.Time) error {
	const q = `UPDATE auth_credentials SET last_login_at = $1 WHERE id = $2`
	_, err := r.pool.Exec(ctx, q, t, id)
	return err
}

func (r *CredentialRepo) scanOne(ctx context.Context, query string, args ...any) (*auth.Credential, error) {
	row := r.pool.QueryRow(ctx, query, args...)
	var c auth.Credential
	var termsVersion, privacyVersion, ugcVersion sql.NullString
	if err := row.Scan(
		&c.ID, &c.UserID, &c.PhoneE164, &c.Username, &c.CreatedAt, &c.LastLoginAt,
		&termsVersion, &privacyVersion, &ugcVersion, &c.AcceptedLegalAt,
	); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, auth.ErrCredentialNotFound
		}
		return nil, err
	}
	c.AcceptedTermsVersion = termsVersion.String
	c.AcceptedPrivacyVersion = privacyVersion.String
	c.AcceptedUGCPolicyVersion = ugcVersion.String
	return &c, nil
}
