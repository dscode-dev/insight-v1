package notification

import (
	"context"

	"github.com/google/uuid"
)

// ListFilter scopes a keyset-paginated per-user listing.
type ListFilter struct {
	UserID     uuid.UUID
	Limit      int
	Cursor     string
	UnreadOnly bool
}

// Page is the repo return shape for List.
type Page struct {
	Notifications []*Notification
	NextCursor    string
}

type Repository interface {
	// Insert persists a notification, DEDUPED on (user_id, dedup_key) via ON
	// CONFLICT DO NOTHING. Returns (inserted=false, nil) when a duplicate was
	// suppressed — never an error, so producers stay idempotent.
	Insert(ctx context.Context, n *Notification) (inserted bool, err error)
	// List returns a keyset page (created_at, id) DESC for the user.
	List(ctx context.Context, f ListFilter) (Page, error)
	// UnreadCount returns the number of unread notifications for the user.
	UnreadCount(ctx context.Context, userID uuid.UUID) (int64, error)
	// MarkRead sets read_at for ONE notification, scoped to the recipient and
	// only when currently unread. Returns changed=false if already read / not
	// owned / not found (idempotent).
	MarkRead(ctx context.Context, userID, id uuid.UUID) (changed bool, err error)
	// MarkAllRead sets read_at for ALL unread notifications of the user
	// (WHERE user_id=? AND read_at IS NULL). Returns the number changed.
	MarkAllRead(ctx context.Context, userID uuid.UUID) (marked int64, err error)
}
