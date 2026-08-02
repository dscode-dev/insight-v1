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

// RefreshSessionRepo is the Postgres implementation of
// auth.RefreshSessionStore (Auth-A Part 7). It stores only token hashes.
type RefreshSessionRepo struct {
	pool *pgxpool.Pool
}

func NewRefreshSessionRepo(pool *pgxpool.Pool) *RefreshSessionRepo {
	return &RefreshSessionRepo{pool: pool}
}

const refreshSessionColumns = `id, user_id, token_hash, issued_at, expires_at, revoked_at`

func (r *RefreshSessionRepo) Create(ctx context.Context, userID uuid.UUID, tokenHash string, expiresAt time.Time) error {
	const q = `
		INSERT INTO auth_refresh_sessions (id, user_id, token_hash, expires_at)
		VALUES ($1, $2, $3, $4)
	`
	_, err := r.pool.Exec(ctx, q, uuid.New(), userID, tokenHash, expiresAt)
	return err
}

func (r *RefreshSessionRepo) Lookup(ctx context.Context, tokenHash string) (*auth.RefreshSession, error) {
	const q = `SELECT ` + refreshSessionColumns + ` FROM auth_refresh_sessions WHERE token_hash = $1`
	row := r.pool.QueryRow(ctx, q, tokenHash)
	var s auth.RefreshSession
	if err := row.Scan(&s.ID, &s.UserID, &s.TokenHash, &s.IssuedAt, &s.ExpiresAt, &s.RevokedAt); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, auth.ErrRefreshNotFound
		}
		return nil, err
	}
	return &s, nil
}

// Revoke is idempotent: it only touches rows not already revoked, and an
// unknown hash simply affects zero rows (no error). This keeps logout and
// reuse-after-rotation handling simple for the application layer.
func (r *RefreshSessionRepo) Revoke(ctx context.Context, tokenHash string) error {
	const q = `UPDATE auth_refresh_sessions SET revoked_at = NOW() WHERE token_hash = $1 AND revoked_at IS NULL`
	_, err := r.pool.Exec(ctx, q, tokenHash)
	return err
}

func (r *RefreshSessionRepo) RevokeAllForUser(ctx context.Context, userID uuid.UUID) (int64, error) {
	const q = `UPDATE auth_refresh_sessions SET revoked_at = NOW() WHERE user_id = $1 AND revoked_at IS NULL`
	tag, err := r.pool.Exec(ctx, q, userID)
	if err != nil {
		return 0, err
	}
	return tag.RowsAffected(), nil
}
