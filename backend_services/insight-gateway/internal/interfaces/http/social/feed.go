// /v1/feed handler.
//
// Algorithm (mirrors the legacy BFF bff.py:get_feed):
//  1. List up to 20 communities (newest-first).
//  2. For each, concurrently fetch the latest 5 discussions.
//  3. Flatten, sort by last_activity_ts descending.
//  4. Return the top 50.
//
// Pagination at the BFF layer: NONE. the legacy BFF never had it; adding it
// here would silently change the wire contract. The cap-at-50 absorbs
// the Hub bundle's "ver mais" intent.
//
// Concurrency: errgroup fan-out so 20 round-trips of ~10ms each take
// ~10ms wall time instead of 200ms. Bounded by the request's parent
// context — if the client disconnects, the whole fan-out cancels.
package social

import (
	"context"
	"net/http"
	"sort"
	"sync"
	"time"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"golang.org/x/sync/errgroup"
)

func (h *Handlers) GetFeed(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), h.upstreamTimeout)
	defer cancel()

	// 1. communities
	limit := int32(feedCommunityFanout)
	commResp, err := h.client.Community.List(ctx, &socialv1.ListCommunitiesRequest{
		Limit: &limit,
	})
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}

	// 2. discussions per community — concurrent fan-out
	type bucket struct {
		communityID string
		discussions []*socialv1.Discussion
	}
	buckets := make([]bucket, len(commResp.Communities))
	var mu sync.Mutex

	g, gctx := errgroup.WithContext(ctx)
	// Cap concurrency at 8 — protects insight-social from a burst when
	// commResp returns many communities. Tunable; matches the broker
	// partition count for symmetry.
	g.SetLimit(8)

	perCommLimit := int32(feedDiscussionsPerCommunity)
	for i, c := range commResp.Communities {
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
			buckets[i] = bucket{communityID: c.Id, discussions: resp.Discussions}
			mu.Unlock()
			return nil
		})
	}
	if err := g.Wait(); err != nil {
		writeGrpcError(w, r, err)
		return
	}

	// 3. flatten + sort
	items := make([]FeedItem, 0, len(commResp.Communities)*feedDiscussionsPerCommunity)
	for _, b := range buckets {
		for _, d := range b.discussions {
			items = append(items, discussionToFeedItem(d))
		}
	}
	sort.Slice(items, func(i, j int) bool {
		// Newest first; string comparison on RFC3339 timestamps is
		// lexicographic-correct because the format is fixed-width.
		return items[i].Ts > items[j].Ts
	})

	// 4. cap
	if len(items) > feedItemsCap {
		items = items[:feedItemsCap]
	}
	writeJSON(w, r, http.StatusOK, FeedResponse{Items: items})
}

// discussionToFeedItem translates a Discussion proto into a FeedItem.
// kind="discussion" always — we don't yet stream raw signals into the
// feed (that would require Signal.ListAcross which doesn't exist).
func discussionToFeedItem(d *socialv1.Discussion) FeedItem {
	item := FeedItem{
		Kind:     "discussion",
		ID:       d.Id,
		AuthorID: d.AuthorId,
		Body:     d.Title, // the legacy BFF used title-or-body fallback; title is always present
		Ts:       formatTs(d.LastActivityTs.AsTime()),
	}
	if d.MatchId != nil {
		mid := *d.MatchId
		item.MatchID = &mid
	}
	return item
}

// formatTs is the canonical wire timestamp format. Aligned with
// the legacy BFF which serialises datetimes via FastAPI's default ISO-8601
// (RFC3339 with "T" separator + "Z" suffix for UTC).
func formatTs(t time.Time) string {
	return t.UTC().Format(time.RFC3339Nano)
}
