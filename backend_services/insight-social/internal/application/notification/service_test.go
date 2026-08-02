package notification

import (
	"context"
	"testing"

	"github.com/google/uuid"

	domnotif "github.com/konoha-labs/insight-social/internal/domain/notification"
)

type fakeRepo struct {
	lastFilter domnotif.ListFilter
	unread     int64
	markedOne  bool
	markedAll  int64
}

func (f *fakeRepo) Insert(context.Context, *domnotif.Notification) (bool, error) { return true, nil }
func (f *fakeRepo) List(_ context.Context, flt domnotif.ListFilter) (domnotif.Page, error) {
	f.lastFilter = flt
	return domnotif.Page{}, nil
}
func (f *fakeRepo) UnreadCount(context.Context, uuid.UUID) (int64, error) { return f.unread, nil }
func (f *fakeRepo) MarkRead(context.Context, uuid.UUID, uuid.UUID) (bool, error) {
	return f.markedOne, nil
}
func (f *fakeRepo) MarkAllRead(context.Context, uuid.UUID) (int64, error) { return f.markedAll, nil }

func TestList_ClampsLimit(t *testing.T) {
	f := &fakeRepo{}
	svc := New(f)
	if _, err := svc.List(context.Background(), uuid.New(), 0, "cur", true); err != nil {
		t.Fatal(err)
	}
	if f.lastFilter.Limit != defaultLimit {
		t.Fatalf("limit 0 must clamp to default, got %d", f.lastFilter.Limit)
	}
	if !f.lastFilter.UnreadOnly || f.lastFilter.Cursor != "cur" {
		t.Fatal("filter must forward unread_only + cursor")
	}
	if _, err := svc.List(context.Background(), uuid.New(), 999, "", false); err != nil {
		t.Fatal(err)
	}
	if f.lastFilter.Limit != maxLimit {
		t.Fatalf("limit 999 must clamp to max %d, got %d", maxLimit, f.lastFilter.Limit)
	}
}

func TestMarkRead_ReturnsRefreshedUnread(t *testing.T) {
	f := &fakeRepo{markedOne: true, unread: 4}
	svc := New(f)
	changed, unread, err := svc.MarkRead(context.Background(), uuid.New(), uuid.New())
	if err != nil || !changed || unread != 4 {
		t.Fatalf("mark read must return changed + refreshed unread: %v %d %v", changed, unread, err)
	}
}

func TestMarkAllRead_ReturnsMarkedAndUnread(t *testing.T) {
	f := &fakeRepo{markedAll: 7, unread: 0}
	svc := New(f)
	marked, unread, err := svc.MarkAllRead(context.Background(), uuid.New())
	if err != nil || marked != 7 || unread != 0 {
		t.Fatalf("mark-all must return count changed + refreshed unread: %d %d %v", marked, unread, err)
	}
}
