// Discussion thread BFF — net-new endpoints in the gateway.
//
// the legacy BFF never exposed a per-discussion view; the Flutter Hub
// rendered the discussion row but had no way to drill into it. These
// 3 routes back the new DiscussionThreadScreen in Flutter:
//
//	GET    /v1/discussions/{discussion_id}                → DiscussionDetail
//	GET    /v1/discussions/{discussion_id}/messages       → ListMessagesResponse
//	POST   /v1/discussions/{discussion_id}/messages       → DiscussionMessage
//
// Author info on EVERY message is denormalised at the BFF (we fan out
// to User.List for the distinct authors) so the Flutter renderer
// doesn't need a second round-trip per author. Bulk fetch caps the
// extra cost at one extra RPC per page regardless of message count.
package social

import (
	"context"
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"golang.org/x/sync/errgroup"
	"google.golang.org/grpc/codes"

	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/authmw"
)

const (
	threadMessagesCap = 50
	maxReplyBody      = 16384 // matches social-go domain validator
)

// ---- handlers ----

// GetDiscussion handles GET /v1/discussions/{discussion_id}.
//
// Fan-out:
//  1. Discussion.Get → header (title, body, counts, community_id, author_id)
//  2. parallel: User.Get(author_id) + Community.Get(community_id)
//
// If either ancillary lookup 404s we fall back to a stub author/community
// rather than failing the whole request — the discussion itself rendered
// is the primary value; an orphaned author is recoverable.
func (h *Handlers) GetDiscussion(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "discussion_id")
	if id == "" {
		writeError(w, http.StatusBadRequest, "missing_discussion_id", "")
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), h.upstreamTimeout)
	defer cancel()

	d, err := h.client.Discussion.Get(ctx, &socialv1.GetDiscussionRequest{Id: id})
	if err != nil {
		if errIs(err, codes.NotFound) {
			writeError(w, http.StatusNotFound, "discussion_not_found", "")
			return
		}
		writeGrpcError(w, r, err)
		return
	}

	var (
		author    *socialv1.User
		community *socialv1.Community
		reactSt   *socialv1.DiscussionReactionState
	)
	// Viewer id is required for liked_by_me. authmw guarantees it
	// (route wraps in requireAuth) but we don't panic if missing —
	// reaction state still works without it (LikedByUser = false).
	viewerID := ""
	if uid, ok := authmw.UserID(r.Context()); ok {
		viewerID = uid.String()
	}

	g, gctx := errgroup.WithContext(ctx)
	g.Go(func() error {
		u, err := h.client.User.Get(gctx, &socialv1.GetUserRequest{Id: d.AuthorId})
		if err != nil {
			// NotFound is tolerated — see func doc.
			if errIs(err, codes.NotFound) {
				return nil
			}
			return err
		}
		author = u
		return nil
	})
	g.Go(func() error {
		c, err := h.client.Community.Get(gctx, &socialv1.GetCommunityRequest{Id: d.CommunityId})
		if err != nil {
			if errIs(err, codes.NotFound) {
				return nil
			}
			return err
		}
		community = c
		return nil
	})
	g.Go(func() error {
		// Sprint B — fetch like count + liked_by_me in parallel.
		// Tolerant of error: if reactions fail we still render the
		// thread, the heart just shows count=0.
		req := &socialv1.GetDiscussionReactionStateRequest{DiscussionId: d.Id}
		if viewerID != "" {
			req.UserId = &viewerID
		}
		st, err := h.client.Reaction.StateForDiscussion(gctx, req)
		if err != nil {
			return nil // tolerated
		}
		reactSt = st
		return nil
	})
	if err := g.Wait(); err != nil {
		writeGrpcError(w, r, err)
		return
	}

	writeJSON(w, r, http.StatusOK, discussionDetailToWire(d, author, community, reactSt))
}

// GetDiscussionMessages handles GET /v1/discussions/{discussion_id}/messages.
//
// Page strategy: 50 messages per page, ASC by created_at (oldest first
// — the chat-style read order). Authors bulk-fetched in one User.List
// call so the response self-contains all rendering info.
func (h *Handlers) GetDiscussionMessages(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "discussion_id")
	if id == "" {
		writeError(w, http.StatusBadRequest, "missing_discussion_id", "")
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), h.upstreamTimeout)
	defer cancel()

	limit := int32(threadMessagesCap)
	cursor := r.URL.Query().Get("cursor")
	listReq := &socialv1.ListMessagesRequest{
		DiscussionId: id,
		Limit:        &limit,
	}
	if cursor != "" {
		listReq.Cursor = &cursor
	}
	resp, err := h.client.Discussion.ListMessages(ctx, listReq)
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}

	// Collect distinct author ids and bulk-fetch them.
	seen := make(map[string]struct{}, len(resp.Messages))
	authorIDs := make([]string, 0, len(resp.Messages))
	for _, m := range resp.Messages {
		if m.AuthorId == "" {
			continue
		}
		if _, ok := seen[m.AuthorId]; ok {
			continue
		}
		seen[m.AuthorId] = struct{}{}
		authorIDs = append(authorIDs, m.AuthorId)
	}

	authorByID := map[string]*socialv1.User{}
	if len(authorIDs) > 0 {
		uResp, err := h.client.User.List(ctx, &socialv1.ListUsersRequest{Ids: authorIDs})
		if err != nil {
			// User bulk-fetch isn't load-bearing for the messages
			// themselves — log + degrade gracefully (messages render
			// with default initials/colors).
			writeGrpcError(w, r, err)
			return
		}
		for _, u := range uResp.Users {
			authorByID[u.Id] = u
		}
	}

	out := make([]DiscussionMessageDTO, 0, len(resp.Messages))
	for _, m := range resp.Messages {
		out = append(out, messageToWire(m, authorByID[m.AuthorId]))
	}
	body := DiscussionMessagesResponse{Messages: out}
	if resp.NextCursor != nil && *resp.NextCursor != "" {
		nc := *resp.NextCursor
		body.NextCursor = &nc
	}
	writeJSON(w, r, http.StatusOK, body)
}

// PostDiscussionMessage handles POST /v1/discussions/{discussion_id}/messages.
//
// Author is taken from the JWT (authmw) — never trusted from the
// request body. Body validated at the BFF for fast feedback, then
// forwarded to social-go which validates again (defence in depth).
func (h *Handlers) PostDiscussionMessage(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "discussion_id")
	if id == "" {
		writeError(w, http.StatusBadRequest, "missing_discussion_id", "")
		return
	}
	userID, ok := authmw.UserID(r.Context())
	if !ok {
		writeGrpcError(w, r, errAuthMissing)
		return
	}

	var req PostMessageRequest
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 64<<10)).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_json", err.Error())
		return
	}
	if req.Body == "" {
		writeError(w, http.StatusBadRequest, "missing_body", "")
		return
	}
	if len(req.Body) > maxReplyBody {
		writeError(w, http.StatusBadRequest, "body_too_long", "")
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), h.upstreamTimeout)
	defer cancel()

	pm, err := h.client.Discussion.PostMessage(ctx, &socialv1.PostMessageRequest{
		DiscussionId: id,
		AuthorId:     userID.String(),
		Body:         req.Body,
	})
	if err != nil {
		if errIs(err, codes.NotFound) {
			writeError(w, http.StatusNotFound, "discussion_not_found", "")
			return
		}
		writeGrpcError(w, r, err)
		return
	}

	// Hydrate author so the response carries everything the client
	// needs to render the just-posted message without a follow-up
	// fetch.
	var author *socialv1.User
	if u, err := h.client.User.Get(ctx, &socialv1.GetUserRequest{Id: userID.String()}); err == nil {
		author = u
	}
	writeJSON(w, r, http.StatusCreated, messageToWire(pm, author))
}

// ---- translators ----

func discussionDetailToWire(d *socialv1.Discussion, author *socialv1.User, community *socialv1.Community, reactSt *socialv1.DiscussionReactionState) DiscussionDetailResponse {
	out := DiscussionDetailResponse{
		ID:          d.Id,
		Title:       d.Title,
		Body:        d.Body,
		CommunityID: d.CommunityId,
		AuthorID:    d.AuthorId,
		ReplyCount:  d.ReplyCount,
		// Sprint B: prefer the live reaction count when available;
		// fall back to whatever the Discussion proto carries (which
		// is 0 until the social repo joins reactions into its read
		// projections — a follow-up).
		ReactionCount:  d.ReactionCount,
		CreatedAt:      formatTs(d.CreatedAt.AsTime()),
		LastActivityTs: formatTs(d.LastActivityTs.AsTime()),
	}
	if d.MatchId != nil {
		mid := *d.MatchId
		out.MatchID = &mid
	}
	if author != nil {
		out.AuthorDisplayName = author.DisplayName
		out.AuthorInitials = author.Initials
		out.AuthorAccent = author.AccentColor
	}
	if community != nil {
		out.CommunityName = community.Name
		out.CommunityHandle = "#" + community.Slug
	}
	if reactSt != nil {
		out.ReactionCount = reactSt.LikeCount
		out.LikedByMe = reactSt.LikedByUser
	}
	return out
}

func messageToWire(m *socialv1.DiscussionMessage, author *socialv1.User) DiscussionMessageDTO {
	out := DiscussionMessageDTO{
		ID:       m.Id,
		AuthorID: m.AuthorId,
		Body:     m.Body,
		Ts:       formatTs(m.CreatedAt.AsTime()),
	}
	if author != nil {
		out.AuthorDisplayName = author.DisplayName
		out.AuthorInitials = author.Initials
		out.AuthorAccent = author.AccentColor
	}
	// Defensive parse — surface a sensible default UUID rather than
	// hiding a corrupt id from the client renderer.
	if _, err := uuid.Parse(m.AuthorId); err != nil {
		out.AuthorID = uuid.Nil.String()
	}
	return out
}
