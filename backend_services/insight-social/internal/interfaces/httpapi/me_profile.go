// AZTECA-PROFILE-B — authenticated profile write (internal Social HTTP).
//
// PATCH /users/me/profile  (gateway-only internal port; gateway forwards the
// verified user via X-User-Id — never a client-supplied id). The ONLY writable
// Core Identity text field modeled by the users schema is display_name. This
// handler is deliberately narrow: no mass assignment, no reputation/tier/role/
// avatar/username mutation (avatar has its own upload path; username/role/
// location/favorite_team are not V1-writable — see the sports-profile handler
// which emits them null/derived, never fabricated).

package httpapi

import (
	"encoding/json"
	"errors"
	"net/http"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// maxDisplayNameLen mirrors the users.display_name VARCHAR(64) column.
const maxDisplayNameLen = 64

type updateProfileBody struct {
	// Pointer = "field present" vs "omitted" (partial update). Only display_name
	// is accepted; any other key in the body is ignored (no mass assignment).
	DisplayName *string `json:"display_name"`
}

// UpdateMyProfile handles PATCH /users/me/profile. Server-derived identity
// (X-User-Id); partial update; returns the updated user projection.
func UpdateMyProfile(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		userID, ok := userIDHeader(r)
		if !ok {
			writeJSON(w, http.StatusUnauthorized, map[string]any{"detail": "unauthenticated"})
			return
		}
		var body updateProfileBody
		if r.Body != nil {
			if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4<<10)).Decode(&body); err != nil {
				writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "invalid_json"})
				return
			}
		}

		// V1 accepts display_name only. Nothing to change → 400 (avoid a silent no-op).
		if body.DisplayName == nil {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "no_editable_fields"})
			return
		}
		name := strings.TrimSpace(*body.DisplayName)
		if name == "" {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "display_name_required", "field": "display_name"})
			return
		}
		// Count runes (not bytes) so multi-byte names aren't unfairly rejected.
		if len([]rune(name)) > maxDisplayNameLen {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "display_name_too_long", "field": "display_name", "max": maxDisplayNameLen})
			return
		}

		const q = `
UPDATE users SET display_name = $2
 WHERE id = $1
RETURNING id, username, display_name, initials, accent_color, reputation, tier`
		var (
			id, username, displayName, initials, accent, tier string
			reputation                                        int
		)
		err := pool.QueryRow(r.Context(), q, userID, name).Scan(
			&id, &username, &displayName, &initials, &accent, &reputation, &tier)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				writeJSON(w, http.StatusNotFound, map[string]any{"detail": "user_not_found"})
				return
			}
			writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "profile_update_failed"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"id": id, "username": username, "display_name": displayName,
			"initials": initials, "accent_color": accent,
			"reputation": reputation, "tier": tier,
		})
	}
}
