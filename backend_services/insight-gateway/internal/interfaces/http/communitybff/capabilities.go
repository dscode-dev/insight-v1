// FEATURE-COMMUNITIES-V1 Stage 2 — capabilities engine.
//
// The Gateway returns EXPLICIT capabilities so the Flutter client never has to
// infer permissions from roles. The client renders UI strictly from these
// booleans. Authorization enforcement still lives in Social's domain (the
// Stage-1 invariants) — capabilities are the client-facing projection of those
// rules; any actual mutation is re-validated server-side. Keeping the mapping
// here (one place) prevents the client from drifting from the domain.
package communitybff

// role constants (Gateway-local; mirror social.v1.CommunityRole wire strings).
const (
	roleNone      = "none"
	roleMember    = "member"
	roleModerator = "moderator"
	roleAdmin     = "admin"
	roleOwner     = "owner"
)

const (
	statusMember    = "member"
	statusNotMember = "not_member"
)

// Capabilities is the explicit permission set for the authenticated viewer in
// a specific community. Every client affordance maps to one of these.
type Capabilities struct {
	CanJoin             bool `json:"can_join"`
	CanLeave            bool `json:"can_leave"`
	CanCreateDiscussion bool `json:"can_create_discussion"`
	CanDeleteDiscussion bool `json:"can_delete_discussion"`
	CanManageMembers    bool `json:"can_manage_members"`
	CanInviteMembers    bool `json:"can_invite_members"`
	CanManageSettings   bool `json:"can_manage_settings"`
	CanViewAdminPanel   bool `json:"can_view_admin_panel"`
}

// capabilitiesFor derives the viewer's capabilities from their role + whether
// they are a member. `privacyPublic` gates joining (V1 is always public).
//
// Rules (consistent with the Stage-1 domain invariants):
//   - not a member        → can only join (public communities).
//   - member              → participate (create discussion) + leave.
//   - moderator           → + delete discussions (moderation).
//   - admin               → + manage/invite members, settings, admin panel.
//   - owner               → everything admin can, but CANNOT leave (must
//                           transfer ownership first — a V1-absent capability).
func capabilitiesFor(role string, isMember, privacyPublic bool) Capabilities {
	c := Capabilities{}
	if !isMember {
		c.CanJoin = privacyPublic
		return c
	}
	// Members and above:
	c.CanCreateDiscussion = true
	c.CanLeave = true // narrowed below for the owner

	switch role {
	case roleModerator:
		c.CanDeleteDiscussion = true
	case roleAdmin:
		c.CanDeleteDiscussion = true
		c.CanManageMembers = true
		c.CanInviteMembers = true
		c.CanManageSettings = true
		c.CanViewAdminPanel = true
	case roleOwner:
		c.CanDeleteDiscussion = true
		c.CanManageMembers = true
		c.CanInviteMembers = true
		c.CanManageSettings = true
		c.CanViewAdminPanel = true
		// Invariant: the owner cannot leave without transferring ownership,
		// which V1 does not expose. Never surface a Leave affordance.
		c.CanLeave = false
	}
	return c
}
