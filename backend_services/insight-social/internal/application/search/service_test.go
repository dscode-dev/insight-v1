package search

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"

	domsearch "github.com/konoha-labs/insight-social/internal/domain/search"
)

// fakeRepo records calls; returns empty pages.
type fakeRepo struct {
	historyWrites []string
	historyUser   uuid.UUID
	cleared       bool
	lastQ         string
	lastLimit     int
	lastCursor    *domsearch.Cursor
	failHistory   bool
}

func (f *fakeRepo) note(q string, limit int, cur *domsearch.Cursor) {
	f.lastQ, f.lastLimit, f.lastCursor = q, limit, cur
}
func (f *fakeRepo) SearchUsers(_ context.Context, _ uuid.UUID, q string, l int, c *domsearch.Cursor) (domsearch.Page[domsearch.UserResult], error) {
	f.note(q, l, c)
	return domsearch.Page[domsearch.UserResult]{}, nil
}
func (f *fakeRepo) SearchAgents(_ context.Context, q string, l int, c *domsearch.Cursor) (domsearch.Page[domsearch.AgentResult], error) {
	f.note(q, l, c)
	return domsearch.Page[domsearch.AgentResult]{}, nil
}
func (f *fakeRepo) SearchCommunities(_ context.Context, q string, l int, c *domsearch.Cursor) (domsearch.Page[domsearch.CommunityResult], error) {
	f.note(q, l, c)
	return domsearch.Page[domsearch.CommunityResult]{}, nil
}
func (f *fakeRepo) SearchCompetitions(_ context.Context, q string, l int, c *domsearch.Cursor) (domsearch.Page[domsearch.CompetitionResult], error) {
	f.note(q, l, c)
	return domsearch.Page[domsearch.CompetitionResult]{}, nil
}
func (f *fakeRepo) SearchMatches(_ context.Context, q string, l int, c *domsearch.Cursor) (domsearch.Page[domsearch.MatchResult], error) {
	f.note(q, l, c)
	return domsearch.Page[domsearch.MatchResult]{}, nil
}
func (f *fakeRepo) SearchPosts(_ context.Context, q string, l int, c *domsearch.Cursor) (domsearch.Page[domsearch.PostResult], error) {
	f.note(q, l, c)
	return domsearch.Page[domsearch.PostResult]{}, nil
}
func (f *fakeRepo) RecordHistory(_ context.Context, u uuid.UUID, q string) error {
	if f.failHistory {
		return errors.New("history down")
	}
	f.historyUser = u
	f.historyWrites = append(f.historyWrites, q)
	return nil
}
func (f *fakeRepo) History(context.Context, uuid.UUID, int) ([]domsearch.HistoryEntry, error) {
	return nil, nil
}
func (f *fakeRepo) ClearHistory(context.Context, uuid.UUID) error { f.cleared = true; return nil }

func TestValidationRejectsBeforeRepo(t *testing.T) {
	repo := &fakeRepo{}
	svc := New(repo)
	if _, err := svc.Users(context.Background(), uuid.New(), "a", 10, ""); err != domsearch.ErrQueryTooShort {
		t.Fatalf("short query must be rejected pre-repo, got %v", err)
	}
	if repo.lastQ != "" {
		t.Fatal("repo must not be called on invalid query")
	}
	// Cross-category cursor rejected pre-repo.
	badCur := domsearch.Cursor{Cat: "posts", B: 0, S1: "1", ID: "x"}.Encode()
	if _, err := svc.Users(context.Background(), uuid.New(), "neymar", 10, badCur); err != domsearch.ErrCursorCategory {
		t.Fatalf("cross-category cursor must be rejected, got %v", err)
	}
}

func TestNormalizationAndClampReachRepo(t *testing.T) {
	repo := &fakeRepo{}
	svc := New(repo)
	if _, err := svc.Posts(context.Background(), uuid.New(), "  Fla   MENGO ", 999, ""); err != nil {
		t.Fatal(err)
	}
	if repo.lastQ != "fla mengo" {
		t.Fatalf("normalized query must reach repo, got %q", repo.lastQ)
	}
	if repo.lastLimit != domsearch.MaxLimit {
		t.Fatalf("limit must be clamped, got %d", repo.lastLimit)
	}
}

func TestHistoryOnlyOnFirstPageAndBestEffort(t *testing.T) {
	repo := &fakeRepo{}
	svc := New(repo)
	viewer := uuid.New()

	// First page → history recorded (normalized).
	if _, err := svc.Agents(context.Background(), viewer, " Ninja ", 10, ""); err != nil {
		t.Fatal(err)
	}
	if len(repo.historyWrites) != 1 || repo.historyWrites[0] != "ninja" || repo.historyUser != viewer {
		t.Fatalf("history must record normalized first-page query: %+v", repo.historyWrites)
	}

	// Paginating (cursor present) → NOT a new search, no history write.
	cur := domsearch.Cursor{Cat: "agents", B: 1, S1: "Ninja", ID: uuid.NewString()}.Encode()
	if _, err := svc.Agents(context.Background(), viewer, "ninja", 10, cur); err != nil {
		t.Fatal(err)
	}
	if len(repo.historyWrites) != 1 {
		t.Fatal("pagination must not re-record history")
	}

	// History failure never fails the search.
	repo.failHistory = true
	if _, err := svc.Communities(context.Background(), viewer, "flamengo", 10, ""); err != nil {
		t.Fatalf("history failure must not fail the search: %v", err)
	}
}

func TestCapabilitiesContract(t *testing.T) {
	caps := New(&fakeRepo{}).Capabilities()
	if len(caps.Enabled) != 6 {
		t.Fatalf("exactly 6 enabled categories, got %v", caps.Enabled)
	}
	for _, blocked := range []string{"teams", "players"} {
		reason, ok := caps.Blocked[blocked]
		if !ok || reason == "" {
			t.Fatalf("%s must be reported BLOCKED_BY_DOMAIN with a reason", blocked)
		}
		for _, e := range caps.Enabled {
			if e == blocked {
				t.Fatalf("%s must never be enabled", blocked)
			}
		}
	}
	if caps.Trending != "UNAVAILABLE" {
		t.Fatalf("trending must be UNAVAILABLE (never fabricated), got %q", caps.Trending)
	}
}
