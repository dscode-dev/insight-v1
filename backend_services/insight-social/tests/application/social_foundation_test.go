// Sprint 3 — Social Foundation proofs:
//
//  1. automatic agent following (idempotent)
//  2. mute behavior (muted stays followed, never feeds)
//  3. mandatory agent feed inclusion (no ranking removes agent posts)
//  4. agent priority ordering (close timestamps → agents first)
//  5. following feed isolation (no public discovery, chronological)
//  6. query-time feed generation (a new post appears on the next
//     read with no write-side fanout)
package application_test

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	appfeed "github.com/konoha-labs/insight-social/internal/application/feed"
	apppost "github.com/konoha-labs/insight-social/internal/application/post"
	appuser "github.com/konoha-labs/insight-social/internal/application/user"
	domfeed "github.com/konoha-labs/insight-social/internal/domain/feed"
	dompost "github.com/konoha-labs/insight-social/internal/domain/post"
	domuser "github.com/konoha-labs/insight-social/internal/domain/user"
)

var t0 = time.Date(2026, 6, 1, 12, 0, 0, 0, time.UTC)

// ---- fakes -----------------------------------------------------------------

type fakeUserRepo struct{ users map[uuid.UUID]*domuser.User }

func (f *fakeUserRepo) Insert(_ context.Context, u *domuser.User) error {
	f.users[u.ID()] = u
	return nil
}
func (f *fakeUserRepo) GetByID(_ context.Context, id uuid.UUID) (*domuser.User, error) {
	return f.users[id], nil
}
func (f *fakeUserRepo) GetByUsername(context.Context, string) (*domuser.User, error) {
	return nil, domuser.ErrNotFound
}
func (f *fakeUserRepo) List(context.Context, []uuid.UUID) ([]*domuser.User, error) {
	return nil, nil
}
func (f *fakeUserRepo) UpdateAccent(context.Context, uuid.UUID, string) (*domuser.User, error) {
	return nil, nil
}
func (f *fakeUserRepo) UpdateAvatar(context.Context, uuid.UUID, string) (*domuser.User, error) {
	return nil, nil
}
func (f *fakeUserRepo) Stats(context.Context, uuid.UUID) (domuser.Stats, error) {
	return domuser.Stats{}, nil
}

type fakeAgentDir struct{ ids []uuid.UUID }

func (f *fakeAgentDir) ActiveIDs(context.Context) ([]uuid.UUID, error) {
	return f.ids, nil
}

// fakeGraph implements both appuser.FollowCreator and
// appfeed.FollowGraph: a tiny in-memory follow graph with mute.
type fakeGraph struct {
	follows map[uuid.UUID]map[uuid.UUID]bool // actor → target → muted
	calls   int
}

func newFakeGraph() *fakeGraph {
	return &fakeGraph{follows: map[uuid.UUID]map[uuid.UUID]bool{}}
}

func (f *fakeGraph) FollowIdempotent(_ context.Context, actorID, targetID uuid.UUID) error {
	f.calls++
	if f.follows[actorID] == nil {
		f.follows[actorID] = map[uuid.UUID]bool{}
	}
	if _, exists := f.follows[actorID][targetID]; !exists {
		f.follows[actorID][targetID] = false
	}
	return nil
}

func (f *fakeGraph) Mute(actorID, targetID uuid.UUID) {
	f.follows[actorID][targetID] = true
}

func (f *fakeGraph) FollowingIDs(_ context.Context, userID uuid.UUID, excludeMuted bool) ([]uuid.UUID, error) {
	var out []uuid.UUID
	for target, muted := range f.follows[userID] {
		if excludeMuted && muted {
			continue
		}
		out = append(out, target)
	}
	return out, nil
}

// fakePosts implements both dompost.Repository (writes) and
// domfeed.Repository (reads) over one in-memory slice — which is
// exactly what makes proof 6 (query-time generation) demonstrable.
type fakePosts struct {
	reposts        map[string]bool
	externalShares int
	posts          []*dompost.Post
	// liked is keyed by "<viewerID>|<postID>" → true.
	liked map[string]bool
}

func (f *fakePosts) InsertPost(_ context.Context, p *dompost.Post) error {
	f.posts = append(f.posts, p)
	return nil
}
func (f *fakePosts) GetPost(_ context.Context, id uuid.UUID) (*dompost.Post, error) {
	for _, p := range f.posts {
		if p.ID == id {
			return p, nil
		}
	}
	return nil, dompost.ErrNotFound
}
func (f *fakePosts) SoftDeletePost(context.Context, uuid.UUID, uuid.UUID) error { return nil }
func (f *fakePosts) InsertComment(context.Context, *dompost.Comment) error      { return nil }
func (f *fakePosts) GetComment(context.Context, uuid.UUID) (*dompost.Comment, error) {
	return nil, dompost.ErrCommentNotFound
}
func (f *fakePosts) ListComments(context.Context, uuid.UUID, int, string) (dompost.CommentPage, error) {
	return dompost.CommentPage{}, nil
}
func (f *fakePosts) Like(context.Context, uuid.UUID, uuid.UUID) error   { return nil }
func (f *fakePosts) Unlike(context.Context, uuid.UUID, uuid.UUID) error { return nil }

func (f *fakePosts) PostsByAuthors(_ context.Context, q domfeed.CandidateQuery) ([]*domfeed.Item, error) {
	authorSet := map[uuid.UUID]bool{}
	for _, id := range q.AuthorIDs {
		authorSet[id] = true
	}
	var out []*domfeed.Item
	for _, p := range f.posts {
		if authorSet[p.AuthorID] && p.CreatedAt.Before(q.Before) &&
			p.Visibility != dompost.VisibilityPrivate {
			out = append(out, &domfeed.Item{Post: p})
		}
		if len(out) == q.Limit {
			break
		}
	}
	return out, nil
}

func (f *fakePosts) RecentPublic(_ context.Context, before time.Time, limit int, _ *uuid.UUID) ([]*domfeed.Item, error) {
	var out []*domfeed.Item
	for _, p := range f.posts {
		if p.Visibility == dompost.VisibilityPublic && p.CreatedAt.Before(before) {
			out = append(out, &domfeed.Item{Post: p})
		}
		if len(out) == limit {
			break
		}
	}
	return out, nil
}

func (f *fakePosts) LikedPostIDs(
	_ context.Context, viewerID uuid.UUID, postIDs []uuid.UUID,
) (map[uuid.UUID]bool, error) {
	out := map[uuid.UUID]bool{}
	for _, pid := range postIDs {
		if f.liked[viewerID.String()+"|"+pid.String()] {
			out[pid] = true
		}
	}
	return out, nil
}

func addPost(f *fakePosts, author uuid.UUID, at time.Time, kind dompost.AuthorType, content string) *dompost.Post {
	p := &dompost.Post{
		ID: uuid.New(), AuthorID: author, AuthorType: kind,
		Content: content, Metadata: map[string]string{},
		Visibility: dompost.VisibilityPublic, CreatedAt: at,
	}
	f.posts = append(f.posts, p)
	return p
}

// ---- proof 1: automatic agent following --------------------------------------

func TestNewUserAutoFollowsAllActiveAgents(t *testing.T) {
	agents := &fakeAgentDir{ids: []uuid.UUID{
		uuid.New(), uuid.New(), uuid.New(), uuid.New(), uuid.New(),
	}}
	graph := newFakeGraph()
	svc := appuser.New(&fakeUserRepo{users: map[uuid.UUID]*domuser.User{}}).
		WithAgentAutoFollow(agents, graph)

	u, err := svc.Create(context.Background(), "torcedor", "Torcedor", "")
	if err != nil {
		t.Fatal(err)
	}
	following, _ := graph.FollowingIDs(context.Background(), u.ID(), false)
	if len(following) != 5 {
		t.Fatalf("new user must follow all 5 active agents, got %d", len(following))
	}

	// Idempotent: replaying the auto-follow changes nothing.
	for _, agentID := range agents.ids {
		if err := graph.FollowIdempotent(context.Background(), u.ID(), agentID); err != nil {
			t.Fatal(err)
		}
	}
	following, _ = graph.FollowingIDs(context.Background(), u.ID(), false)
	if len(following) != 5 {
		t.Fatalf("auto-follow must be idempotent, got %d follows", len(following))
	}
}

// ---- feed harness ---------------------------------------------------------------

func feedHarness() (svc *appfeed.Service, graph *fakeGraph, posts *fakePosts, agents *fakeAgentDir) {
	agents = &fakeAgentDir{ids: []uuid.UUID{uuid.New(), uuid.New()}}
	graph = newFakeGraph()
	posts = &fakePosts{}
	svc = appfeed.New(posts, graph, agents)
	return svc, graph, posts, agents
}

// ---- liked_by_me + AuthorPosts (Production Closure) -------------------------------

func TestFeedSetsLikedByMeForViewer(t *testing.T) {
	svc, graph, posts, agents := feedHarness()
	user := uuid.New()
	ninja := agents.ids[0]
	_ = graph.FollowIdempotent(context.Background(), user, ninja)
	liked := addPost(posts, ninja, t0, dompost.AuthorAgent, "liked post")
	notLiked := addPost(posts, ninja, t0.Add(time.Minute), dompost.AuthorAgent, "plain post")
	posts.liked = map[string]bool{user.String() + "|" + liked.ID.String(): true}

	page, err := svc.Global(context.Background(), user, 30, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	got := map[uuid.UUID]bool{}
	for _, it := range page.Items {
		got[it.Post.ID] = it.LikedByMe
	}
	if !got[liked.ID] {
		t.Error("liked post must report LikedByMe=true for the viewer")
	}
	if got[notLiked.ID] {
		t.Error("un-liked post must report LikedByMe=false")
	}
}

func TestAuthorPostsReturnsOnlyThatAuthorWithLikes(t *testing.T) {
	svc, _, posts, _ := feedHarness()
	viewer := uuid.New()
	author := uuid.New()
	other := uuid.New()
	mine := addPost(posts, author, t0.Add(time.Minute), dompost.AuthorUser, "mine")
	addPost(posts, other, t0, dompost.AuthorUser, "theirs")
	posts.liked = map[string]bool{viewer.String() + "|" + mine.ID.String(): true}

	page, err := svc.AuthorPosts(context.Background(), author, viewer, 30, "")
	if err != nil {
		t.Fatal(err)
	}
	if len(page.Items) != 1 || page.Items[0].Post.ID != mine.ID {
		t.Fatalf("AuthorPosts must return only the author's posts, got %d", len(page.Items))
	}
	if !page.Items[0].LikedByMe {
		t.Error("AuthorPosts must compute liked_by_me for the viewer")
	}
}

// ---- proof 2: mute behavior -------------------------------------------------------

func TestMutedAccountsRemainFollowedButNeverFeed(t *testing.T) {
	svc, graph, posts, agents := feedHarness()
	user := uuid.New()
	ninja, pulse := agents.ids[0], agents.ids[1]
	_ = graph.FollowIdempotent(context.Background(), user, ninja)
	_ = graph.FollowIdempotent(context.Background(), user, pulse)
	addPost(posts, ninja, t0, dompost.AuthorAgent, "ninja post")
	addPost(posts, pulse, t0.Add(time.Minute), dompost.AuthorAgent, "pulse post")

	graph.Mute(user, pulse)

	// Still followed (mute ≠ unfollow)…
	all, _ := graph.FollowingIDs(context.Background(), user, false)
	if len(all) != 2 {
		t.Fatalf("muted account must remain followed, following=%d", len(all))
	}
	// …but absent from BOTH feeds.
	for _, feed := range []func(context.Context, uuid.UUID, int, string, *uuid.UUID) (domfeed.Page, error){
		svc.Global, svc.Following,
	} {
		page, err := feed(context.Background(), user, 50, "", nil)
		if err != nil {
			t.Fatal(err)
		}
		for _, item := range page.Items {
			if item.Post.AuthorID == pulse {
				t.Fatal("muted agent's post must not appear in any feed")
			}
		}
	}
}

// ---- proof 3: mandatory agent feed inclusion ---------------------------------------

func TestFollowedAgentPostsAreMandatoryInGlobalFeed(t *testing.T) {
	svc, graph, posts, agents := feedHarness()
	user := uuid.New()
	ninja := agents.ids[0]
	_ = graph.FollowIdempotent(context.Background(), user, ninja)

	// The agent's post is OLD; the feed is flooded with newer public
	// posts — more than the limit. No ranking may displace the agent.
	agentPost := addPost(posts, ninja, t0.Add(-6*time.Hour), dompost.AuthorAgent, "old agent post")
	for i := 0; i < 30; i++ {
		addPost(posts, uuid.New(), t0.Add(time.Duration(i)*time.Minute),
			dompost.AuthorUser, "newer public post")
	}

	page, err := svc.Global(context.Background(), user, 10, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, item := range page.Items {
		if item.Post.ID == agentPost.ID {
			found = true
			if !item.FromFollowedAgent {
				t.Fatal("agent post must be flagged from_followed_agent")
			}
		}
	}
	if !found {
		t.Fatal("MANDATORY RULE violated: followed agent's post missing from global feed")
	}
}

// ---- proof 4: agent priority ordering ----------------------------------------------

func TestAgentPostsWinCloseTimestamps(t *testing.T) {
	svc, graph, posts, agents := feedHarness()
	user := uuid.New()
	ninja, pulse := agents.ids[0], agents.ids[1]
	friend := uuid.New()
	_ = graph.FollowIdempotent(context.Background(), user, ninja)
	_ = graph.FollowIdempotent(context.Background(), user, pulse)
	_ = graph.FollowIdempotent(context.Background(), user, friend)

	// Same 10-minute bucket; the USER post is the newest.
	ninjaPost := addPost(posts, ninja, t0.Add(1*time.Minute), dompost.AuthorAgent, "ninja")
	pulsePost := addPost(posts, pulse, t0.Add(2*time.Minute), dompost.AuthorAgent, "pulse")
	userPost := addPost(posts, friend, t0.Add(3*time.Minute), dompost.AuthorUser, "user")

	page, err := svc.Global(context.Background(), user, 10, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(page.Items) != 3 {
		t.Fatalf("want 3 items, got %d", len(page.Items))
	}
	// Agents first despite the user post being newest; newest agent first.
	if page.Items[0].Post.ID != pulsePost.ID || page.Items[1].Post.ID != ninjaPost.ID {
		t.Fatalf("agent posts must lead within a close-timestamp bucket: got %s, %s",
			page.Items[0].Post.Content, page.Items[1].Post.Content)
	}
	if page.Items[2].Post.ID != userPost.ID {
		t.Fatal("user post must follow the agent posts")
	}
}

// ---- proof 5: following feed isolation ----------------------------------------------

func TestFollowingFeedContainsOnlyFollowedAuthors(t *testing.T) {
	svc, graph, posts, agents := feedHarness()
	user := uuid.New()
	ninja := agents.ids[0]
	friend := uuid.New()
	stranger := uuid.New()
	_ = graph.FollowIdempotent(context.Background(), user, ninja)
	_ = graph.FollowIdempotent(context.Background(), user, friend)

	addPost(posts, ninja, t0, dompost.AuthorAgent, "agent post")
	addPost(posts, friend, t0.Add(time.Minute), dompost.AuthorUser, "friend post")
	addPost(posts, stranger, t0.Add(2*time.Minute), dompost.AuthorUser, "stranger post")

	page, err := svc.Following(context.Background(), user, 10, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(page.Items) != 2 {
		t.Fatalf("following feed must contain only followed authors, got %d", len(page.Items))
	}
	for _, item := range page.Items {
		if item.Post.AuthorID == stranger {
			t.Fatal("no public discovery in the following feed")
		}
	}
	// Chronological, newest first.
	if !page.Items[0].Post.CreatedAt.After(page.Items[1].Post.CreatedAt) {
		t.Fatal("following feed must be chronological (newest first)")
	}
}

// ---- AZTECA-POSTS-B: own-post feed semantics ------------------------------------------

// A self-authored PUBLIC post participates in the authoritative Global feed by
// normal recency (no pin/priority) and is never duplicated — resolving the
// "create → appears → disappears after refresh" contradiction (FEED_SELF_EXCLUSION).
func TestOwnPublicPostAppearsInGlobalFeed(t *testing.T) {
	svc, graph, posts, agents := feedHarness()
	user := uuid.New()
	ninja := agents.ids[0]
	_ = graph.FollowIdempotent(context.Background(), user, ninja)

	postSvc := apppost.New(posts)
	own, err := postSvc.Create(context.Background(), user, dompost.AuthorUser,
		"my own take", nil, dompost.VisibilityPublic, nil)
	if err != nil {
		t.Fatal(err)
	}

	page, err := svc.Global(context.Background(), user, 10, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	count := 0
	for _, item := range page.Items {
		if item.Post.ID == own.ID {
			count++
		}
	}
	if count != 1 {
		t.Fatalf("own public post must appear exactly once in the authoritative Global feed, got %d", count)
	}
}

// A private (non-public) self-post must NOT leak into the Global feed's public
// fill — only public posts participate.
func TestOwnPrivatePostStaysOutOfGlobalFeed(t *testing.T) {
	svc, graph, posts, agents := feedHarness()
	user := uuid.New()
	_ = graph.FollowIdempotent(context.Background(), user, agents.ids[0])

	postSvc := apppost.New(posts)
	priv, err := postSvc.Create(context.Background(), user, dompost.AuthorUser,
		"just for me", nil, dompost.VisibilityPrivate, nil)
	if err != nil {
		t.Fatal(err)
	}
	page, err := svc.Global(context.Background(), user, 10, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	for _, item := range page.Items {
		if item.Post.ID == priv.ID {
			t.Fatal("a private self-post must never enter the public feed fill")
		}
	}
}

// ---- proof 6: query-time generation ---------------------------------------------------

func TestFeedIsGeneratedAtQueryTime(t *testing.T) {
	svc, graph, posts, agents := feedHarness()
	user := uuid.New()
	ninja := agents.ids[0]
	_ = graph.FollowIdempotent(context.Background(), user, ninja)

	before, err := svc.Global(context.Background(), user, 10, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(before.Items) != 0 {
		t.Fatal("empty store must produce an empty feed")
	}

	// A post written through the WRITE path (no fanout, no timeline
	// materialization) is visible on the very next read.
	postSvc := apppost.New(posts)
	created, err := postSvc.Create(context.Background(), ninja,
		dompost.AuthorAgent, "fresh intelligence", nil, dompost.VisibilityPublic, nil)
	if err != nil {
		t.Fatal(err)
	}
	after, err := svc.Global(context.Background(), user, 10, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(after.Items) != 1 || after.Items[0].Post.ID != created.ID {
		t.Fatal("query-time generation: a new post must appear on the next read")
	}
}

// ---- comment depth rule (Part 6) -------------------------------------------------------

func TestCommentDepthLimitedToTwo(t *testing.T) {
	posts := &fakePosts{}
	svc := apppost.New(posts)
	p, err := svc.Create(context.Background(), uuid.New(), dompost.AuthorUser,
		"a post", nil, dompost.VisibilityPublic, nil)
	if err != nil {
		t.Fatal(err)
	}
	// post → comment (depth 1) → reply (depth 2) → reply-to-reply: NO.
	if _, err := dompost.NewComment(p.ID, nil, 0, uuid.New(), dompost.AuthorUser, "c1"); err != nil {
		t.Fatal(err)
	}
	parentID := uuid.New()
	if _, err := dompost.NewComment(p.ID, &parentID, 1, uuid.New(), dompost.AuthorUser, "r1"); err != nil {
		t.Fatal(err)
	}
	if _, err := dompost.NewComment(p.ID, &parentID, 2, uuid.New(), dompost.AuthorUser, "r2"); err != dompost.ErrMaxDepthExceeded {
		t.Fatalf("depth 3 must be rejected, got %v", err)
	}
}

// Shares, in memory. Modelled on the real rules rather than stubbed: a repost
// is unique per (user, post), an external share repeats, and the count sums
// both — so a test that exercises the service exercises the semantics too.
func (f *fakePosts) Share(_ context.Context, postID, userID uuid.UUID, target, channel string) (bool, int64, error) {
	key := postID.String() + "|" + userID.String()
	created := true
	if target == "feed" {
		if f.reposts == nil {
			f.reposts = map[string]bool{}
		}
		if f.reposts[key] {
			created = false
		} else {
			f.reposts[key] = true
		}
	} else {
		f.externalShares++
	}
	var count int64 = int64(f.externalShares)
	for k := range f.reposts {
		if strings.HasPrefix(k, postID.String()+"|") {
			count++
		}
	}
	return created, count, nil
}

func (f *fakePosts) Unshare(_ context.Context, postID, userID uuid.UUID) error {
	delete(f.reposts, postID.String()+"|"+userID.String())
	return nil
}
