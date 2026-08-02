package community

// Ownership + role invariants (pure domain policy). These functions are the
// single place the rules live; the repository transactions and the gRPC layer
// call them rather than re-deriving the policy. Enforced here so they hold
// regardless of the calling path.
//
// FEATURE-COMMUNITIES-V1 minimum invariants:
//   1. A community has at most one owner (also enforced structurally by the
//      partial-unique index ux_community_members_one_owner).
//   2. The owner cannot leave without an explicit ownership transfer.
//   3. The owner cannot be removed or demoted by a generic operation.
//   4. An admin cannot promote anyone to owner via a common operation.
//   5. Only authorized actors can change roles.
//   6. Leaving is idempotent for common members (handled at repo: NotMember).
//   7. Join must not overwrite an existing privileged role.
//   8. Ownership transfer is NOT a V1 capability — protected, not faked.

// CanLeave reports whether a member holding leaverRole may leave. The owner is
// blocked (invariant 2) — leaving would orphan the community. Everyone else
// may leave; the repository makes the delete idempotent (ErrNotMember when the
// row is already gone).
func CanLeave(leaverRole Role) error {
	if leaverRole == RoleOwner {
		return ErrOwnerCannotLeave
	}
	return nil
}

// CanChangeRole reports whether actorRole may change targetRole to newRole.
//
// Rules:
//   - The owner role is immutable through this path: you cannot demote the
//     owner (invariant 3) nor promote anyone to owner (invariants 4 + 8) —
//     ownership only moves via a dedicated transfer, which V1 does not expose.
//   - Only OWNER or ADMIN may change roles at all (invariant 5).
//   - An ADMIN may manage MEMBER/MODERATOR but may not touch ADMINs or the
//     OWNER (an admin cannot create or unmake peers/superiors).
//   - An OWNER may manage MEMBER/MODERATOR/ADMIN.
func CanChangeRole(actorRole, targetRole, newRole Role) error {
	// Promoting to owner or demoting the owner is never allowed here.
	if newRole == RoleOwner {
		return ErrCannotAssignOwner
	}
	if targetRole == RoleOwner {
		return ErrOwnerImmutable
	}
	switch actorRole {
	case RoleOwner:
		return nil // may set member/moderator/admin on any non-owner
	case RoleAdmin:
		// Admins manage only members and moderators, never other admins.
		if targetRole == RoleAdmin || newRole == RoleAdmin {
			return ErrRoleChangeDenied
		}
		return nil
	default:
		return ErrRoleChangeDenied
	}
}

// ReconcileJoinRole returns the role a (re-)join should settle on, given any
// existing role. Join must never overwrite an existing privileged role
// (invariant 7): a moderator/admin/owner who somehow re-runs join keeps their
// role. A brand-new member (RoleUnspecified/absent) joins as RoleMember.
func ReconcileJoinRole(existing Role) Role {
	if existing.IsPrivileged() || existing == RoleOwner {
		return existing
	}
	return RoleMember
}

// TransferOwnership is intentionally unimplemented in V1. Callers that need it
// must surface it as an absent capability, not a partial endpoint/UI.
func TransferOwnership() error { return ErrTransferUnsupported }
