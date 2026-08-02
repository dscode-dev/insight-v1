// Package notification is the application service for the Notification domain.
//
// Read/mark use cases for the Gateway (List / UnreadCount / MarkRead /
// MarkAllRead). Creation is NOT here — it flows through the domain Publisher
// seam (single point of publication) used by event producers.
package notification

import (
	"context"

	"github.com/google/uuid"

	domnotif "github.com/konoha-labs/insight-social/internal/domain/notification"
)

const (
	defaultLimit = 20
	maxLimit     = 50
)

type Service struct {
	repo domnotif.Repository
}

func New(repo domnotif.Repository) *Service { return &Service{repo: repo} }

func clampLimit(n int) int {
	if n <= 0 {
		return defaultLimit
	}
	if n > maxLimit {
		return maxLimit
	}
	return n
}

func (s *Service) List(ctx context.Context, userID uuid.UUID, limit int, cursor string, unreadOnly bool) (domnotif.Page, error) {
	return s.repo.List(ctx, domnotif.ListFilter{
		UserID:     userID,
		Limit:      clampLimit(limit),
		Cursor:     cursor,
		UnreadOnly: unreadOnly,
	})
}

func (s *Service) UnreadCount(ctx context.Context, userID uuid.UUID) (int64, error) {
	return s.repo.UnreadCount(ctx, userID)
}

// MarkRead marks one notification read and returns whether it changed plus the
// refreshed unread count (so the caller's badge is never inconsistent).
func (s *Service) MarkRead(ctx context.Context, userID, id uuid.UUID) (changed bool, unread int64, err error) {
	changed, err = s.repo.MarkRead(ctx, userID, id)
	if err != nil {
		return false, 0, err
	}
	unread, err = s.repo.UnreadCount(ctx, userID)
	return changed, unread, err
}

// MarkAllRead marks all the user's unread notifications and returns how many
// changed plus the refreshed unread count (0 on success).
func (s *Service) MarkAllRead(ctx context.Context, userID uuid.UUID) (marked int64, unread int64, err error) {
	marked, err = s.repo.MarkAllRead(ctx, userID)
	if err != nil {
		return 0, 0, err
	}
	unread, err = s.repo.UnreadCount(ctx, userID)
	return marked, unread, err
}
