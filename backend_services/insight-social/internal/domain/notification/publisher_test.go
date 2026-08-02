package notification

import (
	"context"
	"testing"

	"github.com/google/uuid"
)

// fakeRepo records inserts and simulates dedup.
type fakeRepo struct {
	seen      map[string]bool // user|dedup
	inserted  int
}

func newFakeRepo() *fakeRepo { return &fakeRepo{seen: map[string]bool{}} }

func (f *fakeRepo) Insert(_ context.Context, n *Notification) (bool, error) {
	k := n.UserID().String() + "|" + n.DedupKey()
	if f.seen[k] {
		return false, nil // dedup suppressed
	}
	f.seen[k] = true
	f.inserted++
	return true, nil
}
func (f *fakeRepo) List(context.Context, ListFilter) (Page, error)            { return Page{}, nil }
func (f *fakeRepo) UnreadCount(context.Context, uuid.UUID) (int64, error)     { return 0, nil }
func (f *fakeRepo) MarkRead(context.Context, uuid.UUID, uuid.UUID) (bool, error) { return false, nil }
func (f *fakeRepo) MarkAllRead(context.Context, uuid.UUID) (int64, error)     { return 0, nil }

func TestDirectPublisher_DedupNoCascade(t *testing.T) {
	repo := newFakeRepo()
	pub := NewDirectPublisher(repo)
	u := uuid.New()
	key := DedupKey("reaction", "discussion", "842", "user", "18")

	mk := func() *Notification {
		n, _ := New(u, TypeReaction, PriorityNormal, "Nova reação", "", Target{}, nil, key)
		return n
	}

	// First publish delivers.
	delivered, err := pub.Publish(context.Background(), mk())
	if err != nil || !delivered {
		t.Fatalf("first publish must deliver: %v %v", delivered, err)
	}
	// Same event (same dedup key) published again → suppressed, no error.
	// Models "one user action → at most one notification per recipient".
	delivered, err = pub.Publish(context.Background(), mk())
	if err != nil || delivered {
		t.Fatalf("duplicate must be suppressed (delivered=false, no error): %v %v", delivered, err)
	}
	if repo.inserted != 1 {
		t.Fatalf("exactly one row must persist, got %d", repo.inserted)
	}
}
