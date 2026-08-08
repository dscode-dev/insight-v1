package httpapi

// Explorar — "em alta", and the view recording that makes it measurable.
//
// The score is computed by `trending_posts()` in migration 00015, not here.
// Ranking is a product rule that changes, and a rule expressed in SQL beside
// the data it reads can be inspected, EXPLAINed and adjusted without a deploy
// — where the same rule assembled in Go is only visible to whoever is holding
// the source.
//
// WHY VIEWS ARE POSTED IN BATCHES. A view happens every time a post renders.
// One HTTP call per rendered post would make scrolling a feed the heaviest
// thing the client does, so the client accumulates and flushes: one call
// carrying many posts. `record_post_views` folds each into a five-minute
// bucket, so the write cost per post per bucket is one UPSERT regardless of
// how many views land in it.

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// The rate is only meaningful over a window a human would recognise, and an
// unbounded one lets a caller ask the database to scan every bucket ever
// written. Named windows rather than a free interval: "1h" is a product
// decision, "3847s" is a way to make the query expensive.
var exploreWindows = map[string]time.Duration{
	"15m": 15 * time.Minute,
	"1h":  time.Hour,
	"6h":  6 * time.Hour,
	"24h": 24 * time.Hour,
	"7d":  7 * 24 * time.Hour,
}

const defaultExploreWindow = "1h"

type trendingEntry struct {
	PostID   string  `json:"post_id"`
	Views    int64   `json:"views"`
	Likes    int64   `json:"likes"`
	Comments int64   `json:"comments"`
	Shares   int64   `json:"shares"`
	Score    float64 `json:"score_per_sec"`
}

// ExploreTrending — GET /explore/trending?window=1h&limit=20&competition_id=...
func ExploreTrending(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		query := r.URL.Query()

		windowKey := strings.TrimSpace(query.Get("window"))
		if windowKey == "" {
			windowKey = defaultExploreWindow
		}
		window, ok := exploreWindows[windowKey]
		if !ok {
			// Named, not silently defaulted: a client asking for a window that
			// does not exist and receiving another one would report the wrong
			// period beside the numbers.
			writeJSON(w, http.StatusBadRequest, map[string]any{
				"detail": "window_invalid", "allowed": sortedWindowKeys(),
			})
			return
		}

		limit := 20
		if raw := query.Get("limit"); raw != "" {
			parsed, err := strconv.Atoi(raw)
			if err != nil || parsed < 1 || parsed > 100 {
				writeJSON(w, http.StatusBadRequest,
					map[string]any{"detail": "limit_invalid: 1..100"})
				return
			}
			limit = parsed
		}

		// The rail's selection reaches Explorar: "em alta" in the competition
		// being viewed, not across the whole platform. Empty = todos.
		var competitionID *string
		if raw := strings.TrimSpace(query.Get("competition_id")); raw != "" {
			competitionID = &raw
		}

		rows, err := pool.Query(r.Context(),
			`SELECT post_id::text, views, likes, comments, shares, score_per_sec
			   FROM trending_posts($1::interval, $2::int, $3::uuid)`,
			window.String(), limit, competitionID)
		if err != nil {
			slog.Error("explore_trending_query_failed", "error", err.Error())
			writeJSON(w, http.StatusInternalServerError,
				map[string]any{"detail": "query_failed"})
			return
		}
		defer rows.Close()

		out := make([]trendingEntry, 0, limit)
		for rows.Next() {
			var e trendingEntry
			if err := rows.Scan(&e.PostID, &e.Views, &e.Likes, &e.Comments,
				&e.Shares, &e.Score); err != nil {
				slog.Error("explore_trending_scan_failed", "error", err.Error())
				writeJSON(w, http.StatusInternalServerError,
					map[string]any{"detail": "scan_failed"})
				return
			}
			out = append(out, e)
		}
		if rows.Err() != nil {
			slog.Error("explore_trending_rows_failed", "error", rows.Err().Error())
			writeJSON(w, http.StatusInternalServerError,
				map[string]any{"detail": "scan_failed"})
			return
		}

		// The window travels with the answer. A score is a rate, and a rate
		// without its period is a number nobody can compare to another.
		writeJSON(w, http.StatusOK, map[string]any{
			"window": windowKey, "trending": out, "count": len(out),
		})
	}
}

type viewBatchEntry struct {
	PostID  string `json:"post_id"`
	Views   int64  `json:"views"`
	Viewers int64  `json:"viewers"`
}

type viewBatch struct {
	Items []viewBatchEntry `json:"items"`
}

// Bounded so one call cannot ask for an unbounded number of UPSERTs. A feed
// screen holds tens of posts, not hundreds.
const maxViewBatch = 200

// RecordPostViews — POST /explore/views
//
// Best-effort by design. A view is a metric, not a fact the user is waiting
// on: an entry that fails is counted and skipped rather than failing the
// batch, because losing a view is invisible and losing the scroll is not.
func RecordPostViews(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var batch viewBatch
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 64<<10)).
			Decode(&batch); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "invalid_json"})
			return
		}
		if len(batch.Items) == 0 {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "items_required"})
			return
		}
		if len(batch.Items) > maxViewBatch {
			writeJSON(w, http.StatusBadRequest,
				map[string]any{"detail": "batch_too_large", "max": maxViewBatch})
			return
		}

		recorded, skipped := 0, 0
		for _, item := range batch.Items {
			// A negative or absurd count is a client bug or an attempt to
			// inflate a ranking. Clamped rather than rejected: the rest of the
			// batch is still worth recording.
			if item.Views <= 0 || item.Views > 1000 {
				skipped++
				continue
			}
			if item.Viewers < 0 || item.Viewers > item.Views {
				// More distinct viewers than views is not representable.
				item.Viewers = 0
			}
			if _, err := pool.Exec(r.Context(),
				`SELECT record_post_views($1::uuid, $2::bigint, $3::bigint)`,
				item.PostID, item.Views, item.Viewers); err != nil {
				// An unknown post id lands here via the foreign key. Counted,
				// not surfaced: the client may legitimately hold a post that
				// was deleted between render and flush.
				skipped++
				continue
			}
			recorded++
		}

		writeJSON(w, http.StatusAccepted, map[string]any{
			"recorded": recorded, "skipped": skipped,
		})
	}
}

func sortedWindowKeys() []string {
	// Ordered by duration, not alphabetically — "15m, 1h, 6h, 24h, 7d" reads
	// as a scale; "15m, 1h, 24h, 6h, 7d" reads as a mistake.
	return []string{"15m", "1h", "6h", "24h", "7d"}
}
