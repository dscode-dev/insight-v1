// FEATURE-SEARCH-V1 Stage 2 — orchestrator behaviour proofs: deterministic
// normalized-score merge, honest partial semantics, cancellation propagation
// (no orphan goroutines), per-user cache isolation, deep links, rate limiting,
// moderation filtering and correlation-id reuse across the fan-out.
package searchbff

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"github.com/prometheus/client_golang/prometheus"
)

func testMetrics() *Metrics { return NewMetrics(prometheus.NewRegistry()) }

func card(cat, id string) Card {
	return Card{EntityType: entityTypeFor[cat], EntityID: id,
		DeepLink: deepLink(cat, id), Data: json.RawMessage(`{}`)}
}

func fixedFetcher(cat string, ids ...string) Fetcher {
	return func(context.Context, callCtx, string, int, string) (CategoryPage, error) {
		cards := make([]Card, 0, len(ids))
		for _, id := range ids {
			cards = append(cards, card(cat, id))
		}
		return CategoryPage{Cards: cards, NextCursor: "cur-" + cat}, nil
	}
}

func failingFetcher(err error) Fetcher {
	return func(context.Context, callCtx, string, int, string) (CategoryPage, error) {
		return CategoryPage{}, err
	}
}

func agg(fetchers map[string]Fetcher, timeout time.Duration) *Aggregator {
	return &Aggregator{fetchers: fetchers, timeout: timeout, perCat: 5, metrics: testMetrics()}
}

// ---- normalized score + deterministic merge ----

func TestAll_NormalizedScoreDeterministicMerge(t *testing.T) {
	a := agg(map[string]Fetcher{
		"users": fixedFetcher("users", "u1", "u2"),
		"posts": fixedFetcher("posts", "p1", "p2", "p3"),
	}, time.Second)
	resp, err := a.All(context.Background(), callCtx{}, "neymar")
	if err != nil {
		t.Fatal(err)
	}
	// Position 0 in each category scores 1.0; ties break by category priority
	// (users before posts), then id. Position 1 scores 0.5, etc.
	wantOrder := []string{"u1", "p1", "u2", "p2", "p3"}
	if len(resp.Items) != 5 {
		t.Fatalf("want 5 items, got %d", len(resp.Items))
	}
	for i, want := range wantOrder {
		if resp.Items[i].EntityID != want {
			t.Fatalf("pos %d: want %s got %s", i, want, resp.Items[i].EntityID)
		}
	}
	if resp.Items[0].Score != 1.0 || resp.Items[2].Score != 0.5 {
		t.Fatalf("reciprocal-rank scores wrong: %v %v", resp.Items[0].Score, resp.Items[2].Score)
	}
	// Per-category cursors surface for continuation.
	if resp.Cursors["users"] != "cur-users" || resp.Cursors["posts"] != "cur-posts" {
		t.Fatalf("per-category cursors missing: %+v", resp.Cursors)
	}
	if resp.Partial || len(resp.FailedCategories) != 0 {
		t.Fatal("fully successful fan-out must not be partial")
	}
	// Determinism: same input ⇒ same order.
	resp2, _ := a.All(context.Background(), callCtx{}, "neymar")
	for i := range resp.Items {
		if resp.Items[i].EntityID != resp2.Items[i].EntityID {
			t.Fatal("aggregation must be deterministic")
		}
	}
}

// ---- partial semantics ----

func TestAll_PartialNeverSilentEmpty(t *testing.T) {
	a := agg(map[string]Fetcher{
		"users":       fixedFetcher("users", "u1"),
		"communities": failingFetcher(errors.New("boom")),
		"posts":       fixedFetcher("posts", "p1"),
	}, time.Second)
	resp, err := a.All(context.Background(), callCtx{}, "fla")
	if err != nil {
		t.Fatal(err)
	}
	if !resp.Partial {
		t.Fatal("a failed category MUST set partial=true")
	}
	if len(resp.FailedCategories) != 1 || resp.FailedCategories[0] != "communities" {
		t.Fatalf("failed categories must be named exactly: %v", resp.FailedCategories)
	}
	if len(resp.Items) != 2 {
		t.Fatal("successful categories must still return items")
	}
}

func TestAll_AllFailedIsErrorNotEmptyPage(t *testing.T) {
	a := agg(map[string]Fetcher{
		"users": failingFetcher(errors.New("down")),
		"posts": failingFetcher(errors.New("down")),
	}, time.Second)
	_, err := a.All(context.Background(), callCtx{}, "x")
	if !errors.Is(err, ErrAllCategoriesFailed) {
		t.Fatalf("all-failed must be an explicit error, got %v", err)
	}
}

// ---- cancellation: workers unblock, no orphan goroutines ----

func TestAll_CancellationPropagates(t *testing.T) {
	var started, finished atomic.Int32
	blocking := func(ctx context.Context, _ callCtx, _ string, _ int, _ string) (CategoryPage, error) {
		started.Add(1)
		<-ctx.Done() // blocks until the aggregator's context is cancelled
		finished.Add(1)
		return CategoryPage{}, ctx.Err()
	}
	a := agg(map[string]Fetcher{"users": blocking, "posts": blocking}, 50*time.Millisecond)
	_, err := a.All(context.Background(), callCtx{}, "x")
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("global timeout must surface, got %v", err)
	}
	// All returned ⇒ WaitGroup joined ⇒ every worker finished (no orphans).
	if started.Load() != 2 || finished.Load() != 2 {
		t.Fatalf("workers must all start and finish: started=%d finished=%d",
			started.Load(), finished.Load())
	}
}

// ---- cache ----

func TestCache_PerUserIsolationAndTTL(t *testing.T) {
	c := NewCache(time.Minute, 10)
	now := time.Now()
	c.now = func() time.Time { return now }

	kA := c.Key("user-a", "users", "fla", "", 20)
	kB := c.Key("user-b", "users", "fla", "", 20)
	if kA == kB {
		t.Fatal("different users MUST have different cache keys")
	}
	if c.Key("u", "users", "fla", "", 20) == c.Key("u", "users", "fla", "cur", 20) {
		t.Fatal("cursor must be part of the key")
	}
	if c.Key("u", "users", "fla", "", 20) == c.Key("u", "users", "fla", "", 50) {
		t.Fatal("limit must be part of the key")
	}
	if c.Key("u", "users", "fla", "", 20) == c.Key("u", "posts", "fla", "", 20) {
		t.Fatal("category must be part of the key")
	}

	c.Set(kA, []byte("body-a"))
	if got, hit := c.Get(kA); !hit || string(got) != "body-a" {
		t.Fatal("hit expected for the same user")
	}
	if _, hit := c.Get(kB); hit {
		t.Fatal("user B must never see user A's entry")
	}
	// TTL expiry.
	now = now.Add(2 * time.Minute)
	if _, hit := c.Get(kA); hit {
		t.Fatal("expired entry must miss")
	}
}

// ---- deep links ----

func TestDeepLinks(t *testing.T) {
	cases := map[string]string{
		"users": "/users/x", "agents": "/agents/x",
		"communities": "/hub/community/x", "matches": "/live/match/x",
		"posts": "/post/x",
	}
	for cat, want := range cases {
		if dl := deepLink(cat, "x"); dl == nil || *dl != want {
			t.Fatalf("%s deep link wrong: %v", cat, dl)
		}
	}
	// Competitions: no client destination exists → honest null, never fabricated.
	if dl := deepLink("competitions", "x"); dl != nil {
		t.Fatalf("competitions must have a null deep link, got %v", *dl)
	}
}

// ---- rate limiter ----

func TestRateLimiterWindow(t *testing.T) {
	l := newRateLimiter(3, time.Minute)
	now := time.Now()
	l.now = func() time.Time { return now }
	for i := 0; i < 3; i++ {
		if !l.allow("u1") {
			t.Fatalf("request %d within budget must pass", i)
		}
	}
	if l.allow("u1") {
		t.Fatal("4th request in window must be limited")
	}
	if !l.allow("u2") {
		t.Fatal("limits are PER USER — u2 must pass")
	}
	now = now.Add(2 * time.Minute)
	if !l.allow("u1") {
		t.Fatal("window reset must allow again")
	}
}

// ---- moderation lens filtering ----

type fakeView struct{ hiddenAuthors, hiddenPosts map[string]bool }

func (v fakeView) AuthorHidden(id string) bool { return v.hiddenAuthors[id] }
func (v fakeView) PostHidden(id string) bool   { return v.hiddenPosts[id] }

type fakeLens struct{ view fakeView }

func (l fakeLens) SearchView(context.Context, string) (ModerationView, error) {
	return l.view, nil
}

func TestModerationLensFiltersUsersAndPosts(t *testing.T) {
	h := &Handlers{mod: fakeLens{view: fakeView{
		hiddenAuthors: map[string]bool{"banned-user": true, "banned-author": true},
		hiddenPosts:   map[string]bool{"hidden-post": true},
	}}}
	postData, _ := json.Marshal(PublicPost{ID: "p-ok", AuthorID: "banned-author"})
	cards := []Card{
		card("users", "banned-user"),                           // dropped: hidden user
		card("users", "ok-user"),                               // kept
		card("posts", "hidden-post"),                           // dropped: admin-hidden post
		{EntityType: "post", EntityID: "p-ok", Data: postData}, // dropped: hidden AUTHOR
		{EntityType: "post", EntityID: "p2", Data: json.RawMessage(`{"author_id":"x"}`)}, // kept
	}
	kept := h.applyLens(context.Background(), "viewer", cards)
	if len(kept) != 2 {
		t.Fatalf("want 2 kept, got %d: %+v", len(kept), kept)
	}
	if kept[0].EntityID != "ok-user" || kept[1].EntityID != "p2" {
		t.Fatalf("wrong survivors: %s %s", kept[0].EntityID, kept[1].EntityID)
	}
}

// ---- correlation id + X-User-Id propagation (real HTTP round-trip) ----

func TestClientReusesCorrelationIDAndForwardsUser(t *testing.T) {
	var gotCorr, gotUser atomic.Value
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotCorr.Store(r.Header.Get("X-Request-Id"))
		gotUser.Store(r.Header.Get("X-User-Id"))
		_, _ = w.Write([]byte(`{"items":[],"next_cursor":""}`))
	}))
	defer srv.Close()

	c := NewSocialClient(srv.URL)
	cc := callCtx{UserID: "user-1", CorrelationID: "corr-abc"}
	if _, err := c.Users(context.Background(), cc, "fla", 5, ""); err != nil {
		t.Fatal(err)
	}
	if gotCorr.Load() != "corr-abc" {
		t.Fatalf("fan-out must reuse the SAME correlation id, got %v", gotCorr.Load())
	}
	if gotUser.Load() != "user-1" {
		t.Fatalf("verified user must be forwarded, got %v", gotUser.Load())
	}
}
