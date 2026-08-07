// FEATURE-COMMUNITIES-V1 Stage 2 — Community Orchestrator public contract.
//
// These DTOs are the DEFINITIVE public contract. They are Gateway-owned and do
// NOT reuse the social.v1 proto structs — Social may evolve internally without
// breaking clients. Mapping proto → DTO happens only in this package.
//
// Editorial invariant (ADR-0001): the community's official content is
// Discussions, never Posts. The detail is an AGGREGATE (header + counters +
// role distribution + capabilities), NOT a mirror of the internal model, and
// never carries members/admins/moderators arrays — those come from the
// dedicated paginated /members endpoint.
package communitybff

// Detail is the community overview aggregate. Everything the header + overview
// needs in ONE response; nothing large or paginated.
type Detail struct {
	ID          string `json:"id"`
	Slug        string `json:"slug"`
	Name        string `json:"name"`
	Description string `json:"description"`
	AvatarURL   string `json:"avatar_url"`
	BannerURL   string `json:"banner_url"`
	AccentColor string `json:"accent_color"`
	Kind        string `json:"kind"`    // topic | competition
	Privacy     string `json:"privacy"` // public (only value in V1 — honest, not fabricated)
	DeepLink    string `json:"deep_link"`

	// Counters (never arrays).
	MemberCount     int64      `json:"member_count"`
	DiscussionCount int64      `json:"discussion_count"`
	OnlineCount     int64      `json:"online_count"`
	RoleCounts      RoleCounts `json:"role_counts"`

	// Viewer context — lets the client render the header without extra calls.
	ViewerRole       string       `json:"viewer_role"`       // owner|admin|moderator|member|none
	MembershipStatus string       `json:"membership_status"` // member|not_member
	OwnerAssigned    bool         `json:"owner_assigned"`    // false => OWNER_UNASSIGNED (legacy/competition)
	Capabilities     Capabilities `json:"capabilities"`

	// partial=true when a non-critical upstream (stats / viewer membership)
	// failed but the community core loaded. failed_sections names them. The
	// core community (name/id) is never partial — its failure is an error.
	Partial        bool     `json:"partial"`
	FailedSections []string `json:"failed_sections,omitempty"`
}

type RoleCounts struct {
	Owner     int64 `json:"owner"`
	Admin     int64 `json:"admin"`
	Moderator int64 `json:"moderator"`
	Member    int64 `json:"member"`
}

// Member is one enriched row of the paginated members list. Public profile
// fields only.
type Member struct {
	UserID      string `json:"user_id"`
	Username    string `json:"username"`
	DisplayName string `json:"display_name"`
	Initials    string `json:"initials"`
	AccentColor string `json:"accent_color"`
	AvatarURL   string `json:"avatar_url"`
	Reputation  int32  `json:"reputation"`
	Role        string `json:"role"`
	DeepLink    string `json:"deep_link"` // /users/{id}
}

type MembersPage struct {
	Members    []Member `json:"members"`
	NextCursor string   `json:"next_cursor,omitempty"`
	RoleFilter string   `json:"role_filter,omitempty"` // echoes the applied projection, if any
}

// Discussion is one row of the community feed (Discussions domain ONLY). It is
// deliberately NOT the Post shape — the community feed is a distinct experience
// (a forum-like conversation), surfaced with its own fields (reply/activity).
type Discussion struct {
	ID             string `json:"id"`
	CommunityID    string `json:"community_id"`
	AuthorID       string `json:"author_id"`
	Title          string `json:"title"`
	ReplyCount     int64  `json:"reply_count"`
	ReactionCount  int64  `json:"reaction_count"`
	LastActivityTs string `json:"last_activity_ts"`
	DeepLink       string `json:"deep_link"` // /discussion/{id}
}

type DiscussionsPage struct {
	Discussions []Discussion `json:"discussions"`
	NextCursor  string       `json:"next_cursor,omitempty"`
}

// MembershipResult is returned by join/leave — the new viewer state + the
// refreshed capabilities so the client updates the UI without re-fetching.
type MembershipResult struct {
	CommunityID      string       `json:"community_id"`
	ViewerRole       string       `json:"viewer_role"`
	MembershipStatus string       `json:"membership_status"`
	MemberCount      int64        `json:"member_count"`
	Capabilities     Capabilities `json:"capabilities"`
}

// ---- deep links (Gateway builds; client only validates + navigates) ----

func communityDeepLink(id string) string  { return "/hub/community/" + id }
func userDeepLink(id string) string       { return "/users/" + id }
func discussionDeepLink(id string) string { return "/discussion/" + id }
