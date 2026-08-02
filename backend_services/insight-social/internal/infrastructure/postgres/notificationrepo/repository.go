// Package notificationrepo is the pgx-backed Notification repository.
//
// Pagination is keyset on (created_at DESC, id DESC) — no offset. Dedup is
// enforced by the UNIQUE (user_id, dedup_key) constraint via ON CONFLICT DO
// NOTHING. Unread count + unread-only listing ride the partial index
// ix_notifications_unread.
package notificationrepo

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	domnotif "github.com/konoha-labs/insight-social/internal/domain/notification"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres"
)

type Repository struct {
	pool postgres.Pool
}

func New(pool postgres.Pool) *Repository { return &Repository{pool: pool} }

// ---- write (deduped) ----

const insertSQL = `
INSERT INTO notifications (
    id, user_id, type, priority, title, body,
    target_type, target_id, deeplink, payload, dedup_key, created_at
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
ON CONFLICT (user_id, dedup_key) DO NOTHING
RETURNING id
`

func (r *Repository) Insert(ctx context.Context, n *domnotif.Notification) (bool, error) {
	t := n.Target()
	var targetID any
	if t.ID != nil {
		targetID = *t.ID
	}
	payload := n.Payload()
	if len(payload) == 0 {
		payload = json.RawMessage(`{}`)
	}
	var id uuid.UUID
	err := r.pool.QueryRow(ctx, insertSQL,
		n.ID(), n.UserID(), n.Type().String(), n.Priority().String(), n.Title(), n.Body(),
		t.Type, targetID, t.DeepLink, []byte(payload), n.DedupKey(), n.CreatedAt(),
	).Scan(&id)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			// ON CONFLICT DO NOTHING suppressed a duplicate — not an error.
			return false, nil
		}
		return false, fmt.Errorf("notificationrepo insert: %w", err)
	}
	return true, nil
}

// ---- reads ----

const selectCols = `
id, user_id, type, priority, title, body,
target_type, target_id, deeplink, payload, dedup_key, created_at, read_at
`

// listSQL: keyset (created_at, id) DESC. $5 (unread_only) narrows to unread.
const listSQL = `
SELECT ` + selectCols + `
  FROM notifications
 WHERE user_id = $1
   AND ($5::boolean IS NOT TRUE OR read_at IS NULL)
   AND ($3::timestamptz IS NULL OR (created_at, id) < ($3, $4))
 ORDER BY created_at DESC, id DESC
 LIMIT $2
`

func (r *Repository) List(ctx context.Context, f domnotif.ListFilter) (domnotif.Page, error) {
	limit := f.Limit
	if limit <= 0 {
		limit = 20
	}
	cur, err := domnotif.DecodeCursor(f.Cursor)
	if err != nil {
		return domnotif.Page{}, err
	}
	var cArg, iArg any
	if cur != nil {
		cArg, iArg = cur.C, cur.I
	}

	rows, err := r.pool.Query(ctx, listSQL, f.UserID, limit+1, cArg, iArg, f.UnreadOnly)
	if err != nil {
		return domnotif.Page{}, fmt.Errorf("notificationrepo list: %w", err)
	}
	defer rows.Close()

	out := make([]*domnotif.Notification, 0, limit+1)
	for rows.Next() {
		n, err := scan(rows)
		if err != nil {
			return domnotif.Page{}, err
		}
		out = append(out, n)
	}
	if err := rows.Err(); err != nil {
		return domnotif.Page{}, fmt.Errorf("notificationrepo list rows: %w", err)
	}

	page := domnotif.Page{Notifications: out}
	if len(out) > limit {
		last := out[limit-1]
		page.Notifications = out[:limit]
		page.NextCursor = domnotif.EncodeCursor(last.CreatedAt(), last.ID())
	}
	return page, nil
}

// UnreadCount rides the partial index ix_notifications_unread. EVOLUTION POINT
// (see PERFORMANCE.md): at very high volume, replace this COUNT with a
// materialized per-user counter or cache.
const unreadCountSQL = `SELECT count(*) FROM notifications WHERE user_id = $1 AND read_at IS NULL`

func (r *Repository) UnreadCount(ctx context.Context, userID uuid.UUID) (int64, error) {
	var n int64
	if err := r.pool.QueryRow(ctx, unreadCountSQL, userID).Scan(&n); err != nil {
		return 0, fmt.Errorf("notificationrepo unread count: %w", err)
	}
	return n, nil
}

// MarkRead: scoped to the recipient AND only when unread (idempotent). The
// WHERE guarantees a user can only mark their OWN notifications.
const markReadSQL = `
UPDATE notifications SET read_at = NOW()
 WHERE id = $2 AND user_id = $1 AND read_at IS NULL
RETURNING id
`

func (r *Repository) MarkRead(ctx context.Context, userID, id uuid.UUID) (bool, error) {
	var got uuid.UUID
	err := r.pool.QueryRow(ctx, markReadSQL, userID, id).Scan(&got)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return false, nil // already read / not owned / not found — no change
		}
		return false, fmt.Errorf("notificationrepo mark read: %w", err)
	}
	return true, nil
}

// MarkAllRead: ONLY the user's unread rows (never a blanket UPDATE). Returns the
// number changed for observability.
const markAllReadSQL = `
UPDATE notifications SET read_at = NOW()
 WHERE user_id = $1 AND read_at IS NULL
`

func (r *Repository) MarkAllRead(ctx context.Context, userID uuid.UUID) (int64, error) {
	tag, err := r.pool.Exec(ctx, markAllReadSQL, userID)
	if err != nil {
		return 0, fmt.Errorf("notificationrepo mark all read: %w", err)
	}
	return tag.RowsAffected(), nil
}

// ---- scan ----

type rowScanner interface {
	Scan(dest ...any) error
}

func scan(r rowScanner) (*domnotif.Notification, error) {
	var (
		id        uuid.UUID
		userID    uuid.UUID
		typeStr   string
		prioStr   string
		title     string
		body      string
		targetTy  string
		targetID  *uuid.UUID
		deeplink  string
		payload   []byte
		dedupKey  string
		createdAt time.Time
		readAt    *time.Time
	)
	if err := r.Scan(&id, &userID, &typeStr, &prioStr, &title, &body,
		&targetTy, &targetID, &deeplink, &payload, &dedupKey, &createdAt, &readAt); err != nil {
		return nil, fmt.Errorf("notificationrepo scan: %w", err)
	}
	var ra *time.Time
	if readAt != nil {
		u := readAt.UTC()
		ra = &u
	}
	return domnotif.Reconstitute(
		id, userID, domnotif.ParseType(typeStr), domnotif.ParsePriority(prioStr), title, body,
		domnotif.Target{Type: targetTy, ID: targetID, DeepLink: deeplink},
		json.RawMessage(payload), dedupKey, createdAt.UTC(), ra,
	), nil
}
