// FEATURE-NOTIFICATIONS-V1 Stage 2 — orchestrator proofs: Gateway-owned DTO
// (icon/color/capabilities), deep-link validation that drops the action but
// keeps the notification (never breaks the list), honest partial when the
// unread count fails, and the few-seconds unread cache with invalidation.
package notificationbff

import (
	"context"
	"errors"
	"testing"
	"time"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"github.com/prometheus/client_golang/prometheus"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type fakeSocial struct {
	page      *socialv1.ListNotificationsResponse
	listErr   error
	unread    int64
	unreadErr error
}

func (f *fakeSocial) List(context.Context, string, string, int32, bool) (*socialv1.ListNotificationsResponse, error) {
	return f.page, f.listErr
}
func (f *fakeSocial) UnreadCount(context.Context, string) (int64, error) { return f.unread, f.unreadErr }
func (f *fakeSocial) MarkRead(context.Context, string, string) (*socialv1.MarkReadResponse, error) {
	return &socialv1.MarkReadResponse{Changed: true, UnreadCount: f.unread}, nil
}
func (f *fakeSocial) MarkAllRead(context.Context, string) (*socialv1.MarkAllReadResponse, error) {
	return &socialv1.MarkAllReadResponse{Marked: 3, UnreadCount: 0}, nil
}

func testAgg(f SocialGateway) *Aggregator { return NewAggregator(f, NewMetrics(prometheus.NewRegistry())) }

func notif(id string, typ socialv1.NotificationType, deeplink string, read bool) *socialv1.Notification {
	st := socialv1.NotificationStatus_NOTIFICATION_STATUS_UNREAD
	if read {
		st = socialv1.NotificationStatus_NOTIFICATION_STATUS_READ
	}
	return &socialv1.Notification{
		Id: id, Type: typ, Priority: socialv1.NotificationPriority_NOTIFICATION_PRIORITY_NORMAL,
		Title: "T", Body: "B", Deeplink: deeplink, Status: st, PayloadJson: "{}",
		CreatedAt: timestamppb.New(time.Now()),
	}
}

// ---- DTO mapping ----

func TestDTO_IconColorAndCapabilities(t *testing.T) {
	d := notificationToDTO(notif("n1", socialv1.NotificationType_NOTIFICATION_TYPE_REACTION, "/discussion/d1", false))
	if d.Type != "reaction" || d.Icon != "favorite" || d.Color == "" {
		t.Fatalf("gateway must own icon/color: %+v", d)
	}
	if !d.Capabilities.CanOpen || !d.Capabilities.CanMarkRead {
		t.Fatal("valid deeplink + unread → can_open + can_mark_read")
	}
	if d.Capabilities.CanDelete || d.Capabilities.CanArchive || d.Capabilities.CanShare {
		t.Fatal("delete/archive/share are false in V1")
	}
	// A read notification cannot be marked read again.
	if notificationToDTO(notif("n2", socialv1.NotificationType_NOTIFICATION_TYPE_MENTION, "/users/u1", true)).Capabilities.CanMarkRead {
		t.Fatal("read notification must not offer mark_read")
	}
}

func TestDTO_InvalidDeepLinkDropsActionKeepsNotification(t *testing.T) {
	// Malformed / unknown route → deeplink "" + can_open false, but the DTO
	// still exists (the notification is kept, the list is not broken).
	for _, bad := range []string{"", "/evil/x", "not-a-path", "/hub/community"} {
		d := notificationToDTO(notif("n", socialv1.NotificationType_NOTIFICATION_TYPE_SYSTEM, bad, false))
		if d.DeepLink != "" || d.Capabilities.CanOpen {
			t.Fatalf("invalid deeplink %q must drop the action: %+v", bad, d)
		}
		if d.ID != "n" {
			t.Fatal("notification must be kept")
		}
	}
	// Valid ones survive.
	for _, ok := range []string{"/users/u1", "/hub/community/c1", "/discussion/d1", "/post/p1"} {
		if validDeepLink(ok) != ok {
			t.Fatalf("valid link rejected: %s", ok)
		}
	}
}

// ---- list aggregate ----

func TestList_HasMoreAndUnreadEmbedded(t *testing.T) {
	nc := "cur2"
	f := &fakeSocial{
		page: &socialv1.ListNotificationsResponse{
			Notifications: []*socialv1.Notification{
				notif("n1", socialv1.NotificationType_NOTIFICATION_TYPE_COMMUNITY_JOIN, "/hub/community/c1", false),
			},
			NextCursor: &nc,
		},
		unread: 7,
	}
	resp, err := testAgg(f).List(context.Background(), "u1", "", 20, false, -1, func(int64) {})
	if err != nil {
		t.Fatal(err)
	}
	if !resp.HasMore || resp.NextCursor != "cur2" {
		t.Fatal("has_more + next_cursor must be explicit (client never infers)")
	}
	if resp.UnreadCount != 7 {
		t.Fatalf("unread embedded in list, got %d", resp.UnreadCount)
	}
	if resp.Partial {
		t.Fatal("healthy fan-out must not be partial")
	}
}

func TestList_UnreadFailureIsPartialNotError(t *testing.T) {
	f := &fakeSocial{
		page:      &socialv1.ListNotificationsResponse{Notifications: []*socialv1.Notification{notif("n1", socialv1.NotificationType_NOTIFICATION_TYPE_SYSTEM, "", true)}},
		unreadErr: errors.New("count down"),
	}
	resp, err := testAgg(f).List(context.Background(), "u1", "", 20, false, -1, func(int64) {})
	if err != nil {
		t.Fatal("list core loaded → no hard error")
	}
	if !resp.Partial || len(resp.FailedSections) == 0 || resp.FailedSections[0] != "unread_count" {
		t.Fatalf("unread failure must be honest partial: %+v", resp)
	}
	if len(resp.Items) != 1 {
		t.Fatal("the list itself must still return")
	}
}

func TestList_CachedUnreadSkipsFanout(t *testing.T) {
	f := &fakeSocial{page: &socialv1.ListNotificationsResponse{}, unreadErr: errors.New("should not be called")}
	resp, err := testAgg(f).List(context.Background(), "u1", "", 20, false, 42, nil)
	if err != nil {
		t.Fatal(err)
	}
	if resp.UnreadCount != 42 || resp.Partial {
		t.Fatalf("cache hit must supply unread without fan-out: %+v", resp)
	}
}

func TestList_CoreFailureIsError(t *testing.T) {
	f := &fakeSocial{listErr: errors.New("social down")}
	if _, err := testAgg(f).List(context.Background(), "u1", "", 20, false, -1, nil); err == nil {
		t.Fatal("list core failure must surface as the request error")
	}
}

// ---- unread cache ----

func TestUnreadCache_TTLAndInvalidate(t *testing.T) {
	c := NewUnreadCache(5*time.Second, 10)
	now := time.Now()
	c.now = func() time.Time { return now }

	c.Set("u1", 9)
	if v, hit := c.Get("u1"); !hit || v != 9 {
		t.Fatal("expected hit")
	}
	// Mutation invalidates immediately (badge never inconsistent).
	c.Invalidate("u1")
	if _, hit := c.Get("u1"); hit {
		t.Fatal("invalidate must drop the entry")
	}
	// TTL expiry.
	c.Set("u2", 3)
	now = now.Add(6 * time.Second)
	if _, hit := c.Get("u2"); hit {
		t.Fatal("expired entry must miss")
	}
}
