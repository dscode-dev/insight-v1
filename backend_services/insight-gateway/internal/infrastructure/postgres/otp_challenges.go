package postgres

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/konoha-labs/insight-gateway/internal/domain/auth"
)

type OtpChallengeRepo struct {
	pool *pgxpool.Pool
}

func NewOtpChallengeRepo(pool *pgxpool.Pool) *OtpChallengeRepo {
	return &OtpChallengeRepo{pool: pool}
}

const otpColumns = `
	id, phone_e164, code_hash, provider, provider_message_id,
	attempts, max_attempts, created_at, expires_at, consumed_at
`

func (r *OtpChallengeRepo) Insert(ctx context.Context, ch *auth.OtpChallenge) error {
	const q = `
		INSERT INTO auth_otp_challenges (
			id, phone_e164, code_hash, provider, provider_message_id,
			attempts, max_attempts, created_at, expires_at, consumed_at
		)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
	`
	_, err := r.pool.Exec(ctx, q,
		ch.ID, ch.PhoneE164, ch.CodeHash, ch.Provider, ch.ProviderMessageID,
		ch.Attempts, ch.MaxAttempts, ch.CreatedAt, ch.ExpiresAt, ch.ConsumedAt,
	)
	return err
}

func (r *OtpChallengeRepo) FreshestUnconsumed(ctx context.Context, phoneE164 string) (*auth.OtpChallenge, error) {
	const q = `
		SELECT ` + otpColumns + `
		FROM auth_otp_challenges
		WHERE phone_e164 = $1 AND consumed_at IS NULL
		ORDER BY created_at DESC
		LIMIT 1
	`
	row := r.pool.QueryRow(ctx, q, phoneE164)
	var ch auth.OtpChallenge
	if err := row.Scan(
		&ch.ID, &ch.PhoneE164, &ch.CodeHash, &ch.Provider, &ch.ProviderMessageID,
		&ch.Attempts, &ch.MaxAttempts, &ch.CreatedAt, &ch.ExpiresAt, &ch.ConsumedAt,
	); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, auth.ErrChallengeNotFound
		}
		return nil, err
	}
	return &ch, nil
}

func (r *OtpChallengeRepo) MostRecentCreatedAt(ctx context.Context, phoneE164 string) (time.Time, error) {
	const q = `
		SELECT created_at
		FROM auth_otp_challenges
		WHERE phone_e164 = $1
		ORDER BY created_at DESC
		LIMIT 1
	`
	row := r.pool.QueryRow(ctx, q, phoneE164)
	var t time.Time
	if err := row.Scan(&t); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return time.Time{}, nil
		}
		return time.Time{}, err
	}
	return t, nil
}

func (r *OtpChallengeRepo) IncrementAttempts(ctx context.Context, id uuid.UUID) error {
	const q = `UPDATE auth_otp_challenges SET attempts = attempts + 1 WHERE id = $1`
	_, err := r.pool.Exec(ctx, q, id)
	return err
}

func (r *OtpChallengeRepo) MarkConsumed(ctx context.Context, id uuid.UUID, t time.Time) error {
	const q = `UPDATE auth_otp_challenges SET consumed_at = $1 WHERE id = $2`
	_, err := r.pool.Exec(ctx, q, t, id)
	return err
}
