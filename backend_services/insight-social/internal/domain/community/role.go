package community

// Role is the canonical authorization + presentation role of a membership.
// It mirrors social.v1.CommunityRole. `community_members.role` is the SOURCE
// OF TRUTH; the legacy is_moderator bool is derived from it during
// FEATURE-COMMUNITIES-V1 (true for RoleModerator and above).
//
// The integer ordering is deliberate: higher = more privileged. Do not
// reorder — persistence uses the String() form, but Priority() ranking and
// the ">= " comparisons below rely on this order.
type Role int

const (
	RoleUnspecified Role = iota
	RoleMember
	RoleModerator
	RoleAdmin
	RoleOwner
)

// DB storage strings (community_members.role CHECK constraint).
func (r Role) String() string {
	switch r {
	case RoleOwner:
		return "owner"
	case RoleAdmin:
		return "admin"
	case RoleModerator:
		return "moderator"
	case RoleMember:
		return "member"
	default:
		return "member" // unspecified persists as the least-privileged role
	}
}

// ParseRole maps a stored string back to a Role. Unknown values fall back to
// RoleMember (least privilege) rather than panicking on unexpected data.
func ParseRole(s string) Role {
	switch s {
	case "owner":
		return RoleOwner
	case "admin":
		return RoleAdmin
	case "moderator":
		return RoleModerator
	case "member":
		return RoleMember
	default:
		return RoleMember
	}
}

// Priority ranks roles for the members listing: OWNER first (0), then ADMIN,
// MODERATOR, MEMBER. Lower number = shown first. Kept in one place so the SQL
// ordering and the cursor comparator can never drift.
func (r Role) Priority() int {
	switch r {
	case RoleOwner:
		return 0
	case RoleAdmin:
		return 1
	case RoleModerator:
		return 2
	default: // RoleMember / unspecified
		return 3
	}
}

// IsPrivileged reports whether the role is moderator or above — the semantic
// the legacy is_moderator bool now carries (kept for wire compatibility).
func (r Role) IsPrivileged() bool { return r >= RoleModerator }

// LegacyIsModerator is what the deprecated is_moderator column/field should
// hold given a role, so old readers keep working while `role` is the truth.
func (r Role) LegacyIsModerator() bool { return r.IsPrivileged() }
