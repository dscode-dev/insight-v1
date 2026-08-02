// FEATURE-SEARCH-V1 (Stage 1) — internal Search HTTP surface.
//
// Gateway-only internal port; the Gateway authenticates and forwards the
// verified user via X-User-Id (never a client-supplied id). One typed route per
// category (no generic search endpoint), plus private history and the
// capabilities contract. "All" aggregation is NOT here — it belongs to the
// Gateway BFF (Stage 2).
//
//   GET    /search/users?q=&limit=&cursor=
//   GET    /search/agents?...
//   GET    /search/communities?...
//   GET    /search/competitions?...
//   GET    /search/matches?...
//   GET    /search/posts?...
//   GET    /search/history
//   DELETE /search/history
//   GET    /search/capabilities

package httpapi

import (
	"errors"
	"net/http"
	"strconv"
	"time"

	appsearch "github.com/konoha-labs/insight-social/internal/application/search"
	domsearch "github.com/konoha-labs/insight-social/internal/domain/search"
)

// searchErr maps domain validation errors to explicit client statuses.
func searchErr(w http.ResponseWriter, err error) bool {
	if err == nil {
		return false
	}
	switch {
	case errors.Is(err, domsearch.ErrQueryTooShort):
		writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "query_too_short", "min": domsearch.MinQueryLen})
	case errors.Is(err, domsearch.ErrQueryTooLong):
		writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "query_too_long", "max": domsearch.MaxQueryLen})
	case errors.Is(err, domsearch.ErrInvalidCursor), errors.Is(err, domsearch.ErrCursorCategory):
		writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "invalid_cursor"})
	default:
		writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "search_failed"})
	}
	return true
}

func searchParams(r *http.Request) (q string, limit int, cursor string) {
	qs := r.URL.Query()
	limit, _ = strconv.Atoi(qs.Get("limit"))
	return qs.Get("q"), limit, qs.Get("cursor")
}

func ts(t time.Time) string { return t.UTC().Format(time.RFC3339) }

// SearchUsers handles GET /search/users.
func SearchUsers(svc *appsearch.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		viewer, ok := userIDHeader(r)
		if !ok {
			writeJSON(w, http.StatusUnauthorized, map[string]any{"detail": "unauthenticated"})
			return
		}
		q, limit, cursor := searchParams(r)
		page, err := svc.Users(r.Context(), viewer, q, limit, cursor)
		if searchErr(w, err) {
			return
		}
		items := make([]map[string]any, 0, len(page.Items))
		for _, u := range page.Items {
			items = append(items, map[string]any{
				"id": u.ID.String(), "username": u.Username,
				"display_name": u.DisplayName, "initials": u.Initials,
				"accent_color": u.AccentColor, "avatar_url": u.AvatarURL,
				"reputation": u.Reputation, "tier": u.Tier,
				"followers": u.Followers, "is_following": u.IsFollowing,
				"follows_viewer": u.FollowsViewer,
				"mutual":         u.IsFollowing && u.FollowsViewer,
			})
		}
		writeJSON(w, http.StatusOK, map[string]any{"items": items, "next_cursor": page.NextCursor})
	}
}

// SearchAgents handles GET /search/agents.
func SearchAgents(svc *appsearch.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		viewer, ok := userIDHeader(r)
		if !ok {
			writeJSON(w, http.StatusUnauthorized, map[string]any{"detail": "unauthenticated"})
			return
		}
		q, limit, cursor := searchParams(r)
		page, err := svc.Agents(r.Context(), viewer, q, limit, cursor)
		if searchErr(w, err) {
			return
		}
		items := make([]map[string]any, 0, len(page.Items))
		for _, a := range page.Items {
			items = append(items, map[string]any{
				"id": a.ID.String(), "slug": a.Slug, "name": a.Name,
				"avatar": a.Avatar, "bio": a.Bio,
				"active": a.Active, "verified": a.Verified,
			})
		}
		writeJSON(w, http.StatusOK, map[string]any{"items": items, "next_cursor": page.NextCursor})
	}
}

// SearchCommunities handles GET /search/communities.
func SearchCommunities(svc *appsearch.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		viewer, ok := userIDHeader(r)
		if !ok {
			writeJSON(w, http.StatusUnauthorized, map[string]any{"detail": "unauthenticated"})
			return
		}
		q, limit, cursor := searchParams(r)
		page, err := svc.Communities(r.Context(), viewer, q, limit, cursor)
		if searchErr(w, err) {
			return
		}
		items := make([]map[string]any, 0, len(page.Items))
		for _, c := range page.Items {
			items = append(items, map[string]any{
				"id": c.ID.String(), "slug": c.Slug, "name": c.Name,
				"topic": c.Topic, "kind": c.Kind,
				"member_count": c.MemberCount, "accent_color": c.AccentColor,
			})
		}
		writeJSON(w, http.StatusOK, map[string]any{"items": items, "next_cursor": page.NextCursor})
	}
}

// SearchCompetitions handles GET /search/competitions.
func SearchCompetitions(svc *appsearch.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		viewer, ok := userIDHeader(r)
		if !ok {
			writeJSON(w, http.StatusUnauthorized, map[string]any{"detail": "unauthenticated"})
			return
		}
		q, limit, cursor := searchParams(r)
		page, err := svc.Competitions(r.Context(), viewer, q, limit, cursor)
		if searchErr(w, err) {
			return
		}
		items := make([]map[string]any, 0, len(page.Items))
		for _, c := range page.Items {
			items = append(items, map[string]any{
				"id": c.ID.String(), "slug": c.Slug, "name": c.Name,
				"short_name": c.ShortName, "region": c.Region,
				"accent_color": c.AccentColor, "featured": c.Featured,
				"active": c.Active,
			})
		}
		writeJSON(w, http.StatusOK, map[string]any{"items": items, "next_cursor": page.NextCursor})
	}
}

// SearchMatches handles GET /search/matches. Team names are match CONTEXT —
// never promoted to Team entities (BLOCKED_BY_DOMAIN).
func SearchMatches(svc *appsearch.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		viewer, ok := userIDHeader(r)
		if !ok {
			writeJSON(w, http.StatusUnauthorized, map[string]any{"detail": "unauthenticated"})
			return
		}
		q, limit, cursor := searchParams(r)
		page, err := svc.Matches(r.Context(), viewer, q, limit, cursor)
		if searchErr(w, err) {
			return
		}
		items := make([]map[string]any, 0, len(page.Items))
		for _, m := range page.Items {
			items = append(items, map[string]any{
				"match_id":         m.MatchID.String(),
				"competition_id":   m.CompetitionID.String(),
				"competition_name": m.CompetitionName,
				"home_team": map[string]any{
					"name": m.HomeTeamName, "short": m.HomeTeamShort, "color": m.HomeTeamColor,
				},
				"away_team": map[string]any{
					"name": m.AwayTeamName, "short": m.AwayTeamShort, "color": m.AwayTeamColor,
				},
				"kickoff_ts": ts(m.KickoffTs), "state": m.State,
				"home_score": m.HomeScore, "away_score": m.AwayScore,
			})
		}
		writeJSON(w, http.StatusOK, map[string]any{"items": items, "next_cursor": page.NextCursor})
	}
}

// SearchPosts handles GET /search/posts (real FTS; public + non-deleted only;
// Gateway applies its moderation lens in Stage 2, mirroring the feed).
func SearchPosts(svc *appsearch.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		viewer, ok := userIDHeader(r)
		if !ok {
			writeJSON(w, http.StatusUnauthorized, map[string]any{"detail": "unauthenticated"})
			return
		}
		q, limit, cursor := searchParams(r)
		page, err := svc.Posts(r.Context(), viewer, q, limit, cursor)
		if searchErr(w, err) {
			return
		}
		items := make([]map[string]any, 0, len(page.Items))
		for _, p := range page.Items {
			items = append(items, map[string]any{
				"id":        p.ID.String(),
				"author_id": p.AuthorID.String(), "author_type": p.AuthorType,
				"author_name": p.AuthorName, "author_avatar": p.AuthorAvatar,
				"snippet":    p.Snippet, // matched terms wrapped in <b></b>
				"created_at": ts(p.CreatedAt),
				"like_count": p.LikeCount, "comment_count": p.CommentCount,
			})
		}
		writeJSON(w, http.StatusOK, map[string]any{"items": items, "next_cursor": page.NextCursor})
	}
}

// SearchHistory handles GET /search/history (private per user).
func SearchHistory(svc *appsearch.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		userID, ok := userIDHeader(r)
		if !ok {
			writeJSON(w, http.StatusUnauthorized, map[string]any{"detail": "unauthenticated"})
			return
		}
		entries, err := svc.History(r.Context(), userID)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "history_failed"})
			return
		}
		items := make([]map[string]any, 0, len(entries))
		for _, e := range entries {
			items = append(items, map[string]any{"query": e.Query, "created_at": ts(e.CreatedAt)})
		}
		writeJSON(w, http.StatusOK, map[string]any{"items": items})
	}
}

// ClearSearchHistory handles DELETE /search/history.
func ClearSearchHistory(svc *appsearch.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		userID, ok := userIDHeader(r)
		if !ok {
			writeJSON(w, http.StatusUnauthorized, map[string]any{"detail": "unauthenticated"})
			return
		}
		if err := svc.ClearHistory(r.Context(), userID); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "history_clear_failed"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"cleared": true})
	}
}

// SearchCapabilities handles GET /search/capabilities — the contract clients
// derive their visible categories from (enabled + honestly-blocked + trending
// availability). Never a hardcoded client list.
func SearchCapabilities(svc *appsearch.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, svc.Capabilities())
	}
}
