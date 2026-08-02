// Package searchbff is the FEATURE-SEARCH-V1 (Stage 2) Search Orchestrator —
// the Gateway-owned public discovery contract over Social's internal category
// endpoints. NOT a proxy: it owns the public DTOs, the "All" aggregation, the
// normalized cross-category score, per-user caching, cancellation, partial
// semantics, moderation filtering and deep links.
//
// The public contract is DEFINED HERE (Gateway DTO ← mapping ← Social DTO).
// Social's internal wire shapes never reach the client directly: a Social field
// rename would break compilation of the mapping, not silently leak.
package searchbff

import "encoding/json"

// Categories in deterministic PRODUCT priority order — used as the tiebreak
// when normalized scores collide in /all. Mirrors Social's enabled set.
var CategoryOrder = []string{
	"users", "agents", "communities", "competitions", "matches", "posts",
}

var categoryPriority = func() map[string]int {
	m := make(map[string]int, len(CategoryOrder))
	for i, c := range CategoryOrder {
		m[c] = i
	}
	return m
}()

// entityType per category (singular, public vocabulary).
var entityTypeFor = map[string]string{
	"users": "user", "agents": "agent", "communities": "community",
	"competitions": "competition", "matches": "match", "posts": "post",
}

// Card is ONE public search result — the unit of the discovery contract.
// entity_type/entity_id/deep_link are always present so the client never
// assembles routes manually; deep_link is null when no client destination
// exists yet (competitions today) — an honest absence, never a fabricated route.
type Card struct {
	EntityType string          `json:"entity_type"`
	EntityID   string          `json:"entity_id"`
	DeepLink   *string         `json:"deep_link"`
	Score      float64         `json:"normalized_score,omitempty"` // /all only
	Data       json.RawMessage `json:"data"`
}

// deepLink builds the client route for an entity. Route shapes are the ones the
// Azteca router actually registers — the backend knows the domain; the client
// never composes these. Competitions have NO detail destination in the client
// today ⇒ nil (documented; the card renders non-navigable).
func deepLink(category, id string) *string {
	var s string
	switch category {
	case "users":
		s = "/users/" + id
	case "agents":
		s = "/agents/" + id
	case "communities":
		s = "/hub/community/" + id
	case "matches":
		s = "/live/match/" + id
	case "posts":
		s = "/post/" + id
	default: // competitions: no client detail route exists — honest null
		return nil
	}
	return &s
}

// ---------------------------------------------------------------------------
// Public payloads (Gateway-owned). Each mirrors ONLY the product fields the
// client may consume; mapping from Social's internal JSON happens in client.go
// via these exact types — nothing else can leak.
// ---------------------------------------------------------------------------

type PublicUser struct {
	ID            string  `json:"id"`
	Username      string  `json:"username"`
	DisplayName   string  `json:"display_name"`
	Initials      string  `json:"initials"`
	AccentColor   string  `json:"accent_color"`
	AvatarURL     *string `json:"avatar_url"`
	Reputation    int     `json:"reputation"`
	Tier          string  `json:"tier"`
	Followers     int     `json:"followers"`
	IsFollowing   bool    `json:"is_following"`
	FollowsViewer bool    `json:"follows_viewer"`
	Mutual        bool    `json:"mutual"`
}

type PublicAgent struct {
	ID       string `json:"id"`
	Slug     string `json:"slug"`
	Name     string `json:"name"`
	Avatar   string `json:"avatar"`
	Bio      string `json:"bio"`
	Active   bool   `json:"active"`
	Verified bool   `json:"verified"`
}

type PublicCommunity struct {
	ID          string `json:"id"`
	Slug        string `json:"slug"`
	Name        string `json:"name"`
	Topic       string `json:"topic"`
	Kind        string `json:"kind"`
	MemberCount int    `json:"member_count"`
	AccentColor string `json:"accent_color"`
}

type PublicCompetition struct {
	ID          string `json:"id"`
	Slug        string `json:"slug"`
	Name        string `json:"name"`
	ShortName   string `json:"short_name"`
	Region      string `json:"region"`
	AccentColor string `json:"accent_color"`
	Featured    bool   `json:"featured"`
	Active      bool   `json:"active"`
}

// PublicTeamContext is match CONTEXT (denormalized strings) — deliberately not
// a Team entity; it has no entity_id and no deep link (BLOCKED_BY_DOMAIN).
type PublicTeamContext struct {
	Name  string `json:"name"`
	Short string `json:"short"`
	Color string `json:"color"`
}

type PublicMatch struct {
	MatchID         string            `json:"match_id"`
	CompetitionID   string            `json:"competition_id"`
	CompetitionName string            `json:"competition_name"`
	HomeTeam        PublicTeamContext `json:"home_team"`
	AwayTeam        PublicTeamContext `json:"away_team"`
	KickoffTs       string            `json:"kickoff_ts"`
	State           string            `json:"state"`
	HomeScore       *int              `json:"home_score"`
	AwayScore       *int              `json:"away_score"`
}

type PublicPost struct {
	ID           string `json:"id"`
	AuthorID     string `json:"author_id"`
	AuthorType   string `json:"author_type"`
	AuthorName   string `json:"author_name"`
	AuthorAvatar string `json:"author_avatar"`
	Snippet      string `json:"snippet"` // matched terms wrapped in <b></b>
	CreatedAt    string `json:"created_at"`
	LikeCount    int    `json:"like_count"`
	CommentCount int    `json:"comment_count"`
}

// CategoryResponse is the public per-category page.
type CategoryResponse struct {
	Query      string `json:"query"`
	Category   string `json:"category"`
	Items      []Card `json:"items"`
	NextCursor string `json:"next_cursor"`
}

// AllResponse is the public aggregated discovery page — the ONLY place the
// "All" view exists. Cursors are per category (a client "sees more" of one
// category by switching to that category's endpoint with its cursor).
type AllResponse struct {
	Query            string            `json:"query"`
	Items            []Card            `json:"items"` // sorted by normalized_score
	Cursors          map[string]string `json:"cursors"`
	Partial          bool              `json:"partial"`
	FailedCategories []string          `json:"failed_categories"`
}

// CapabilitiesResponse enriches Social's capability contract with the
// Gateway-owned temporarily_unavailable dimension (a category that EXISTS but
// whose upstream is currently failing/degraded — distinct from blocked, which
// has no domain at all). Future surfaces (teams, players, live, radar) can move
// between these states without a contract change.
type CapabilitiesResponse struct {
	Enabled                []string          `json:"enabled"`
	Blocked                map[string]string `json:"blocked"`
	TemporarilyUnavailable []string          `json:"temporarily_unavailable"`
	Trending               string            `json:"trending"` // "UNAVAILABLE" in V1
}
