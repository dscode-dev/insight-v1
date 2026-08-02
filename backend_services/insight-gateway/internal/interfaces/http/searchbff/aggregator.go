// SearchAggregator — the ONLY place the "All" discovery view exists.
// Social knows individual categories; the Gateway owns the experience:
// parallel fan-out (one shared correlation id), a global timeout whose
// cancellation propagates to every upstream call (no orphan goroutines — the
// WaitGroup joins every worker before returning), HONEST partial semantics
// (partial=true + the exact failed categories, never a silent []), per-category
// cursors, and a deterministic cross-category ordering via normalized_score.
//
// ── normalized_score strategy (documented, no AI) ───────────────────────────
// Each Social category is already deterministically ranked internally (Stage 1:
// exact → prefix → contains → domain tiebreakers). Those per-domain orders are
// not comparable as raw values (reputation vs member_count vs ts_rank), so the
// Gateway derives a score PURELY from each item's POSITION in its own ranking:
//
//     normalized_score = 1 / (1 + position)        (position 0-based)
//
// → 1.00, 0.50, 0.33, 0.25, 0.20 … (reciprocal-rank). Properties:
//   * derived exclusively from the domain's own deterministic ranking;
//   * every category's #1 result scores 1.0 ⇒ the best of each domain surfaces
//     first (the desired discovery UX), then #2s, and so on;
//   * ties (same position across categories) break by the fixed product
//     category priority (CategoryOrder) and finally entity_id — total order is
//     fully deterministic: same data + same query ⇒ same response.
// ─────────────────────────────────────────────────────────────────────────────

package searchbff

import (
	"context"
	"errors"
	"sort"
	"sync"
	"time"
)

// Fetcher is one category's first-page fetch (injected — testable without HTTP).
type Fetcher func(ctx context.Context, cc callCtx, q string, limit int, cursor string) (CategoryPage, error)

type Aggregator struct {
	fetchers map[string]Fetcher // keyed by category (subset of CategoryOrder)
	timeout  time.Duration      // global budget for the whole fan-out
	perCat   int                // items fetched per category for /all
	metrics  *Metrics
}

func NewAggregator(c *SocialClient, timeout time.Duration, perCategory int, m *Metrics) *Aggregator {
	return &Aggregator{
		fetchers: map[string]Fetcher{
			"users":        c.Users,
			"agents":       c.Agents,
			"communities":  c.Communities,
			"competitions": c.Competitions,
			"matches":      c.Matches,
			"posts":        c.Posts,
		},
		timeout: timeout,
		perCat:  perCategory,
		metrics: m,
	}
}

// ErrAllCategoriesFailed — every upstream failed: a real error, not partial.
var ErrAllCategoriesFailed = errors.New("search_all_categories_failed")

type catOutcome struct {
	category string
	page     CategoryPage
	err      error
}

// All runs the aggregated discovery search.
func (a *Aggregator) All(ctx context.Context, cc callCtx, q string) (AllResponse, error) {
	// Global budget: expiry (or the caller's own cancellation) aborts every
	// in-flight upstream call via context propagation.
	ctx, cancel := context.WithTimeout(ctx, a.timeout)
	defer cancel()

	results := make(chan catOutcome, len(a.fetchers))
	var wg sync.WaitGroup
	for _, cat := range CategoryOrder { // deterministic launch set
		fetch, ok := a.fetchers[cat]
		if !ok {
			continue
		}
		wg.Add(1)
		go func(cat string, fetch Fetcher) {
			defer wg.Done()
			page, err := fetch(ctx, cc, q, a.perCat, "")
			results <- catOutcome{category: cat, page: page, err: err}
		}(cat, fetch)
	}
	wg.Wait() // no orphan goroutines: every worker joined before we return
	close(results)

	resp := AllResponse{
		Query:            q,
		Items:            []Card{},
		Cursors:          map[string]string{},
		FailedCategories: []string{},
	}
	succeeded := 0
	for out := range results {
		if out.err != nil {
			resp.Partial = true
			resp.FailedCategories = append(resp.FailedCategories, out.category)
			if a.metrics != nil {
				a.metrics.CategoryFailure(out.category, out.err, ctx.Err())
			}
			continue
		}
		succeeded++
		if out.page.NextCursor != "" {
			resp.Cursors[out.category] = out.page.NextCursor
		}
		for pos, card := range out.page.Cards {
			card.Score = 1.0 / (1.0 + float64(pos)) // reciprocal rank of the DOMAIN's own order
			resp.Items = append(resp.Items, card)
		}
	}
	sort.Strings(resp.FailedCategories) // deterministic report

	if succeeded == 0 {
		if ctx.Err() != nil {
			return AllResponse{}, ctx.Err() // timeout/cancel surfaced canonically
		}
		return AllResponse{}, ErrAllCategoriesFailed
	}

	// Deterministic heterogeneous merge: score DESC → category priority → id.
	sort.SliceStable(resp.Items, func(i, j int) bool {
		a, b := resp.Items[i], resp.Items[j]
		if a.Score != b.Score {
			return a.Score > b.Score
		}
		pa := categoryPriority[pluralOf(a.EntityType)]
		pb := categoryPriority[pluralOf(b.EntityType)]
		if pa != pb {
			return pa < pb
		}
		return a.EntityID < b.EntityID
	})
	return resp, nil
}

// pluralOf maps entity_type back to its category key (for priority lookup).
func pluralOf(entityType string) string {
	for cat, et := range entityTypeFor {
		if et == entityType {
			return cat
		}
	}
	return entityType
}
