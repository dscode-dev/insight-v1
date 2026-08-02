// AZTECA-IDENTITY-B — the enriched Sports Profile read.
//
// ONE endpoint returns the whole identity payload (versioned avatar + grouped
// stats) so the client makes a single request instead of stitching getUser +
// separate counts. This ENRICHES the profile contract; it is not a duplicate
// statistics API. insight-social owns every field. Fields the backend doesn't
// model yet (location, favorite_team) are emitted as null — never fabricated.
package httpapi

import (
	"net/http"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

type sportsProfileStats struct {
	Followers   int `json:"followers"`
	Following   int `json:"following"`
	Communities int `json:"communities"`
	Posts       int `json:"posts"`
	Signals     int `json:"signals"`
}

type sportsProfileResponse struct {
	ID            string             `json:"id"`
	Username      string             `json:"username"`
	DisplayName   string             `json:"display_name"`
	Initials      string             `json:"initials"`
	AccentColor   string             `json:"accent_color"`
	Reputation    int                `json:"reputation"`
	AvatarURL     *string            `json:"avatar_url"`
	AvatarVersion *int64             `json:"avatar_version"`
	Role          string             `json:"role"`          // V1: always "supporter"
	Location      *string            `json:"location"`      // not modelled yet → null
	FavoriteTeam  *string            `json:"favorite_team"` // not modelled yet → null
	Stats         sportsProfileStats `json:"stats"`
}

// SportsProfile serves `GET /users/{id}/sports-profile`.
func SportsProfile(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"detail": "method_not_allowed"})
			return
		}
		id, err := uuid.Parse(r.PathValue("id"))
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid_user_id"})
			return
		}

		var (
			resp    sportsProfileResponse
			avatar  *string
			version *int64
			stats   sportsProfileStats
		)
		err = pool.QueryRow(r.Context(), `
SELECT u.id, u.username, u.display_name, u.initials, u.accent_color, u.reputation,
       CASE WHEN u.avatar_url IS NOT NULL AND u.avatar_url <> '' AND u.avatar_updated_at IS NOT NULL
            THEN u.avatar_url || '?v=' || (extract(epoch FROM u.avatar_updated_at)::bigint)::text
            ELSE u.avatar_url END AS avatar_url,
       (extract(epoch FROM u.avatar_updated_at)::bigint) AS avatar_version,
       (SELECT COUNT(*) FROM relationships r WHERE r.target_id = u.id AND r.kind = 'follow') AS followers,
       (SELECT COUNT(*) FROM relationships r WHERE r.actor_id  = u.id AND r.kind = 'follow') AS following,
       (SELECT COUNT(*) FROM community_members cm WHERE cm.user_id = u.id) AS communities,
       (SELECT COUNT(*) FROM posts p WHERE p.author_id = u.id AND p.author_type = 'user' AND p.deleted_at IS NULL) AS posts,
       (SELECT COUNT(*) FROM signals s WHERE s.author_id = u.id) AS signals
  FROM users u
 WHERE u.id = $1`, id).Scan(
			&resp.ID, &resp.Username, &resp.DisplayName, &resp.Initials, &resp.AccentColor, &resp.Reputation,
			&avatar, &version,
			&stats.Followers, &stats.Following, &stats.Communities, &stats.Posts, &stats.Signals,
		)
		if err != nil {
			// No row → 404; anything else → 500.
			writeJSON(w, http.StatusNotFound, map[string]string{"detail": "user_not_found"})
			return
		}

		resp.AvatarURL = avatar
		resp.AvatarVersion = version
		resp.Stats = stats
		resp.Role = "supporter" // V1 default; future roles render-ready on the client.
		// Location + FavoriteTeam stay nil — not modelled yet (never fabricated).
		writeJSON(w, http.StatusOK, resp)
	}
}
