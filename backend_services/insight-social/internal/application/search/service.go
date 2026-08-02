// Package search is the FEATURE-SEARCH-V1 (Stage 1) application service:
// validation, per-category orchestration, private history and the capabilities
// contract clients derive their visible categories from.
//
// Thin by design — ranking/pagination correctness lives in SQL (searchrepo);
// this layer owns input hygiene (normalize, clamp, cursor decode) and the
// history side-effect (best-effort: a history failure never fails a search).
package search

import (
	"context"

	"github.com/google/uuid"

	domsearch "github.com/konoha-labs/insight-social/internal/domain/search"
)

type Service struct {
	repo domsearch.Repository
}

func New(repo domsearch.Repository) *Service { return &Service{repo: repo} }

// prepare normalizes the query, clamps the limit and decodes the cursor for
// one category. Every category search funnels through it.
func prepare(rawQ string, limit int, rawCursor string, cat domsearch.Category,
) (q string, lim int, cur *domsearch.Cursor, err error) {
	q, err = domsearch.NormalizeQuery(rawQ)
	if err != nil {
		return "", 0, nil, err
	}
	cur, err = domsearch.DecodeCursor(rawCursor, cat)
	if err != nil {
		return "", 0, nil, err
	}
	return q, domsearch.ClampLimit(limit), cur, nil
}

// recordHistory is best-effort and only on FIRST pages (a paginating user is
// continuing one search, not issuing a new one).
func (s *Service) recordHistory(ctx context.Context, userID uuid.UUID, q string, cur *domsearch.Cursor) {
	if cur != nil || userID == uuid.Nil {
		return
	}
	_ = s.repo.RecordHistory(ctx, userID, q) // never fails the search
}

func (s *Service) Users(ctx context.Context, viewerID uuid.UUID, rawQ string, limit int, cursor string,
) (domsearch.Page[domsearch.UserResult], error) {
	q, lim, cur, err := prepare(rawQ, limit, cursor, domsearch.CategoryUsers)
	if err != nil {
		return domsearch.Page[domsearch.UserResult]{}, err
	}
	s.recordHistory(ctx, viewerID, q, cur)
	return s.repo.SearchUsers(ctx, viewerID, q, lim, cur)
}

func (s *Service) Agents(ctx context.Context, viewerID uuid.UUID, rawQ string, limit int, cursor string,
) (domsearch.Page[domsearch.AgentResult], error) {
	q, lim, cur, err := prepare(rawQ, limit, cursor, domsearch.CategoryAgents)
	if err != nil {
		return domsearch.Page[domsearch.AgentResult]{}, err
	}
	s.recordHistory(ctx, viewerID, q, cur)
	return s.repo.SearchAgents(ctx, q, lim, cur)
}

func (s *Service) Communities(ctx context.Context, viewerID uuid.UUID, rawQ string, limit int, cursor string,
) (domsearch.Page[domsearch.CommunityResult], error) {
	q, lim, cur, err := prepare(rawQ, limit, cursor, domsearch.CategoryCommunities)
	if err != nil {
		return domsearch.Page[domsearch.CommunityResult]{}, err
	}
	s.recordHistory(ctx, viewerID, q, cur)
	return s.repo.SearchCommunities(ctx, q, lim, cur)
}

func (s *Service) Competitions(ctx context.Context, viewerID uuid.UUID, rawQ string, limit int, cursor string,
) (domsearch.Page[domsearch.CompetitionResult], error) {
	q, lim, cur, err := prepare(rawQ, limit, cursor, domsearch.CategoryCompetitions)
	if err != nil {
		return domsearch.Page[domsearch.CompetitionResult]{}, err
	}
	s.recordHistory(ctx, viewerID, q, cur)
	return s.repo.SearchCompetitions(ctx, q, lim, cur)
}

func (s *Service) Matches(ctx context.Context, viewerID uuid.UUID, rawQ string, limit int, cursor string,
) (domsearch.Page[domsearch.MatchResult], error) {
	q, lim, cur, err := prepare(rawQ, limit, cursor, domsearch.CategoryMatches)
	if err != nil {
		return domsearch.Page[domsearch.MatchResult]{}, err
	}
	s.recordHistory(ctx, viewerID, q, cur)
	return s.repo.SearchMatches(ctx, q, lim, cur)
}

func (s *Service) Posts(ctx context.Context, viewerID uuid.UUID, rawQ string, limit int, cursor string,
) (domsearch.Page[domsearch.PostResult], error) {
	q, lim, cur, err := prepare(rawQ, limit, cursor, domsearch.CategoryPosts)
	if err != nil {
		return domsearch.Page[domsearch.PostResult]{}, err
	}
	s.recordHistory(ctx, viewerID, q, cur)
	return s.repo.SearchPosts(ctx, q, lim, cur)
}

func (s *Service) History(ctx context.Context, userID uuid.UUID) ([]domsearch.HistoryEntry, error) {
	return s.repo.History(ctx, userID, domsearch.HistoryLimit)
}

func (s *Service) ClearHistory(ctx context.Context, userID uuid.UUID) error {
	return s.repo.ClearHistory(ctx, userID)
}

// CapabilityInfo is the contract clients derive visible categories from —
// never a hardcoded client list. Blocked categories are reported honestly.
type CapabilityInfo struct {
	Enabled []string          `json:"enabled"`
	Blocked map[string]string `json:"blocked"`
	// Trending is UNAVAILABLE in V1: no query-log volume, no aggregation rule,
	// no privacy window defined yet. Never fabricated.
	Trending string `json:"trending"`
}

func (s *Service) Capabilities() CapabilityInfo {
	enabled := make([]string, 0, len(domsearch.EnabledCategories))
	for _, c := range domsearch.EnabledCategories {
		enabled = append(enabled, string(c))
	}
	return CapabilityInfo{
		Enabled:  enabled,
		Blocked:  domsearch.BlockedCategories,
		Trending: "UNAVAILABLE",
	}
}
