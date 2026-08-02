// Package social holds the gateway's Flutter-shaped BFF handlers for
// the social domain. Wire shapes mirror the legacy BFF's bff.py 1:1 so the
// Flutter client doesn't notice the cutover.
//
// W2.2 endpoints registered as NativeFlagged in main.go:
//
//	GET /v1/feed                              → FeedResponse
//	GET /v1/hub/bundle?segment=mine|hot|fresh → HubBundleResponse
//	GET /v1/hub/communities/{community_id}    → CommunityDetailResponse
//	GET /v1/profile/me/bundle                 → ProfileBundleResponse
package social

// ---- /v1/feed ----

// FeedItem mirrors the legacy bff FeedItem (snake_case on the wire, Flutter
// rename via build.yaml field_rename: snake).
type FeedItem struct {
	Kind     string  `json:"kind"` // "signal" | "discussion"
	ID       string  `json:"id"`
	MatchID  *string `json:"match_id,omitempty"` // omitempty matches Python's `None` behavior
	AuthorID string  `json:"author_id"`
	Body     string  `json:"body"`
	Ts       string  `json:"ts"` // ISO-8601 (RFC3339)
}

type FeedResponse struct {
	Items []FeedItem `json:"items"`
}

// ---- /v1/hub/bundle ----

// HubCommunity is the Flutter-shaped community summary on the Hub
// screen. Subset of social.v1.Community — drops competition_id and
// active_now (not surfaced in the Hub list cards).
type HubCommunity struct {
	ID          string `json:"id"`
	Slug        string `json:"slug"`
	Name        string `json:"name"`
	Topic       string `json:"topic"`
	Kind        string `json:"kind"` // "topic" | "competition"
	AccentColor string `json:"accent_color"`
	MemberCount int64  `json:"member_count"`
}

// HubDiscussion is a flattened discussion preview (no body — only the
// title + counts, matching the Hub feed card).
type HubDiscussion struct {
	ID             string `json:"id"`
	CommunityID    string `json:"community_id"`
	AuthorID       string `json:"author_id"`
	Title          string `json:"title"`
	ReplyCount     int64  `json:"reply_count"`
	LastActivityTs string `json:"last_activity_ts"`
}

// HubBundleResponse matches the legacy BFF's stub: 3 arrays, one per
// section of the Hub screen. `tipsters` stays empty until we model
// expert users separately (out of scope for W2.2).
type HubBundleResponse struct {
	Communities []HubCommunity  `json:"communities"`
	Tipsters    []any           `json:"tipsters"`
	Discussions []HubDiscussion `json:"discussions"`
}

// ---- /v1/hub/communities/{community_id} ----

// CommunityDetailResponse is a NEW shape (the legacy BFF returned 404 for
// this endpoint). Defined here so the wire contract is explicit.
// Flutter side: render community header + discussions list.
type CommunityDetailResponse struct {
	Community   HubCommunity    `json:"community"`
	Discussions []HubDiscussion `json:"discussions"`
	NextCursor  *string         `json:"next_cursor,omitempty"`
}

// ---- /v1/profile/me/bundle ----

// ProfileStats mirrors the legacy BFF's stub shape — same field names so
// the Flutter ProfileScreen parses without code changes.
type ProfileStats struct {
	UserID     string  `json:"user_id"`
	Reputation int32   `json:"reputation"`
	Posts      int64   `json:"posts"`    // = discussions started (no separate counter yet)
	Signals    int64   `json:"signals"`  // = signals_sent
	Accuracy   float64 `json:"accuracy"` // 0..1
}

type ProfileBundleResponse struct {
	Stats    ProfileStats `json:"stats"`
	Badges   []any        `json:"badges"`   // empty until badge engine ships
	Activity []any        `json:"activity"` // empty until activity log ships
}

// ---- /v1/discussions/{discussion_id} (Sprint A) ----

// DiscussionDetailResponse — header for the DiscussionThreadScreen.
// Carries denormalised author + community info so the screen renders
// the title row in one round-trip.
//
// Sprint B: reaction_count + liked_by_me populated from the Reactions
// aggregate via a parallel fetch in the BFF.
type DiscussionDetailResponse struct {
	ID                string  `json:"id"`
	Title             string  `json:"title"`
	Body              string  `json:"body"`
	CommunityID       string  `json:"community_id"`
	CommunityName     string  `json:"community_name,omitempty"`
	CommunityHandle   string  `json:"community_handle,omitempty"` // "#tatica"
	AuthorID          string  `json:"author_id"`
	AuthorDisplayName string  `json:"author_display_name,omitempty"`
	AuthorInitials    string  `json:"author_initials,omitempty"`
	AuthorAccent      string  `json:"author_accent,omitempty"` // #RRGGBB
	MatchID           *string `json:"match_id,omitempty"`
	ReplyCount        int64   `json:"reply_count"`
	ReactionCount     int64   `json:"reaction_count"`
	LikedByMe         bool    `json:"liked_by_me"`
	CreatedAt         string  `json:"created_at"`
	LastActivityTs    string  `json:"last_activity_ts"`
}

// DiscussionMessageDTO — one reply, with author info denormalised.
type DiscussionMessageDTO struct {
	ID                string `json:"id"`
	AuthorID          string `json:"author_id"`
	AuthorDisplayName string `json:"author_display_name,omitempty"`
	AuthorInitials    string `json:"author_initials,omitempty"`
	AuthorAccent      string `json:"author_accent,omitempty"`
	Body              string `json:"body"`
	Ts                string `json:"ts"`
}

type DiscussionMessagesResponse struct {
	Messages   []DiscussionMessageDTO `json:"messages"`
	NextCursor *string                `json:"next_cursor,omitempty"`
}

// PostMessageRequest is the JSON request body for POST .../messages.
// author_id is NEVER read from here — always taken from the JWT.
type PostMessageRequest struct {
	Body string `json:"body"`
}

// ---- /v1/reactions/discussion/{id} (Sprint B) ----

// ReactionDTO mirrors the social.v1.Reaction message but flattens the
// proto enum to a lowercase string for client consumption.
type ReactionDTO struct {
	UserID       string `json:"user_id"`
	DiscussionID string `json:"discussion_id"`
	Kind         string `json:"kind"` // "like" today; expand when more kinds land
	CreatedAt    string `json:"created_at"`
}
