// /v1/hub/bundle + /v1/hub/communities/{community_id} handlers.
package social

import (
	"context"
	"net/http"
	"sort"
	"sync"

	"github.com/go-chi/chi/v5"
	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"golang.org/x/sync/errgroup"
	"google.golang.org/grpc/codes"

	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/authmw"
)

// GetHubBundle handles GET /v1/hub/bundle?segment=mine|hot|fresh.
//
// Per the legacy BFF contract:
//   - segment defaults to "hot" when absent (the legacy BFF default).
//   - invalid segment → 400 invalid_segment.
//
// Segment semantics (W2.2.1 — real implementations for all three):
//   - mine  — communities the authenticated user is a member of,
//     ordered by recency of join. Backed by
//     Community.ListForUser (added W2.2.1). Discussions
//     aggregated across those communities.
//   - hot   — top communities by active_now then member_count,
//     newest discussions across them. Backed by
//     Community.List with sort=HOT.
//   - fresh — newest communities by created_at, newest discussions
//     across them. Backed by Community.List with sort=NEWEST
//     (the pre-W2.2.1 default).
func (h *Handlers) GetHubBundle(w http.ResponseWriter, r *http.Request) {
	segment := r.URL.Query().Get("segment")
	if segment == "" {
		segment = "hot"
	}
	switch segment {
	case "mine", "hot", "fresh":
	default:
		writeError(w, http.StatusBadRequest, "invalid_segment", segment)
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), h.upstreamTimeout)
	defer cancel()

	// 1. Fetch the communities for this segment. "mine" requires an
	// authenticated user_id; "hot"/"fresh" don't (curated public
	// surface). authmw is mounted on the route regardless — the
	// user_id is always available here.
	protoCommunities, err := h.communitiesForSegment(ctx, r, segment)
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}

	// 2. Fan-out the latest 2 discussions per community. Truncate the
	// merged set to hubDiscussionsCap so the response stays bounded.
	type bucket struct {
		discussions []*socialv1.Discussion
	}
	buckets := make([]bucket, len(protoCommunities))
	var mu sync.Mutex

	g, gctx := errgroup.WithContext(ctx)
	g.SetLimit(8)
	perCommLimit := int32(2)
	for i, c := range protoCommunities {
		i, c := i, c
		g.Go(func() error {
			resp, err := h.client.Discussion.ListForCommunity(gctx, &socialv1.ListDiscussionsRequest{
				CommunityId: c.Id,
				Limit:       &perCommLimit,
			})
			if err != nil {
				return err
			}
			mu.Lock()
			buckets[i] = bucket{discussions: resp.Discussions}
			mu.Unlock()
			return nil
		})
	}
	if err := g.Wait(); err != nil {
		writeGrpcError(w, r, err)
		return
	}

	// 3. Build response.
	hubComms := make([]HubCommunity, 0, len(protoCommunities))
	for _, c := range protoCommunities {
		hubComms = append(hubComms, communityToHub(c))
	}
	discussions := make([]HubDiscussion, 0, hubDiscussionsCap)
	for _, b := range buckets {
		for _, d := range b.discussions {
			discussions = append(discussions, discussionToHub(d))
		}
	}
	sort.Slice(discussions, func(i, j int) bool {
		return discussions[i].LastActivityTs > discussions[j].LastActivityTs
	})
	if len(discussions) > hubDiscussionsCap {
		discussions = discussions[:hubDiscussionsCap]
	}

	writeJSON(w, r, http.StatusOK, HubBundleResponse{
		Communities: hubComms,
		Tipsters:    []any{}, // see DTO comment
		Discussions: discussions,
	})
}

// communitiesForSegment fetches the community list for the requested
// Hub segment. Returns the raw protos so the caller can re-use them
// both as the response's `communities` array AND as the fan-out keys
// for discussion lookups.
//
// Segment routing:
//   - mine  → Community.ListForUser(user_id from ctx)
//   - hot   → Community.List(sort=HOT)
//   - fresh → Community.List(sort=NEWEST)
//
// Any unknown segment is a programmer error here (validation happens
// in the handler). We panic-default to NEWEST defensively.
func (h *Handlers) communitiesForSegment(ctx context.Context, r *http.Request, segment string) ([]*socialv1.Community, error) {
	limit := int32(hubCommunitiesCap)

	switch segment {
	case "mine":
		userID, ok := authmw.UserID(r.Context())
		if !ok {
			// authmw wasn't applied — defensive 401 surface via the
			// generic error mapper. Should never happen if the route
			// is registered correctly.
			return nil, errAuthMissing
		}
		resp, err := h.client.Community.ListForUser(ctx, &socialv1.ListCommunitiesForUserRequest{
			UserId: userID.String(),
			Limit:  &limit,
		})
		if err != nil {
			return nil, err
		}
		return resp.Communities, nil

	case "hot":
		resp, err := h.client.Community.List(ctx, &socialv1.ListCommunitiesRequest{
			Limit: &limit,
			Sort:  socialv1.CommunityListSort_COMMUNITY_LIST_SORT_HOT,
		})
		if err != nil {
			return nil, err
		}
		return resp.Communities, nil

	default: // "fresh" — and the safety net
		resp, err := h.client.Community.List(ctx, &socialv1.ListCommunitiesRequest{
			Limit: &limit,
			Sort:  socialv1.CommunityListSort_COMMUNITY_LIST_SORT_NEWEST,
		})
		if err != nil {
			return nil, err
		}
		return resp.Communities, nil
	}
}

// GetCommunityDetail handles GET /v1/hub/communities/{community_id}.
//
// the legacy BFF returned 404 here as a stub — this is the first real
// implementation. Shape locked in dto.go.
func (h *Handlers) GetCommunityDetail(w http.ResponseWriter, r *http.Request) {
	communityID := chi.URLParam(r, "community_id")
	if communityID == "" {
		writeError(w, http.StatusBadRequest, "missing_community_id", "")
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), h.upstreamTimeout)
	defer cancel()

	// 1. Get the community itself. NotFound short-circuits to 404
	// (rather than 200 with an empty body) — matches REST semantics.
	c, err := h.client.Community.Get(ctx, &socialv1.GetCommunityRequest{Id: communityID})
	if err != nil {
		if errIs(err, codes.NotFound) {
			writeError(w, http.StatusNotFound, "community_not_found", "")
			return
		}
		writeGrpcError(w, r, err)
		return
	}

	// 2. Discussions for it. Cursor flows through verbatim.
	cursor := r.URL.Query().Get("cursor")
	limit := int32(communityDiscussionsCap)
	listReq := &socialv1.ListDiscussionsRequest{
		CommunityId: communityID,
		Limit:       &limit,
	}
	if cursor != "" {
		listReq.Cursor = &cursor
	}
	dResp, err := h.client.Discussion.ListForCommunity(ctx, listReq)
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}

	out := CommunityDetailResponse{
		Community:   communityToHub(c),
		Discussions: make([]HubDiscussion, 0, len(dResp.Discussions)),
	}
	for _, d := range dResp.Discussions {
		out.Discussions = append(out.Discussions, discussionToHub(d))
	}
	if dResp.NextCursor != nil && *dResp.NextCursor != "" {
		nc := *dResp.NextCursor
		out.NextCursor = &nc
	}
	writeJSON(w, r, http.StatusOK, out)
}

// ---- translators ----

func communityToHub(c *socialv1.Community) HubCommunity {
	return HubCommunity{
		ID:          c.Id,
		Slug:        c.Slug,
		Name:        c.Name,
		Topic:       c.Topic,
		Kind:        kindToWire(c.Kind),
		AccentColor: c.AccentColor,
		MemberCount: c.MemberCount,
	}
}

func discussionToHub(d *socialv1.Discussion) HubDiscussion {
	return HubDiscussion{
		ID:             d.Id,
		CommunityID:    d.CommunityId,
		AuthorID:       d.AuthorId,
		Title:          d.Title,
		ReplyCount:     d.ReplyCount,
		LastActivityTs: formatTs(d.LastActivityTs.AsTime()),
	}
}

// kindToWire maps the proto enum back to the lowercase string the legacy BFF
// (and the Flutter client) expects.
func kindToWire(k socialv1.CommunityKind) string {
	switch k {
	case socialv1.CommunityKind_COMMUNITY_KIND_COMPETITION:
		return "competition"
	case socialv1.CommunityKind_COMMUNITY_KIND_TOPIC:
		return "topic"
	default:
		return "unspecified"
	}
}
