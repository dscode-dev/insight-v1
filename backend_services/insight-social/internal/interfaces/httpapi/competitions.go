// Package httpapi exposes lightweight read-only HTTP endpoints on the social
// service's HTTP port (alongside /healthz, /metrics). insight-social is the
// source of truth for the Azteca Featured Competitions Rail; the Gateway
// proxies this endpoint and the mobile client consumes it. (AZTECA-HOME-A.)
package httpapi

import (
	"encoding/json"
	"net/http"

	"github.com/jackc/pgx/v5/pgxpool"
)

// competition is the wire shape for one rail entry. Field names are stable;
// the client tolerates additional fields, so the model can grow without a
// breaking change.
type competition struct {
	ID           string  `json:"id"`
	Name         string  `json:"name"`
	Slug         string  `json:"slug"`
	Country      *string `json:"country"`
	Continent    *string `json:"continent"`
	Type         *string `json:"type"`
	Featured     bool    `json:"featured"`
	Priority     int     `json:"priority"`
	DisplayOrder int     `json:"display_order"`
	Icon         *string `json:"icon"`
	Active       bool    `json:"active"`
}

// CompetitionHighlights serves `GET /competitions/highlights`: the active
// competitions for the rail, ordered ENTIRELY by the backend —
// featured DESC, then priority ASC, display_order ASC, name ASC. The client
// must not reorder.
func CompetitionHighlights(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"detail": "method_not_allowed"})
			return
		}
		rows, err := pool.Query(r.Context(), `
SELECT id::text, name, slug, country, continent, type, featured, priority, display_order, icon, active
  FROM competitions
 WHERE active = TRUE
 ORDER BY featured DESC, priority ASC, display_order ASC, name ASC`)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "competitions_query_failed"})
			return
		}
		defer rows.Close()

		out := make([]competition, 0, 8)
		for rows.Next() {
			var c competition
			if err := rows.Scan(
				&c.ID, &c.Name, &c.Slug, &c.Country, &c.Continent, &c.Type,
				&c.Featured, &c.Priority, &c.DisplayOrder, &c.Icon, &c.Active,
			); err != nil {
				continue
			}
			out = append(out, c)
		}
		if err := rows.Err(); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "competitions_scan_failed"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"competitions": out})
	}
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
