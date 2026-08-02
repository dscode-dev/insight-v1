// Package userrepo is the pgx-backed implementation of
// domain/user.Repository.
//
// Mapping rules pgx ⇄ domain:
//   - tier varchar  ⇄  user.Tier via ParseTier / Tier.String
//   - timestamptz   ⇄  time.Time (UTC normalised at Reconstitute time)
//   - UUID v7 etc.  ⇄  github.com/google/uuid via pgx-uuid bridge
//
// Errors translated:
//   - pgx.ErrNoRows                ⇒ user.ErrNotFound
//   - pgconn.PgError code "23505"  ⇒ user.ErrUsernameTaken (unique on username)
package userrepo

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgerrcode"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	domuser "github.com/konoha-labs/insight-social/internal/domain/user"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres"
)

type Repository struct {
	pool postgres.Pool
}

func New(pool postgres.Pool) *Repository {
	return &Repository{pool: pool}
}

// ---- writes ----

const insertSQL = `
INSERT INTO users (
    id, username, display_name, initials, accent_color,
    reputation, tier, created_at, avatar_url
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
`

func (r *Repository) Insert(ctx context.Context, u *domuser.User) error {
	var avatarArg any
	if u.AvatarURL() != "" {
		avatarArg = u.AvatarURL()
	} // else nil → NULL
	_, err := r.pool.Exec(ctx, insertSQL,
		u.ID(), u.Username(), u.DisplayName(), u.Initials(), u.AccentColor(),
		u.Reputation(), u.Tier().String(), u.CreatedAt(), avatarArg,
	)
	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == pgerrcode.UniqueViolation {
			return domuser.ErrUsernameTaken
		}
		return fmt.Errorf("userrepo insert: %w", err)
	}
	return nil
}

const updateAccentSQL = `
UPDATE users
   SET accent_color = $2
 WHERE id = $1
RETURNING id, username, display_name, initials, accent_color,
          reputation, tier, created_at, avatar_url
`

func (r *Repository) UpdateAccent(ctx context.Context, id uuid.UUID, accentColor string) (*domuser.User, error) {
	row := r.pool.QueryRow(ctx, updateAccentSQL, id, accentColor)
	return scanUser(row)
}

// avatarVersionedExpr appends `?v=<epoch>` to the stored avatar URL when (and
// only when) the avatar has an update timestamp — AZTECA-IDENTITY-B versioned
// avatars. The NULL guard keeps legacy rows (and test fixtures) emitting the
// bare URL, so behaviour is unchanged until the first upload stamps the column.
const avatarVersionedExpr = `CASE
    WHEN avatar_url IS NOT NULL AND avatar_url <> '' AND avatar_updated_at IS NOT NULL
    THEN avatar_url || '?v=' || (extract(epoch FROM avatar_updated_at)::bigint)::text
    ELSE avatar_url END`

// Sprint C — UpdateAvatar. Empty string sets the column to NULL so
// readers see "no avatar" via the conventional IS NULL check.
// AZTECA-IDENTITY-B: also stamp avatar_updated_at so the URL versions.
const updateAvatarSQL = `
UPDATE users
   SET avatar_url = NULLIF($2, ''), avatar_updated_at = NOW()
 WHERE id = $1
RETURNING id, username, display_name, initials, accent_color,
          reputation, tier, created_at, ` + avatarVersionedExpr + `
`

func (r *Repository) UpdateAvatar(ctx context.Context, id uuid.UUID, avatarURL string) (*domuser.User, error) {
	return scanUser(r.pool.QueryRow(ctx, updateAvatarSQL, id, avatarURL))
}

// ---- reads ----

const selectByIDSQL = `
SELECT id, username, display_name, initials, accent_color,
       reputation, tier, created_at, ` + avatarVersionedExpr + `
  FROM users
 WHERE id = $1
`

func (r *Repository) GetByID(ctx context.Context, id uuid.UUID) (*domuser.User, error) {
	return scanUser(r.pool.QueryRow(ctx, selectByIDSQL, id))
}

const selectByUsernameSQL = `
SELECT id, username, display_name, initials, accent_color,
       reputation, tier, created_at, avatar_url
  FROM users
 WHERE username = $1
`

func (r *Repository) GetByUsername(ctx context.Context, username string) (*domuser.User, error) {
	return scanUser(r.pool.QueryRow(ctx, selectByUsernameSQL, username))
}

const selectByIDsSQL = `
SELECT id, username, display_name, initials, accent_color,
       reputation, tier, created_at, ` + avatarVersionedExpr + `
  FROM users
 WHERE id = ANY($1)
`

func (r *Repository) List(ctx context.Context, ids []uuid.UUID) ([]*domuser.User, error) {
	rows, err := r.pool.Query(ctx, selectByIDsSQL, ids)
	if err != nil {
		return nil, fmt.Errorf("userrepo list: %w", err)
	}
	defer rows.Close()

	out := make([]*domuser.User, 0, len(ids))
	for rows.Next() {
		u, err := scanUser(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, u)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("userrepo list rows: %w", err)
	}
	return out, nil
}

// Stats — single round-trip with scalar subqueries. Cheaper than 5
// separate counts; postgres plans each subselect against its index.
// Matches the legacy stats endpoint shape (counts only; no time
// windowing — leaderboards are someone else's problem).
const statsSQL = `
SELECT
    (SELECT COUNT(*) FROM signals          WHERE author_id = $1)                                              AS signals_sent,
    (SELECT COUNT(*) FROM reputation_events WHERE user_id  = $1 AND kind = 'signal_validated')                AS signals_validated,
    (SELECT COUNT(*) FROM reputation_events WHERE user_id  = $1 AND kind = 'signal_flagged')                  AS signals_flagged,
    (SELECT COUNT(DISTINCT match_id) FROM signals WHERE author_id = $1 AND match_id IS NOT NULL)              AS matches_followed,
    (SELECT COUNT(*) FROM community_members WHERE user_id = $1)                                               AS communities_joined
`

func (r *Repository) Stats(ctx context.Context, id uuid.UUID) (domuser.Stats, error) {
	var s domuser.Stats
	s.UserID = id
	err := r.pool.QueryRow(ctx, statsSQL, id).Scan(
		&s.SignalsSent, &s.SignalsValidated, &s.SignalsFlagged,
		&s.MatchesFollowed, &s.CommunitiesJoined,
	)
	if err != nil {
		return domuser.Stats{}, fmt.Errorf("userrepo stats: %w", err)
	}
	if s.SignalsSent > 0 {
		s.Accuracy = float64(s.SignalsValidated) / float64(s.SignalsSent)
	}
	return s, nil
}

// ---- helpers ----

// rowScanner abstracts over *pgx.Row and pgx.Rows so scanUser works
// for both single-row and multi-row paths without duplication.
type rowScanner interface {
	Scan(dest ...any) error
}

func scanUser(r rowScanner) (*domuser.User, error) {
	var (
		id          uuid.UUID
		username    string
		displayName string
		initials    string
		accentColor string
		reputation  int
		tierStr     string
		createdAt   time.Time
		avatarURL   *string // NULL when no avatar uploaded
	)
	err := r.Scan(&id, &username, &displayName, &initials, &accentColor,
		&reputation, &tierStr, &createdAt, &avatarURL)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, domuser.ErrNotFound
		}
		return nil, fmt.Errorf("userrepo scan: %w", err)
	}
	var av string
	if avatarURL != nil {
		av = *avatarURL
	}
	return domuser.Reconstitute(id, username, displayName, initials, accentColor,
		reputation, domuser.ParseTier(tierStr), createdAt.UTC(), av), nil
}
