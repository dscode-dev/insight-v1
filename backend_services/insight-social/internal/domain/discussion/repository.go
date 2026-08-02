package discussion

import (
	"context"

	"github.com/google/uuid"
)

// ListFilter for ListForCommunity.
type ListFilter struct {
	CommunityID uuid.UUID
	Limit       int
	Cursor      string
}

type ListPage struct {
	Discussions []*Discussion
	NextCursor  string
}

// MessageListFilter for ListMessages on a discussion. Pagination
// chronological ASC (created_at ASC, id ASC) so message order reads
// naturally in the UI — the cursor still encodes (created_at, id).
type MessageListFilter struct {
	DiscussionID uuid.UUID
	Limit        int
	Cursor       string
}

type MessageListPage struct {
	Messages   []*Message
	NextCursor string
}

type Repository interface {
	// Discussions
	Insert(ctx context.Context, d *Discussion) error
	GetByID(ctx context.Context, id uuid.UUID) (*Discussion, error)
	ListForCommunity(ctx context.Context, f ListFilter) (ListPage, error)

	// Messages
	InsertMessage(ctx context.Context, m *Message) error
	ListMessages(ctx context.Context, f MessageListFilter) (MessageListPage, error)
}
