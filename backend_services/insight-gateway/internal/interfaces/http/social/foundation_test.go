// Social Foundation BFF tests — Sprint 2.5 Part 16.
package social

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/emptypb"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/authmw"
)

// ---- fakes -------------------------------------------------------------------

type fakeFeed struct {
	lastReq    *socialv1.FeedRequest
	lastAuthor *socialv1.AuthorPostsRequest
	resp       *socialv1.FeedResponse
	err        error
}

func (f *fakeFeed) Global(_ context.Context, in *socialv1.FeedRequest, _ ...grpc.CallOption) (*socialv1.FeedResponse, error) {
	f.lastReq = in
	return f.resp, f.err
}

func (f *fakeFeed) Following(_ context.Context, in *socialv1.FeedRequest, _ ...grpc.CallOption) (*socialv1.FeedResponse, error) {
	f.lastReq = in
	return f.resp, f.err
}

func (f *fakeFeed) AuthorPosts(_ context.Context, in *socialv1.AuthorPostsRequest, _ ...grpc.CallOption) (*socialv1.FeedResponse, error) {
	f.lastAuthor = in
	return f.resp, f.err
}

type fakeRels struct {
	followErr error
	muted     bool
	calls     []string
}

func (f *fakeRels) Follow(_ context.Context, in *socialv1.FollowRequest, _ ...grpc.CallOption) (*socialv1.Relationship, error) {
	f.calls = append(f.calls, "follow:"+in.GetTargetUserId())
	if f.followErr != nil {
		return nil, f.followErr
	}
	return &socialv1.Relationship{
		SourceUserId: in.GetSourceUserId(),
		TargetUserId: in.GetTargetUserId(),
	}, nil
}

func (f *fakeRels) Unfollow(_ context.Context, in *socialv1.UnfollowRequest, _ ...grpc.CallOption) (*emptypb.Empty, error) {
	f.calls = append(f.calls, "unfollow:"+in.GetTargetUserId())
	return &emptypb.Empty{}, nil
}

func (f *fakeRels) Mute(_ context.Context, in *socialv1.MuteRequest, _ ...grpc.CallOption) (*socialv1.Relationship, error) {
	f.calls = append(f.calls, "mute:"+in.GetTargetUserId())
	return &socialv1.Relationship{
		SourceUserId: in.GetSourceUserId(),
		TargetUserId: in.GetTargetUserId(),
		Muted:        true,
	}, nil
}

func (f *fakeRels) Unmute(_ context.Context, in *socialv1.UnmuteRequest, _ ...grpc.CallOption) (*socialv1.Relationship, error) {
	f.calls = append(f.calls, "unmute:"+in.GetTargetUserId())
	return &socialv1.Relationship{
		SourceUserId: in.GetSourceUserId(),
		TargetUserId: in.GetTargetUserId(),
		Muted:        false,
	}, nil
}

type fakePosts struct {
	created *socialv1.CreatePostRequest
	getErr  error
}

func (f *fakePosts) Create(_ context.Context, in *socialv1.CreatePostRequest, _ ...grpc.CallOption) (*socialv1.Post, error) {
	f.created = in
	return &socialv1.Post{
		Id:         "p1",
		AuthorId:   in.GetAuthorId(),
		AuthorType: in.GetAuthorType(),
		Content:    in.GetContent(),
		Visibility: in.GetVisibility(),
		CreatedAt:  timestamppb.New(time.Now()),
	}, nil
}

func (f *fakePosts) Get(_ context.Context, in *socialv1.GetPostRequest, _ ...grpc.CallOption) (*socialv1.Post, error) {
	if f.getErr != nil {
		return nil, f.getErr
	}
	return &socialv1.Post{Id: in.GetId()}, nil
}

func (f *fakePosts) Delete(_ context.Context, in *socialv1.DeletePostRequest, _ ...grpc.CallOption) (*emptypb.Empty, error) {
	return &emptypb.Empty{}, nil
}

func (f *fakePosts) CreateComment(_ context.Context, in *socialv1.CreateCommentRequest, _ ...grpc.CallOption) (*socialv1.Comment, error) {
	if in.GetParentId() == "too-deep" {
		return nil, status.Error(codes.InvalidArgument, "max_comment_depth_exceeded")
	}
	return &socialv1.Comment{
		Id: "c1", PostId: in.GetPostId(), ParentId: in.GetParentId(),
		AuthorId: in.GetAuthorId(), Content: in.GetContent(), Depth: 1,
		CreatedAt: timestamppb.New(time.Now()),
	}, nil
}

func (f *fakePosts) ListComments(_ context.Context, in *socialv1.ListCommentsRequest, _ ...grpc.CallOption) (*socialv1.ListCommentsResponse, error) {
	return &socialv1.ListCommentsResponse{}, nil
}

func (f *fakePosts) Like(_ context.Context, _ *socialv1.LikePostRequest, _ ...grpc.CallOption) (*emptypb.Empty, error) {
	return &emptypb.Empty{}, nil
}

func (f *fakePosts) Unlike(_ context.Context, _ *socialv1.UnlikePostRequest, _ ...grpc.CallOption) (*emptypb.Empty, error) {
	return &emptypb.Empty{}, nil
}

type fakeAgents struct{}

func (fakeAgents) List(_ context.Context, _ *socialv1.ListAgentsRequest, _ ...grpc.CallOption) (*socialv1.ListAgentsResponse, error) {
	return &socialv1.ListAgentsResponse{Agents: []*socialv1.AgentProfile{
		{Id: "a1", Slug: "ninja", Name: "Ninja", Active: true, Verified: true,
			CreatedAt: timestamppb.New(time.Now())},
	}}, nil
}

func (fakeAgents) Get(_ context.Context, in *socialv1.GetAgentRequest, _ ...grpc.CallOption) (*socialv1.AgentProfile, error) {
	if in.GetId() == "" && in.GetSlug() == "" {
		return nil, status.Error(codes.InvalidArgument, "id or slug required")
	}
	return &socialv1.AgentProfile{Id: "a1", Slug: "ninja", Name: "Ninja",
		CreatedAt: timestamppb.New(time.Now())}, nil
}

type fakeUsers struct{ lastID string }

func (f *fakeUsers) Get(_ context.Context, in *socialv1.GetUserRequest, _ ...grpc.CallOption) (*socialv1.User, error) {
	f.lastID = in.GetId()
	return &socialv1.User{
		Id: in.GetId(), Username: "dani", DisplayName: "Daniela",
		Initials: "DS", AccentColor: "#5BA8FF", Reputation: 42,
	}, nil
}

// ---- harness --------------------------------------------------------------------

var testUser = uuid.MustParse("4dc85496-1ca7-4a91-8884-44d847bbbf09")

func harness(feed *fakeFeed, rels *fakeRels, posts *fakePosts) *FoundationHandlers {
	return NewFoundationHandlers(FoundationDeps{
		Feed:          feed,
		Agents:        fakeAgents{},
		Posts:         posts,
		Users:         &fakeUsers{},
		Relationships: rels,
	})
}

// do executes a handler through a chi router with an authenticated
// context (mirroring authmw.Require + the route pattern params).
func do(h http.HandlerFunc, method, path, pattern string, body string, authed bool) *httptest.ResponseRecorder {
	router := chi.NewRouter()
	router.MethodFunc(method, pattern, h)
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	if authed {
		req = req.WithContext(authmw.WithUserID(req.Context(), testUser))
	}
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	return rec
}

// ---- auth (Part 14) ----------------------------------------------------------------

func TestUnauthenticatedContextIs401(t *testing.T) {
	h := harness(&fakeFeed{resp: &socialv1.FeedResponse{}}, &fakeRels{}, &fakePosts{})
	rec := do(h.GlobalFeed, http.MethodGet, "/v1/feed/global", "/v1/feed/global", "", false)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("want 401 without auth context, got %d", rec.Code)
	}
}

func TestActingUserAlwaysComesFromToken(t *testing.T) {
	feed := &fakeFeed{resp: &socialv1.FeedResponse{}}
	h := harness(feed, &fakeRels{}, &fakePosts{})
	// A malicious user_id query param must be ignored.
	rec := do(h.GlobalFeed, http.MethodGet,
		"/v1/feed/global?user_id=someone-else", "/v1/feed/global", "", true)
	if rec.Code != http.StatusOK {
		t.Fatalf("want 200, got %d (%s)", rec.Code, rec.Body)
	}
	if feed.lastReq.GetUserId() != testUser.String() {
		t.Fatalf("impersonation: upstream saw %q, want token user %q",
			feed.lastReq.GetUserId(), testUser)
	}
}

func TestCreatePostAuthorIsTokenUser(t *testing.T) {
	posts := &fakePosts{}
	h := harness(&fakeFeed{}, &fakeRels{}, posts)
	rec := do(h.CreatePost, http.MethodPost, "/v1/posts", "/v1/posts",
		`{"content":"olá","author_id":"someone-else","author_type":"admin"}`, true)
	if rec.Code != http.StatusCreated {
		t.Fatalf("want 201, got %d (%s)", rec.Code, rec.Body)
	}
	if posts.created.GetAuthorId() != testUser.String() {
		t.Fatal("author_id from the body must be ignored — token user only")
	}
	if posts.created.GetAuthorType() != socialv1.AuthorType_AUTHOR_TYPE_USER {
		t.Fatal("public BFF posts are ALWAYS author_type=user")
	}
}

// ---- pagination (Part 16) ------------------------------------------------------------

func TestPaginationClampAndCursorPassThrough(t *testing.T) {
	feed := &fakeFeed{resp: &socialv1.FeedResponse{}}
	h := harness(feed, &fakeRels{}, &fakePosts{})

	rec := do(h.GlobalFeed, http.MethodGet,
		"/v1/feed/global?limit=99999&cursor=abc", "/v1/feed/global", "", true)
	if rec.Code != http.StatusOK {
		t.Fatalf("want 200, got %d", rec.Code)
	}
	if feed.lastReq.GetLimit() != maxPageLimit {
		t.Fatalf("limit must clamp to %d, got %d", maxPageLimit, feed.lastReq.GetLimit())
	}
	if feed.lastReq.GetCursor() != "abc" {
		t.Fatalf("cursor must pass through, got %q", feed.lastReq.GetCursor())
	}
}

// ---- error mapping (Part 12) -----------------------------------------------------------

func TestGrpcErrorsMapToHTTP(t *testing.T) {
	cases := []struct {
		code codes.Code
		want int
	}{
		{codes.NotFound, http.StatusNotFound},
		{codes.InvalidArgument, http.StatusBadRequest},
		{codes.PermissionDenied, http.StatusForbidden},
		{codes.Unavailable, http.StatusServiceUnavailable},
		{codes.Internal, http.StatusInternalServerError},
	}
	for _, tc := range cases {
		posts := &fakePosts{getErr: status.Error(tc.code, "boom")}
		h := harness(&fakeFeed{}, &fakeRels{}, posts)
		rec := do(h.GetPost, http.MethodGet, "/v1/posts/p1",
			"/v1/posts/{postId}", "", true)
		if rec.Code != tc.want {
			t.Fatalf("%s: want %d, got %d", tc.code, tc.want, rec.Code)
		}
		var body map[string]any
		if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
			t.Fatalf("%s: error body must be JSON: %v", tc.code, err)
		}
		if _, ok := body["error"]; !ok {
			t.Fatalf("%s: consistent error shape requires `error` key", tc.code)
		}
		if strings.Contains(rec.Body.String(), "goroutine") {
			t.Fatal("stack traces must never leak")
		}
	}
}

func TestInternalErrorsDontLeakDetails(t *testing.T) {
	posts := &fakePosts{getErr: status.Error(codes.Internal, "pgx: connection refused dsn=...")}
	h := harness(&fakeFeed{}, &fakeRels{}, posts)
	rec := do(h.GetPost, http.MethodGet, "/v1/posts/p1", "/v1/posts/{postId}", "", true)
	if strings.Contains(rec.Body.String(), "pgx") {
		t.Fatal("5xx details must not reach the wire")
	}
}

// ---- follow / mute (Parts 8 + 9) ---------------------------------------------------------

func TestFollowIsIdempotentOnAlreadyExists(t *testing.T) {
	rels := &fakeRels{followErr: status.Error(codes.AlreadyExists, "already_following")}
	h := harness(&fakeFeed{}, rels, &fakePosts{})
	rec := do(h.Follow, http.MethodPost, "/v1/follow/t1", "/v1/follow/{targetId}", "", true)
	if rec.Code != http.StatusOK {
		t.Fatalf("re-follow must succeed (mobile retry), got %d", rec.Code)
	}
}

func TestMuteEchoesState(t *testing.T) {
	rels := &fakeRels{}
	h := harness(&fakeFeed{}, rels, &fakePosts{})
	rec := do(h.Mute, http.MethodPost, "/v1/mute/t1", "/v1/mute/{targetId}", "", true)
	if rec.Code != http.StatusOK {
		t.Fatalf("want 200, got %d", rec.Code)
	}
	var dto RelationshipDTO
	_ = json.Unmarshal(rec.Body.Bytes(), &dto)
	if !dto.Muted || !dto.Followed {
		t.Fatalf("mute must preserve follow + set muted: %+v", dto)
	}
}

// ---- feed DTO + updates (Parts 3 + 10 + 11) -----------------------------------------------

func TestFeedResponseIsStableDTO(t *testing.T) {
	feed := &fakeFeed{resp: &socialv1.FeedResponse{
		Items: []*socialv1.FeedItem{{
			Post: &socialv1.Post{
				Id: "p1", AuthorId: "a1",
				AuthorType: socialv1.AuthorType_AUTHOR_TYPE_AGENT,
				Content:    "tendência",
				Visibility: socialv1.PostVisibility_POST_VISIBILITY_PUBLIC,
				CreatedAt:  timestamppb.New(time.Now()),
			},
			AuthorName:        "Ninja",
			FromFollowedAgent: true,
		}},
	}}
	h := harness(feed, &fakeRels{}, &fakePosts{})
	rec := do(h.GlobalFeed, http.MethodGet, "/v1/feed/global", "/v1/feed/global", "", true)

	var page FeedPageDTO
	if err := json.Unmarshal(rec.Body.Bytes(), &page); err != nil {
		t.Fatal(err)
	}
	if len(page.Items) != 1 {
		t.Fatalf("want 1 item, got %d", len(page.Items))
	}
	item := page.Items[0]
	if item.Post.AuthorType != "agent" || !item.FromFollowedAgent {
		t.Fatalf("agent post must survive DTO mapping intact: %+v", item)
	}
	if strings.Contains(rec.Body.String(), "AUTHOR_TYPE_") {
		t.Fatal("raw gRPC enum names must never leak to the wire")
	}
}

func TestFeedUpdatesCountsNewerPosts(t *testing.T) {
	now := time.Now().UTC()
	feed := &fakeFeed{resp: &socialv1.FeedResponse{
		Items: []*socialv1.FeedItem{
			{Post: &socialv1.Post{Id: "new1", CreatedAt: timestamppb.New(now)}},
			{Post: &socialv1.Post{Id: "new2", CreatedAt: timestamppb.New(now.Add(-time.Minute))}},
			{Post: &socialv1.Post{Id: "old", CreatedAt: timestamppb.New(now.Add(-2 * time.Hour))}},
		},
	}}
	h := harness(feed, &fakeRels{}, &fakePosts{})
	since := now.Add(-time.Hour).Format(time.RFC3339)
	rec := do(h.FeedUpdates, http.MethodGet,
		"/v1/feed/updates?since="+since, "/v1/feed/updates", "", true)

	var dto FeedUpdatesDTO
	_ = json.Unmarshal(rec.Body.Bytes(), &dto)
	if !dto.HasUpdates || dto.NewPosts != 2 {
		t.Fatalf("want 2 new posts, got %+v", dto)
	}
}

func TestFeedUpdatesRequiresValidSince(t *testing.T) {
	h := harness(&fakeFeed{}, &fakeRels{}, &fakePosts{})
	rec := do(h.FeedUpdates, http.MethodGet,
		"/v1/feed/updates?since=yesterday", "/v1/feed/updates", "", true)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("want 400 on malformed since, got %d", rec.Code)
	}
}

// ---- payload guard (Part 14) -----------------------------------------------------------

func TestOversizedBodyRejected(t *testing.T) {
	h := harness(&fakeFeed{}, &fakeRels{}, &fakePosts{})
	huge := `{"content":"` + strings.Repeat("x", maxBodyBytes+1024) + `"}`
	rec := do(h.CreatePost, http.MethodPost, "/v1/posts", "/v1/posts", huge, true)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("oversized body must 400, got %d", rec.Code)
	}
}

// ---- Production Closure: user profile + author posts -----------------------------

func TestGetUserReturnsPublicProfile(t *testing.T) {
	users := &fakeUsers{}
	h := NewFoundationHandlers(FoundationDeps{
		Feed: &fakeFeed{}, Agents: fakeAgents{}, Posts: &fakePosts{},
		Users: users, Relationships: &fakeRels{},
	})
	rec := do(h.GetUser, http.MethodGet, "/v1/users/u9", "/v1/users/{userId}", "", true)
	if rec.Code != http.StatusOK {
		t.Fatalf("want 200, got %d (%s)", rec.Code, rec.Body)
	}
	if users.lastID != "u9" {
		t.Fatalf("upstream user id = %q, want u9", users.lastID)
	}
	var dto UserDTO
	if err := json.Unmarshal(rec.Body.Bytes(), &dto); err != nil {
		t.Fatal(err)
	}
	if dto.DisplayName != "Daniela" || dto.Reputation != 42 {
		t.Fatalf("unexpected profile dto: %+v", dto)
	}
}

func TestUserPostsUsesAuthorPostsWithViewer(t *testing.T) {
	feed := &fakeFeed{resp: &socialv1.FeedResponse{Items: []*socialv1.FeedItem{
		{Post: &socialv1.Post{Id: "p1", AuthorId: "u9"}, AuthorName: "Daniela",
			LikedByMe: true},
	}}}
	h := harness(feed, &fakeRels{}, &fakePosts{})
	rec := do(h.UserPosts, http.MethodGet, "/v1/users/u9/posts",
		"/v1/users/{userId}/posts", "", true)
	if rec.Code != http.StatusOK {
		t.Fatalf("want 200, got %d (%s)", rec.Code, rec.Body)
	}
	// author = path id; viewer = token user (so liked_by_me is correct).
	if feed.lastAuthor.GetAuthorId() != "u9" {
		t.Fatalf("author_id = %q, want u9", feed.lastAuthor.GetAuthorId())
	}
	if feed.lastAuthor.GetViewerId() != testUser.String() {
		t.Fatalf("viewer_id = %q, want token user", feed.lastAuthor.GetViewerId())
	}
	var page FeedPageDTO
	if err := json.Unmarshal(rec.Body.Bytes(), &page); err != nil {
		t.Fatal(err)
	}
	if len(page.Items) != 1 || !page.Items[0].LikedByMe {
		t.Fatalf("liked_by_me must propagate to the DTO: %+v", page.Items)
	}
}

func TestAgentPostsUsesAuthorPosts(t *testing.T) {
	feed := &fakeFeed{resp: &socialv1.FeedResponse{}}
	h := harness(feed, &fakeRels{}, &fakePosts{})
	rec := do(h.AgentPosts, http.MethodGet, "/v1/agents/a1/posts",
		"/v1/agents/{agentId}/posts", "", true)
	if rec.Code != http.StatusOK {
		t.Fatalf("want 200, got %d", rec.Code)
	}
	if feed.lastAuthor.GetAuthorId() != "a1" {
		t.Fatalf("agent posts must query author a1, got %q", feed.lastAuthor.GetAuthorId())
	}
}
