// Social Foundation BFF — Sprint 2.5 Parts 3–10.
//
// The REST surface Azteca consumes for the Sprint 3 Social
// Foundation: feeds, agents, posts, comments, likes, follow and mute,
// all over the social.v1 gRPC services. One FoundationHandlers struct
// mirrors the existing Handlers pattern: thin orchestration, DTO
// shaping, consistent error mapping — ZERO business logic (Social is
// the source of truth for permissions, mute semantics and depth
// rules).
//
// SECURITY INVARIANT (Part 14): the acting user id ALWAYS comes from
// the authenticated token (authmw.UserID) — never from the request
// body or query — so a client can never act as another user.
package social

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"
	"time"

	"github.com/go-chi/chi/v5"
	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	appmod "github.com/konoha-labs/insight-gateway/internal/application/moderation"
	dommod "github.com/konoha-labs/insight-gateway/internal/domain/moderation"
	"github.com/konoha-labs/insight-gateway/internal/infrastructure/socialclient"
	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/authmw"
)

const (
	// Pagination abuse guard (Part 14): limits are clamped server-side.
	defaultPageLimit = 30
	maxPageLimit     = 100
	// Oversized-payload guard: post/comment bodies over this are
	// rejected before hitting Social (Social enforces its own caps too).
	maxBodyBytes = 64 << 10 // 64 KiB
)

// FoundationDeps wires the narrow transport slices (testable with
// fakes) + the metrics sink.
type FoundationDeps struct {
	Feed            socialclient.FeedClient
	Agents          socialclient.AgentClient
	Posts           socialclient.PostClient
	Users           socialclient.UserClient
	Relationships   socialclient.RelationshipClient
	Moderation      *appmod.Service // Store-A: block/ban content filter + write-gate; optional
	Metrics         *Metrics        // optional; nil disables instrumentation
	UpstreamTimeout time.Duration
}

type FoundationHandlers struct {
	feed    socialclient.FeedClient
	agents  socialclient.AgentClient
	posts   socialclient.PostClient
	users   socialclient.UserClient
	rels    socialclient.RelationshipClient
	mod     *appmod.Service
	metrics *Metrics
	timeout time.Duration
}

func NewFoundationHandlers(d FoundationDeps) *FoundationHandlers {
	t := d.UpstreamTimeout
	if t <= 0 {
		t = defaultUpstreamTimeout
	}
	return &FoundationHandlers{
		feed:    d.Feed,
		agents:  d.Agents,
		posts:   d.Posts,
		users:   d.Users,
		rels:    d.Relationships,
		mod:     d.Moderation,
		metrics: d.Metrics,
		timeout: t,
	}
}

// modView builds the caller's moderation filter (blocked authors + globally
// banned/suspended users + admin-hidden content). Returns nil when moderation
// is unwired — callers treat nil as "hide nothing".
func (h *FoundationHandlers) modView(ctx context.Context, viewerID string) *appmod.View {
	if h.mod == nil {
		return nil
	}
	v, err := h.mod.ViewFor(ctx, viewerID)
	if err != nil {
		return nil // fail-open on read: never break the feed because of a filter error
	}
	return v
}

// ensureCanAct write-gates banned/suspended users out of create paths.
// Returns false (response already written) when the user may not act.
func (h *FoundationHandlers) ensureCanAct(w http.ResponseWriter, r *http.Request) bool {
	if h.mod == nil {
		return true
	}
	uid, ok := authmw.UserID(r.Context())
	if !ok {
		return true
	}
	err := h.mod.EnsureCanAct(r.Context(), uid)
	switch {
	case err == nil:
		return true
	case errors.Is(err, dommod.ErrUserBanned):
		writeError(w, http.StatusForbidden, "account_banned", "Sua conta foi banida por violar os Termos de Uso.")
	case errors.Is(err, dommod.ErrUserSuspended):
		writeError(w, http.StatusForbidden, "account_suspended", "Sua conta está suspensa temporariamente.")
	default:
		writeError(w, http.StatusInternalServerError, "moderation_check_failed", "")
	}
	return false
}

// filterFeed drops hidden authors + hidden posts from a feed page in place.
func filterFeed(page FeedPageDTO, v *appmod.View) FeedPageDTO {
	if v == nil {
		return page
	}
	kept := page.Items[:0]
	for _, item := range page.Items {
		if v.AuthorHidden(item.Post.AuthorID) || v.PostHidden(item.Post.ID) {
			continue
		}
		kept = append(kept, item)
	}
	page.Items = kept
	return page
}

// userCtx extracts the authenticated user and returns an upstream-
// budgeted context annotated for cross-service correlation.
func (h *FoundationHandlers) userCtx(r *http.Request) (string, func(), error) {
	userID, ok := authmw.UserID(r.Context())
	if !ok {
		return "", func() {}, errAuthMissing
	}
	ctx, cancel := context.WithTimeout(r.Context(), h.timeout)
	ctx = socialclient.WithUserID(ctx, userID)
	*r = *r.WithContext(ctx)
	return userID.String(), cancel, nil
}

// pageParams clamps limit + extracts cursor (pagination abuse guard).
func pageParams(r *http.Request) (int32, *string) {
	limit := int32(defaultPageLimit)
	if raw := r.URL.Query().Get("limit"); raw != "" {
		if v, err := strconv.Atoi(raw); err == nil && v > 0 {
			if v > maxPageLimit {
				v = maxPageLimit
			}
			limit = int32(v)
		}
	}
	var cursor *string
	if raw := r.URL.Query().Get("cursor"); raw != "" {
		cursor = &raw
	}
	return limit, cursor
}

// ---- Part 3: feeds -----------------------------------------------------------

func (h *FoundationHandlers) GlobalFeed(w http.ResponseWriter, r *http.Request) {
	h.serveFeed(w, r, "global", h.feed.Global)
}

func (h *FoundationHandlers) FollowingFeed(w http.ResponseWriter, r *http.Request) {
	h.serveFeed(w, r, "following", h.feed.Following)
}

func (h *FoundationHandlers) serveFeed(
	w http.ResponseWriter,
	r *http.Request,
	kind string,
	call func(context.Context, *socialv1.FeedRequest, ...grpc.CallOption) (*socialv1.FeedResponse, error),
) {
	userID, cancel, err := h.userCtx(r)
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	defer cancel()
	h.metrics.feedRead(kind)

	limit, cursor := pageParams(r)
	resp, err := call(r.Context(), &socialv1.FeedRequest{
		UserId: userID,
		Limit:  &limit,
		Cursor: cursor,
	})
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	writeJSON(w, r, http.StatusOK, filterFeed(feedPageDTO(resp), h.modView(r.Context(), userID)))
}

// ---- Part 10: feed updates (polling now; SSE/WS later, same shape) -----------

func (h *FoundationHandlers) FeedUpdates(w http.ResponseWriter, r *http.Request) {
	userID, cancel, err := h.userCtx(r)
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	defer cancel()

	since, err := time.Parse(time.RFC3339, r.URL.Query().Get("since"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_since",
			"query param `since` must be RFC3339 (the newest created_at the client has)")
		return
	}

	limit := int32(maxPageLimit)
	resp, err := h.feed.Global(r.Context(), &socialv1.FeedRequest{
		UserId: userID,
		Limit:  &limit,
	})
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	var fresh int64
	for _, item := range resp.GetItems() {
		if item.GetPost().GetCreatedAt().AsTime().After(since) {
			fresh++
		}
	}
	writeJSON(w, r, http.StatusOK, FeedUpdatesDTO{
		HasUpdates: fresh > 0,
		NewPosts:   fresh,
	})
}

// ---- Part 4: agents -----------------------------------------------------------

func (h *FoundationHandlers) ListAgents(w http.ResponseWriter, r *http.Request) {
	_, cancel, err := h.userCtx(r)
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	defer cancel()

	resp, err := h.agents.List(r.Context(), &socialv1.ListAgentsRequest{
		ActiveOnly: r.URL.Query().Get("all") != "true",
	})
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	out := make([]AgentDTO, 0, len(resp.GetAgents()))
	for _, a := range resp.GetAgents() {
		out = append(out, agentDTO(a))
	}
	writeJSON(w, r, http.StatusOK, map[string]any{"agents": out})
}

func (h *FoundationHandlers) GetAgent(w http.ResponseWriter, r *http.Request) {
	_, cancel, err := h.userCtx(r)
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	defer cancel()

	id := chi.URLParam(r, "agentId")
	// Accept both UUIDs and slugs — mobile deep links use slugs.
	req := &socialv1.GetAgentRequest{}
	if looksLikeUUID(id) {
		req.Id = id
	} else {
		req.Slug = id
	}
	agent, err := h.agents.Get(r.Context(), req)
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	writeJSON(w, r, http.StatusOK, agentDTO(agent))
}

// AgentPosts — GET /v1/agents/:id/posts. Backed by the dedicated
// AuthorPosts RPC (real per-author query in Social) — no longer a
// filter over the caller's global feed page. liked_by_me is computed
// for the viewer.
func (h *FoundationHandlers) AgentPosts(w http.ResponseWriter, r *http.Request) {
	h.serveAuthorPosts(w, r, chi.URLParam(r, "agentId"))
}

// GetUser — GET /v1/users/:id. Public profile of any user.
func (h *FoundationHandlers) GetUser(w http.ResponseWriter, r *http.Request) {
	if _, cancel, err := h.userCtx(r); err != nil {
		writeGrpcError(w, r, err)
		return
	} else {
		defer cancel()
	}
	id := chi.URLParam(r, "userId")
	resp, err := h.users.Get(r.Context(), &socialv1.GetUserRequest{Id: id})
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	writeJSON(w, r, http.StatusOK, userDTO(resp))
}

// UserPosts — GET /v1/users/:id/posts. The user's authored posts.
func (h *FoundationHandlers) UserPosts(w http.ResponseWriter, r *http.Request) {
	h.serveAuthorPosts(w, r, chi.URLParam(r, "userId"))
}

// serveAuthorPosts is the shared body for agent + user post timelines:
// AuthorPosts(author=id, viewer=caller) so liked_by_me is correct.
func (h *FoundationHandlers) serveAuthorPosts(
	w http.ResponseWriter, r *http.Request, authorID string,
) {
	userID, cancel, err := h.userCtx(r)
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	defer cancel()

	limit, cursor := pageParams(r)
	resp, err := h.feed.AuthorPosts(r.Context(), &socialv1.AuthorPostsRequest{
		AuthorId: authorID,
		ViewerId: userID,
		Limit:    &limit,
		Cursor:   cursor,
	})
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	writeJSON(w, r, http.StatusOK, filterFeed(feedPageDTO(resp), h.modView(r.Context(), userID)))
}

// ---- Part 5: posts --------------------------------------------------------------

type createPostBody struct {
	Content    string            `json:"content"`
	Metadata   map[string]string `json:"metadata"`
	Visibility string            `json:"visibility"`
}

func (h *FoundationHandlers) CreatePost(w http.ResponseWriter, r *http.Request) {
	userID, cancel, err := h.userCtx(r)
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	defer cancel()
	if !h.ensureCanAct(w, r) {
		return
	}
	h.metrics.postWrite("create")

	var body createPostBody
	if !decodeBody(w, r, &body) {
		return
	}
	// The author is ALWAYS the token user posting as themselves —
	// agent/admin posts enter Social through the internal publication
	// path (Nexus), never through this public BFF.
	post, err := h.posts.Create(r.Context(), &socialv1.CreatePostRequest{
		AuthorId:   userID,
		AuthorType: socialv1.AuthorType_AUTHOR_TYPE_USER,
		Content:    body.Content,
		Metadata:   body.Metadata,
		Visibility: visibilityFromString(body.Visibility),
	})
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	writeJSON(w, r, http.StatusCreated, postDTO(post))
}

func (h *FoundationHandlers) GetPost(w http.ResponseWriter, r *http.Request) {
	userID, cancel, err := h.userCtx(r)
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	defer cancel()

	post, err := h.posts.Get(r.Context(), &socialv1.GetPostRequest{
		Id: chi.URLParam(r, "postId"),
	})
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	// CONSOLE-SOCIAL-B: single post detail must respect admin-hidden content +
	// non-active authors (consumer read model). Hidden ⇒ 404 (not leaked).
	if v := h.modView(r.Context(), userID); v != nil {
		if v.PostHidden(post.GetId()) || v.AuthorHidden(post.GetAuthorId()) {
			writeError(w, http.StatusNotFound, "post_not_found", "")
			return
		}
	}
	writeJSON(w, r, http.StatusOK, postDTO(post))
}

func (h *FoundationHandlers) DeletePost(w http.ResponseWriter, r *http.Request) {
	userID, cancel, err := h.userCtx(r)
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	defer cancel()
	h.metrics.postWrite("delete")

	// Ownership validation happens in SOCIAL (requester == author);
	// the gateway only guarantees requester_id is the token user.
	_, err = h.posts.Delete(r.Context(), &socialv1.DeletePostRequest{
		Id:          chi.URLParam(r, "postId"),
		RequesterId: userID,
	})
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- Part 6: comments --------------------------------------------------------------

type createCommentBody struct {
	ParentID string `json:"parent_id"`
	Content  string `json:"content"`
}

func (h *FoundationHandlers) CreateComment(w http.ResponseWriter, r *http.Request) {
	userID, cancel, err := h.userCtx(r)
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	defer cancel()
	if !h.ensureCanAct(w, r) {
		return
	}
	h.metrics.postWrite("comment")

	var body createCommentBody
	if !decodeBody(w, r, &body) {
		return
	}
	// Depth (max 2) is enforced by Social; an attempt to nest deeper
	// surfaces as InvalidArgument → 400.
	comment, err := h.posts.CreateComment(r.Context(), &socialv1.CreateCommentRequest{
		PostId:     chi.URLParam(r, "postId"),
		ParentId:   body.ParentID,
		AuthorId:   userID,
		AuthorType: socialv1.AuthorType_AUTHOR_TYPE_USER,
		Content:    body.Content,
	})
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	writeJSON(w, r, http.StatusCreated, commentDTO(comment))
}

func (h *FoundationHandlers) ListComments(w http.ResponseWriter, r *http.Request) {
	userID, cancel, err := h.userCtx(r)
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	defer cancel()

	limit, cursor := pageParams(r)
	resp, err := h.posts.ListComments(r.Context(), &socialv1.ListCommentsRequest{
		PostId: chi.URLParam(r, "postId"),
		Limit:  &limit,
		Cursor: cursor,
	})
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	// Store-A: collapse comments from blocked/banned authors or admin-hidden.
	view := h.modView(r.Context(), userID)
	comments := make([]CommentDTO, 0, len(resp.GetComments()))
	for _, c := range resp.GetComments() {
		if view.AuthorHidden(c.GetAuthorId()) || view.CommentHidden(c.GetId()) {
			continue
		}
		comments = append(comments, commentDTO(c))
	}
	writeJSON(w, r, http.StatusOK, CommentPageDTO{
		Comments:   comments,
		NextCursor: resp.GetNextCursor(),
	})
}

// ---- Part 7: likes -----------------------------------------------------------------

func (h *FoundationHandlers) LikePost(w http.ResponseWriter, r *http.Request) {
	h.toggleLike(w, r, true)
}

func (h *FoundationHandlers) UnlikePost(w http.ResponseWriter, r *http.Request) {
	h.toggleLike(w, r, false)
}

func (h *FoundationHandlers) toggleLike(w http.ResponseWriter, r *http.Request, like bool) {
	userID, cancel, err := h.userCtx(r)
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	defer cancel()
	// CONSOLE-SOCIAL-B: adding a like is a participation mutation — gate
	// banned/suspended users. Removing a like (reductive) stays allowed.
	if like && !h.ensureCanAct(w, r) {
		return
	}
	postID := chi.URLParam(r, "postId")

	if like {
		h.metrics.reaction("like")
		_, err = h.posts.Like(r.Context(), &socialv1.LikePostRequest{
			PostId: postID, UserId: userID,
		})
	} else {
		h.metrics.reaction("unlike")
		_, err = h.posts.Unlike(r.Context(), &socialv1.UnlikePostRequest{
			PostId: postID, UserId: userID,
		})
	}
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	// Idempotent + optimistic-update ready: the echo confirms the
	// final state regardless of whether the toggle was a no-op.
	writeJSON(w, r, http.StatusOK, PostReactionDTO{PostID: postID, Liked: like})
}

// ---- Parts 8 + 9: follow + mute ------------------------------------------------------

func (h *FoundationHandlers) Follow(w http.ResponseWriter, r *http.Request) {
	h.relationshipAction(w, r, "follow")
}

func (h *FoundationHandlers) Unfollow(w http.ResponseWriter, r *http.Request) {
	h.relationshipAction(w, r, "unfollow")
}

func (h *FoundationHandlers) Mute(w http.ResponseWriter, r *http.Request) {
	h.relationshipAction(w, r, "mute")
}

func (h *FoundationHandlers) Unmute(w http.ResponseWriter, r *http.Request) {
	h.relationshipAction(w, r, "unmute")
}

func (h *FoundationHandlers) relationshipAction(
	w http.ResponseWriter, r *http.Request, action string,
) {
	userID, cancel, err := h.userCtx(r)
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	defer cancel()
	// CONSOLE-SOCIAL-B: following is a participation mutation — gate banned/
	// suspended users. Unfollow/mute/unmute (reductive/personal) stay allowed.
	if action == "follow" && !h.ensureCanAct(w, r) {
		return
	}
	targetID := chi.URLParam(r, "targetId")
	h.metrics.relationship(action)

	// The gateway never distinguishes user vs agent targets — Social
	// owns validation (Part 8 rule).
	dto := RelationshipDTO{TargetID: targetID}
	switch action {
	case "follow":
		rel, ferr := h.rels.Follow(r.Context(), &socialv1.FollowRequest{
			SourceUserId: userID, TargetUserId: targetID,
		})
		// Re-following is mobile-retry-friendly: AlreadyExists → the
		// state the client wanted. Treat as success.
		if ferr != nil && status.Code(ferr) != codes.AlreadyExists {
			writeGrpcError(w, r, ferr)
			return
		}
		dto.Followed = true
		dto.Muted = rel.GetMuted()
	case "unfollow":
		if _, ferr := h.rels.Unfollow(r.Context(), &socialv1.UnfollowRequest{
			SourceUserId: userID, TargetUserId: targetID,
		}); ferr != nil && status.Code(ferr) != codes.NotFound {
			writeGrpcError(w, r, ferr)
			return
		}
	case "mute":
		rel, ferr := h.rels.Mute(r.Context(), &socialv1.MuteRequest{
			SourceUserId: userID, TargetUserId: targetID,
		})
		if ferr != nil {
			writeGrpcError(w, r, ferr)
			return
		}
		dto.Followed = true
		dto.Muted = rel.GetMuted()
	case "unmute":
		rel, ferr := h.rels.Unmute(r.Context(), &socialv1.UnmuteRequest{
			SourceUserId: userID, TargetUserId: targetID,
		})
		if ferr != nil {
			writeGrpcError(w, r, ferr)
			return
		}
		dto.Followed = true
		dto.Muted = rel.GetMuted()
	}
	writeJSON(w, r, http.StatusOK, dto)
}

// ---- shared helpers --------------------------------------------------------------------

// decodeBody reads + decodes a JSON body with the oversized-payload
// guard. Returns false (response already written) on failure.
func decodeBody(w http.ResponseWriter, r *http.Request, into any) bool {
	defer func() { _, _ = io.Copy(io.Discard, r.Body) }()
	dec := json.NewDecoder(io.LimitReader(r.Body, maxBodyBytes))
	if err := dec.Decode(into); err != nil {
		if errors.Is(err, io.EOF) {
			writeError(w, http.StatusBadRequest, "empty_body", "")
			return false
		}
		writeError(w, http.StatusBadRequest, "invalid_json", "")
		return false
	}
	return true
}

func looksLikeUUID(s string) bool {
	return len(s) == 36 && s[8] == '-' && s[13] == '-' && s[18] == '-' && s[23] == '-'
}
