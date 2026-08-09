// Package feed implements query-time feed generation — Sprint 3
// (Social Foundation) Parts 8 + 9.
//
// NO fanout-on-write. NO materialized timelines. Every read assembles
// the page from the relationship graph + posts tables at query time.
//
// GLOBAL feed (personalized):
//  1. posts from followed agents — MANDATORY inclusion (product
//     rule: no ranking, relevance score or optimization may remove
//     them; only unfollow or mute)
//  2. posts from followed users
//  3. relevant public posts (recent public fill)
//  4. sponsored slots — placeholder only in V1 (always empty)
//
// Agent priority: when timestamps are close (same time bucket),
// agent posts sort ahead of user posts.
//
// FOLLOWING feed: followed users + followed agents only, purely
// chronological, no public discovery.
package feed

import (
	"context"
	"encoding/base64"
	"sort"
	"strconv"
	"time"

	"github.com/google/uuid"

	domfeed "github.com/konoha-labs/insight-social/internal/domain/feed"
	dompost "github.com/konoha-labs/insight-social/internal/domain/post"
	"github.com/konoha-labs/insight-social/internal/observability"
)

const (
	defaultLimit = 30
	maxLimit     = 100
	// Posts whose timestamps fall in the same bucket count as
	// "close"; within a bucket agents win the tie.
	priorityBucket = 10 * time.Minute
)

// AgentDirectory is the slice of the agent service the feed needs.
type AgentDirectory interface {
	ActiveIDs(ctx context.Context) ([]uuid.UUID, error)
}

// FollowGraph is the slice of the relationship repository the feed
// needs. excludeMuted=true is the feed view (mute rule).
type FollowGraph interface {
	FollowingIDs(ctx context.Context, userID uuid.UUID, excludeMuted bool) ([]uuid.UUID, error)
}

type Service struct {
	posts  domfeed.Repository
	graph  FollowGraph
	agents AgentDirectory
}

func New(posts domfeed.Repository, graph FollowGraph, agents AgentDirectory) *Service {
	return &Service{posts: posts, graph: graph, agents: agents}
}

// Global assembles the personalized global feed.
// `competitionID` is the rail selection under the header, or nil for "todos".
// It narrows the CANDIDATE SET — the mandatory-inclusion rule below still
// holds within it. A followed agent posting about another competition is not
// demoted; it is outside what the viewer asked to see.
func (s *Service) Global(
	ctx context.Context, userID uuid.UUID, limit int, cursor string,
	competitionID *uuid.UUID,
) (domfeed.Page, error) {
	observability.FeedReadsTotal.WithLabelValues("global").Inc()
	limit = clampLimit(limit)
	before := decodeCursor(cursor)

	followedAgents, followedUsers, err := s.splitFollowing(ctx, userID)
	if err != nil {
		return domfeed.Page{}, err
	}
	muted, err := s.mutedSet(ctx, userID)
	if err != nil {
		return domfeed.Page{}, err
	}

	// 1. MANDATORY: every followed agent's post in the window. These
	// are selected FIRST and can never be displaced by other content.
	var agentItems []*domfeed.Item
	if len(followedAgents) > 0 {
		agentItems, err = s.posts.PostsByAuthors(ctx, domfeed.CandidateQuery{
			AuthorIDs: followedAgents, Before: before, CompetitionID: competitionID, Limit: limit,
		})
		if err != nil {
			return domfeed.Page{}, err
		}
		for _, item := range agentItems {
			item.FromFollowedAgent = true
		}
	}

	// 2. Followed users' posts.
	var userItems []*domfeed.Item
	if len(followedUsers) > 0 && len(agentItems) < limit {
		userItems, err = s.posts.PostsByAuthors(ctx, domfeed.CandidateQuery{
			AuthorIDs: followedUsers, Before: before, CompetitionID: competitionID,
			Limit: limit - len(agentItems),
		})
		if err != nil {
			return domfeed.Page{}, err
		}
	}

	// 3. Relevant public posts fill the remainder.
	items := append(append([]*domfeed.Item{}, agentItems...), userItems...)
	if remaining := limit - len(items); remaining > 0 {
		public, err := s.posts.RecentPublic(ctx, before, remaining+len(items), competitionID)
		if err != nil {
			return domfeed.Page{}, err
		}
		seen := make(map[uuid.UUID]bool, len(items))
		for _, item := range items {
			seen[item.Post.ID] = true
		}
		for _, item := range public {
			if remaining == 0 {
				break
			}
			// Mute rule: muted authors never re-enter through the public fill.
			//
			// AZTECA-POSTS-B (feed self-post semantics): a self-authored PUBLIC
			// post DOES participate in the public fill by normal recency ranking
			// — it is NOT pinned or prioritized, just no longer special-cased out.
			// This resolves the "create → appears → disappears after refresh"
			// contradiction: the authoritative Global feed can now return the
			// user's own recent public post instead of it surviving only as an
			// optimistic client insert. Deduped by `seen` (own posts arrive only
			// via this fill — a user never follows themselves — so no duplicate is
			// possible), and Profile▸Activity remains the reliable per-author
			// surface independent of feed ranking.
			if seen[item.Post.ID] || muted[item.Post.AuthorID] {
				continue
			}
			items = append(items, item)
			remaining--
		}
	}
	// 4. Sponsored slots: placeholder only — intentionally empty.

	sortWithAgentPriority(items)
	out := page(items)
	if err := s.applyLiked(ctx, userID, out.Items); err != nil {
		return domfeed.Page{}, err
	}
	return out, nil
}

// Following assembles the chronological following feed: followed
// users + followed agents only. No public discovery.
// Takes the same rail selection as Global. The rail sits above both tabs, so a
// filter that applied to one and not the other would look like a bug to the
// person who switched tabs — and the proto field is on FeedRequest, which
// serves both RPCs.
func (s *Service) Following(
	ctx context.Context, userID uuid.UUID, limit int, cursor string,
	competitionID *uuid.UUID,
) (domfeed.Page, error) {
	observability.FeedReadsTotal.WithLabelValues("following").Inc()
	limit = clampLimit(limit)
	before := decodeCursor(cursor)

	followedAgents, followedUsers, err := s.splitFollowing(ctx, userID)
	if err != nil {
		return domfeed.Page{}, err
	}
	authorIDs := append(append([]uuid.UUID{}, followedAgents...), followedUsers...)
	if len(authorIDs) == 0 {
		return domfeed.Page{}, nil
	}
	agentSet := toSet(followedAgents)
	items, err := s.posts.PostsByAuthors(ctx, domfeed.CandidateQuery{
		AuthorIDs: authorIDs, Before: before, Limit: limit,
		CompetitionID: competitionID,
	})
	if err != nil {
		return domfeed.Page{}, err
	}
	for _, item := range items {
		item.FromFollowedAgent = agentSet[item.Post.AuthorID]
	}
	// Chronological, newest first.
	sort.SliceStable(items, func(i, j int) bool {
		return items[i].Post.CreatedAt.After(items[j].Post.CreatedAt)
	})
	out := page(items)
	if err := s.applyLiked(ctx, userID, out.Items); err != nil {
		return domfeed.Page{}, err
	}
	return out, nil
}

// AuthorPosts returns one author's posts (a user OR an agent), newest
// first, with liked_by_me computed for the viewer. Powers the public
// profile + agent-posts surfaces.
func (s *Service) AuthorPosts(
	ctx context.Context, authorID, viewerID uuid.UUID, limit int, cursor string,
) (domfeed.Page, error) {
	observability.FeedReadsTotal.WithLabelValues("author").Inc()
	limit = clampLimit(limit)
	before := decodeCursor(cursor)
	items, err := s.posts.PostsByAuthors(ctx, domfeed.CandidateQuery{
		AuthorIDs: []uuid.UUID{authorID}, Before: before, Limit: limit,
	})
	if err != nil {
		return domfeed.Page{}, err
	}
	out := page(items)
	if err := s.applyLiked(ctx, viewerID, out.Items); err != nil {
		return domfeed.Page{}, err
	}
	return out, nil
}

// applyLiked batch-sets Item.LikedByMe for the viewer in a single
// query. A nil/zero viewer (or empty page) is a no-op.
func (s *Service) applyLiked(
	ctx context.Context, viewerID uuid.UUID, items []*domfeed.Item,
) error {
	if viewerID == uuid.Nil || len(items) == 0 {
		return nil
	}
	ids := make([]uuid.UUID, 0, len(items))
	for _, item := range items {
		ids = append(ids, item.Post.ID)
	}
	liked, err := s.posts.LikedPostIDs(ctx, viewerID, ids)
	if err != nil {
		return err
	}
	for _, item := range items {
		item.LikedByMe = liked[item.Post.ID]
	}
	return nil
}

// mutedSet returns the authors the user follows but has muted —
// excluded from every feed section, including the public fill.
func (s *Service) mutedSet(
	ctx context.Context, userID uuid.UUID,
) (map[uuid.UUID]bool, error) {
	all, err := s.graph.FollowingIDs(ctx, userID, false)
	if err != nil {
		return nil, err
	}
	unmuted, err := s.graph.FollowingIDs(ctx, userID, true)
	if err != nil {
		return nil, err
	}
	unmutedSet := toSet(unmuted)
	muted := map[uuid.UUID]bool{}
	for _, id := range all {
		if !unmutedSet[id] {
			muted[id] = true
		}
	}
	return muted, nil
}

// splitFollowing partitions the user's UNMUTED follows into agents
// and users. Muted follows never reach a feed (mute rule).
func (s *Service) splitFollowing(
	ctx context.Context, userID uuid.UUID,
) (agents, users []uuid.UUID, err error) {
	following, err := s.graph.FollowingIDs(ctx, userID, true)
	if err != nil {
		return nil, nil, err
	}
	activeAgents, err := s.agents.ActiveIDs(ctx)
	if err != nil {
		return nil, nil, err
	}
	agentSet := toSet(activeAgents)
	for _, id := range following {
		if agentSet[id] {
			agents = append(agents, id)
		} else {
			users = append(users, id)
		}
	}
	return agents, users, nil
}

// sortWithAgentPriority orders newest-first by time bucket; INSIDE a
// bucket ("timestamps are close") agent posts come before user posts,
// then newest-first as the final tiebreak. Deterministic — this is a
// fixed product ordering, not a ranking engine.
func sortWithAgentPriority(items []*domfeed.Item) {
	sort.SliceStable(items, func(i, j int) bool {
		bi := items[i].Post.CreatedAt.Truncate(priorityBucket)
		bj := items[j].Post.CreatedAt.Truncate(priorityBucket)
		if !bi.Equal(bj) {
			return bi.After(bj)
		}
		ai := items[i].Post.AuthorType == dompost.AuthorAgent
		aj := items[j].Post.AuthorType == dompost.AuthorAgent
		if ai != aj {
			return ai
		}
		return items[i].Post.CreatedAt.After(items[j].Post.CreatedAt)
	})
}

func page(items []*domfeed.Item) domfeed.Page {
	p := domfeed.Page{Items: items}
	if len(items) > 0 {
		oldest := items[0].Post.CreatedAt
		for _, item := range items[1:] {
			if item.Post.CreatedAt.Before(oldest) {
				oldest = item.Post.CreatedAt
			}
		}
		p.NextCursor = encodeCursor(oldest)
	}
	return p
}

func clampLimit(limit int) int {
	if limit <= 0 {
		return defaultLimit
	}
	if limit > maxLimit {
		return maxLimit
	}
	return limit
}

// Cursor: base64 of the oldest-seen unix-nano timestamp; the next
// page fetches strictly older posts. Simple + stateless — adequate
// for V1 query-time generation.
func encodeCursor(t time.Time) string {
	return base64.RawURLEncoding.EncodeToString(
		[]byte(strconv.FormatInt(t.UnixNano(), 10)),
	)
}

func decodeCursor(cursor string) time.Time {
	if cursor == "" {
		return time.Now().UTC().Add(time.Minute)
	}
	raw, err := base64.RawURLEncoding.DecodeString(cursor)
	if err != nil {
		return time.Now().UTC().Add(time.Minute)
	}
	nanos, err := strconv.ParseInt(string(raw), 10, 64)
	if err != nil {
		return time.Now().UTC().Add(time.Minute)
	}
	return time.Unix(0, nanos).UTC()
}

func toSet(ids []uuid.UUID) map[uuid.UUID]bool {
	set := make(map[uuid.UUID]bool, len(ids))
	for _, id := range ids {
		set[id] = true
	}
	return set
}
