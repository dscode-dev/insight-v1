// FEATURE-NOTIFICATIONS-V1 Stage 2 — Notification Center orchestrator.
//
// The list endpoint is an aggregate: the notification page (CRITICAL — its
// failure is the request's error) plus the unread count (non-critical — its
// failure degrades to partial=true + failed_sections, never hidden). Both share
// the inbound context so a client disconnect / timeout cancels the fan-out.
package notificationbff

import (
	"context"
	"sync"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
)

type Aggregator struct {
	social  SocialGateway
	metrics *Metrics
}

func NewAggregator(social SocialGateway, m *Metrics) *Aggregator {
	return &Aggregator{social: social, metrics: m}
}

// List composes the Notification Center page for viewer, requesting limit items.
// cachedUnread (>=0) short-circuits the unread fan-out on a cache hit. On a
// miss (cachedUnread<0) it fetches the count in parallel and calls storeUnread
// with the fresh value.
func (a *Aggregator) List(ctx context.Context, userID, cursor string, limit int, unreadOnly bool,
	cachedUnread int64, storeUnread func(int64)) (ListResponse, error) {
	var (
		wg        sync.WaitGroup
		page      *socialv1.ListNotificationsResponse
		listErr   error
		unread    int64
		unreadErr error
	)

	wg.Add(1)
	go func() {
		defer wg.Done()
		page, listErr = a.social.List(ctx, userID, cursor, int32(limit), unreadOnly)
	}()

	needUnread := cachedUnread < 0
	if needUnread {
		wg.Add(1)
		go func() {
			defer wg.Done()
			unread, unreadErr = a.social.UnreadCount(ctx, userID)
		}()
	}
	wg.Wait()

	// Critical: the page.
	if listErr != nil {
		return ListResponse{}, listErr
	}

	out := ListResponse{Items: make([]Notification, 0, len(page.Notifications))}
	for _, n := range page.Notifications {
		out.Items = append(out.Items, notificationToDTO(n))
	}
	if page.NextCursor != nil && *page.NextCursor != "" {
		out.NextCursor = *page.NextCursor
		out.HasMore = true
	}

	// Non-critical: unread count.
	switch {
	case !needUnread:
		out.UnreadCount = cachedUnread
	case unreadErr != nil:
		out.Partial = true
		out.FailedSections = append(out.FailedSections, "unread_count")
		a.metrics.partialInc()
	default:
		out.UnreadCount = unread
		if storeUnread != nil {
			storeUnread(unread)
		}
	}
	return out, nil
}
