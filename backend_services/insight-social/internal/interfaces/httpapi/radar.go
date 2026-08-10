package httpapi

// Radar — what the collector brought, for the app to read.
//
// The write side (registering sources) is in console_radar.go and belongs to
// the operator. This is the read side and belongs to the reader: one stream,
// newest first, filtered by the same rail as the feed.
//
// ONLY ITEMS FROM ACTIVE SOURCES. Deactivating a source is how an operator
// says "stop showing this" — it is the reversible action offered instead of
// deletion, and if the content it already collected stayed visible the action
// would not do what its name promises. Deleting the source removes the items
// too (ON DELETE CASCADE); deactivating hides them and keeps them.

import (
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

type radarItem struct {
	ID         string    `json:"id"`
	Kind       string    `json:"kind"`
	Title      string    `json:"title"`
	Summary    *string   `json:"summary,omitempty"`
	URL        *string   `json:"url,omitempty"`
	ImageURL   *string   `json:"image_url,omitempty"`
	OccurredAt time.Time `json:"occurred_at"`

	// Which subscription produced it. The app shows attribution, and an
	// operator debugging a bad item needs to know where it came from without
	// opening the database.
	SourceSlug string `json:"source_slug"`
	SourceName string `json:"source_name"`

	CompetitionID   *string `json:"competition_id,omitempty"`
	CompetitionSlug *string `json:"competition_slug,omitempty"`
}

// RadarFeed — GET /radar?competition_id=&kind=&limit=&before=
//
// `before` is an RFC3339 timestamp rather than an opaque cursor: the ordering
// key is `occurred_at`, which the client already has on the last item it
// rendered. An encoded cursor would hide a value the client is holding anyway.
func RadarFeed(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		query := r.URL.Query()

		limit := 30
		if raw := query.Get("limit"); raw != "" {
			parsed, err := strconv.Atoi(raw)
			if err != nil || parsed < 1 || parsed > 100 {
				writeJSON(w, http.StatusBadRequest,
					map[string]any{"detail": "limit_invalid: 1..100"})
				return
			}
			limit = parsed
		}

		before := time.Now().UTC().Add(time.Minute)
		if raw := strings.TrimSpace(query.Get("before")); raw != "" {
			parsed, err := time.Parse(time.RFC3339, raw)
			if err != nil {
				writeJSON(w, http.StatusBadRequest,
					map[string]any{"detail": "before_invalid: use RFC3339"})
				return
			}
			before = parsed
		}

		var kind *string
		if raw := strings.TrimSpace(query.Get("kind")); raw != "" {
			if !radarKinds[raw] {
				writeJSON(w, http.StatusBadRequest, map[string]any{
					"detail":  "kind_invalid",
					"allowed": []string{"live_matches", "scores", "news", "odds", "other"},
				})
				return
			}
			kind = &raw
		}

		var competitionID *string
		if raw := strings.TrimSpace(query.Get("competition_id")); raw != "" {
			competitionID = &raw
		}

		rows, err := pool.Query(r.Context(), `
			SELECT i.id::text, i.kind, i.title, i.summary, i.url, i.image_url,
			       i.occurred_at, s.slug, s.name,
			       i.competition_id::text, c.slug
			  FROM radar_items i
			  JOIN radar_sources s ON s.id = i.source_id
			  -- LEFT, not INNER: most items map to no competition, and an inner
			  -- join would silently drop every one of them from the stream.
			  LEFT JOIN competitions c ON c.id = i.competition_id
			 WHERE s.active
			   AND i.occurred_at < $1
			   AND ($2::varchar IS NULL OR i.kind = $2::varchar)
			   AND ($3::uuid IS NULL OR i.competition_id = $3::uuid)
			 ORDER BY i.occurred_at DESC
			 LIMIT $4::int`,
			before, kind, competitionID, limit)
		if err != nil {
			slog.Error("radar_feed_query_failed", "error", err.Error())
			writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "query_failed"})
			return
		}
		defer rows.Close()

		out := make([]radarItem, 0, limit)
		for rows.Next() {
			var item radarItem
			if err := rows.Scan(&item.ID, &item.Kind, &item.Title, &item.Summary,
				&item.URL, &item.ImageURL, &item.OccurredAt,
				&item.SourceSlug, &item.SourceName,
				&item.CompetitionID, &item.CompetitionSlug); err != nil {
				slog.Error("radar_feed_scan_failed", "error", err.Error())
				writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "scan_failed"})
				return
			}
			out = append(out, item)
		}
		if rows.Err() != nil {
			slog.Error("radar_feed_rows_failed", "error", rows.Err().Error())
			writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "scan_failed"})
			return
		}

		// The next page's `before`, so the client does not have to know that
		// `occurred_at` is the ordering key. Absent when the page was not
		// full — there is nothing after it.
		response := map[string]any{"items": out, "count": len(out)}
		if len(out) == limit {
			response["next_before"] = out[len(out)-1].OccurredAt.Format(time.RFC3339)
		}
		writeJSON(w, http.StatusOK, response)
	}
}
