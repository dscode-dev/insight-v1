// Package preferencesrepo — pgx-backed UserPreferences repository.
//
// Lazy creation: Get uses an INSERT ... ON CONFLICT DO NOTHING +
// RETURNING idiom so the row is created on first read with all the
// schema defaults. No client coordination required.
//
// Update: single UPSERT-style statement using COALESCE($new, current)
// so unset fields stay at their previous value without read-modify-
// write races.
package preferencesrepo

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgerrcode"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	dompreferences "github.com/konoha-labs/insight-social/internal/domain/preferences"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres"
)

type Repository struct {
	pool postgres.Pool
}

func New(pool postgres.Pool) *Repository {
	return &Repository{pool: pool}
}

// Get: lazy upsert. The CTE inserts the default row when missing,
// then SELECTs the persisted row whether it was new or pre-existing.
// Pattern matches reactionrepo.React (single round-trip, no
// client-side "exists?" check).
const getSQL = `
WITH ins AS (
    INSERT INTO user_preferences (user_id)
    VALUES ($1)
    ON CONFLICT (user_id) DO NOTHING
    RETURNING user_id, locale, push_enabled, email_enabled, digest_frequency, updated_at
)
SELECT user_id, locale, push_enabled, email_enabled, digest_frequency, updated_at FROM ins
UNION ALL
SELECT user_id, locale, push_enabled, email_enabled, digest_frequency, updated_at
  FROM user_preferences
 WHERE user_id = $1 AND NOT EXISTS (SELECT 1 FROM ins)
LIMIT 1
`

func (r *Repository) Get(ctx context.Context, userID uuid.UUID) (dompreferences.Preferences, error) {
	p, err := scanPreferences(r.pool.QueryRow(ctx, getSQL, userID))
	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == pgerrcode.ForeignKeyViolation {
			// user_id doesn't reference a real users row. Same posture
			// as reactions: surface as "user not found" upstream.
			return dompreferences.Preferences{}, fmt.Errorf("preferencesrepo get: user not found: %w", err)
		}
		return dompreferences.Preferences{}, fmt.Errorf("preferencesrepo get: %w", err)
	}
	return p, nil
}

// Update: ensure the row exists then patch. Two-step via CTE so the
// caller of a user who hasn't read prefs yet still gets a sensible
// upserted row.
const updateSQL = `
WITH ins AS (
    INSERT INTO user_preferences (user_id)
    VALUES ($1)
    ON CONFLICT (user_id) DO NOTHING
), upd AS (
    UPDATE user_preferences
       SET locale           = COALESCE($2, locale),
           push_enabled     = COALESCE($3, push_enabled),
           email_enabled    = COALESCE($4, email_enabled),
           digest_frequency = COALESCE($5, digest_frequency),
           updated_at       = NOW()
     WHERE user_id = $1
    RETURNING user_id, locale, push_enabled, email_enabled, digest_frequency, updated_at
)
SELECT user_id, locale, push_enabled, email_enabled, digest_frequency, updated_at FROM upd
`

func (r *Repository) Update(ctx context.Context, userID uuid.UUID, patch dompreferences.Update) (dompreferences.Preferences, error) {
	p, err := scanPreferences(r.pool.QueryRow(ctx, updateSQL, userID,
		patch.Locale, patch.PushEnabled, patch.EmailEnabled, patch.DigestFrequency))
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			// Update RETURNING produced nothing → row wasn't created.
			// Most likely cause: user_id doesn't reference a real
			// users row (FK on the insert would have surfaced as
			// PgError but the CTE swallows it via DO NOTHING).
			return dompreferences.Preferences{}, fmt.Errorf("preferencesrepo update: user not found")
		}
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == pgerrcode.CheckViolation {
			return dompreferences.Preferences{}, dompreferences.ErrInvalidDigestFrequency
		}
		return dompreferences.Preferences{}, fmt.Errorf("preferencesrepo update: %w", err)
	}
	return p, nil
}

type rowScanner interface {
	Scan(dest ...any) error
}

func scanPreferences(r rowScanner) (dompreferences.Preferences, error) {
	var (
		p         dompreferences.Preferences
		updatedAt time.Time
	)
	err := r.Scan(&p.UserID, &p.Locale, &p.PushEnabled, &p.EmailEnabled,
		&p.DigestFrequency, &updatedAt)
	if err != nil {
		return p, err
	}
	p.UpdatedAt = updatedAt.UTC()
	return p, nil
}
