// Package notification is the Notification domain — an IMMUTABLE historical
// record of a message delivered to ONE user. Notifications DERIVE from domain
// events; the domain does not own Communities/Posts/Discussions.
//
// Immutability: after New(...), nothing changes except read_at (via MarkRead).
// Status is derived from read_at, never stored — a single source of truth.
package notification

import (
	"encoding/json"
	"strings"
	"time"

	"github.com/google/uuid"
)

// Target is the entity a notification points at, plus the deeplink PERSISTED at
// creation time. The deeplink is stored (not recomputed on read) so old
// notifications stay valid even if the deep-link strategy changes later.
type Target struct {
	Type     string // community|discussion|post|user|"" (system)
	ID       *uuid.UUID
	DeepLink string
}

type Notification struct {
	id        uuid.UUID
	userID    uuid.UUID
	typ       Type
	priority  Priority
	title     string
	body      string
	target    Target
	payload   json.RawMessage
	dedupKey  string
	createdAt time.Time
	readAt    *time.Time // the ONLY mutable field
}

// New constructs a notification for a recipient. Validates the essentials;
// payload defaults to `{}`. Called ONLY through a Publisher (single seam).
func New(userID uuid.UUID, typ Type, priority Priority, title, body string,
	target Target, payload json.RawMessage, dedupKey string) (*Notification, error) {
	if userID == uuid.Nil {
		return nil, ErrInvalidUser
	}
	if !typ.Valid() {
		return nil, ErrInvalidType
	}
	if strings.TrimSpace(title) == "" {
		return nil, ErrEmptyTitle
	}
	if strings.TrimSpace(dedupKey) == "" {
		return nil, ErrEmptyDedupKey
	}
	if priority == PriorityUnspecified {
		priority = PriorityNormal
	}
	if len(payload) == 0 {
		payload = json.RawMessage(`{}`)
	}
	return &Notification{
		id:        uuid.New(),
		userID:    userID,
		typ:       typ,
		priority:  priority,
		title:     title,
		body:      body,
		target:    target,
		payload:   payload,
		dedupKey:  dedupKey,
		createdAt: time.Now().UTC(),
	}, nil
}

// Reconstitute rebuilds from persisted state without validation.
func Reconstitute(id, userID uuid.UUID, typ Type, priority Priority, title, body string,
	target Target, payload json.RawMessage, dedupKey string, createdAt time.Time, readAt *time.Time) *Notification {
	return &Notification{
		id: id, userID: userID, typ: typ, priority: priority, title: title, body: body,
		target: target, payload: payload, dedupKey: dedupKey, createdAt: createdAt, readAt: readAt,
	}
}

// ---- accessors ----
func (n *Notification) ID() uuid.UUID           { return n.id }
func (n *Notification) UserID() uuid.UUID        { return n.userID }
func (n *Notification) Type() Type               { return n.typ }
func (n *Notification) Priority() Priority        { return n.priority }
func (n *Notification) Title() string            { return n.title }
func (n *Notification) Body() string             { return n.body }
func (n *Notification) Target() Target           { return n.target }
func (n *Notification) Payload() json.RawMessage { return n.payload }
func (n *Notification) DedupKey() string         { return n.dedupKey }
func (n *Notification) CreatedAt() time.Time     { return n.createdAt }
func (n *Notification) ReadAt() *time.Time       { return n.readAt }

// Status is DERIVED from read_at — the single source of truth.
func (n *Notification) Status() Status {
	if n.readAt != nil {
		return StatusRead
	}
	return StatusUnread
}

func (n *Notification) IsRead() bool { return n.readAt != nil }
