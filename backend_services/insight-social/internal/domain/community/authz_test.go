package community

import (
	"errors"
	"testing"
)

func TestCanLeave_OwnerBlockedOthersAllowed(t *testing.T) {
	if err := CanLeave(RoleOwner); !errors.Is(err, ErrOwnerCannotLeave) {
		t.Fatalf("owner must be blocked from leaving, got %v", err)
	}
	for _, r := range []Role{RoleAdmin, RoleModerator, RoleMember} {
		if err := CanLeave(r); err != nil {
			t.Fatalf("%v must be allowed to leave, got %v", r, err)
		}
	}
}

func TestCanChangeRole_OwnerImmutable(t *testing.T) {
	// Cannot demote the owner, whoever the actor is.
	if err := CanChangeRole(RoleOwner, RoleOwner, RoleAdmin); !errors.Is(err, ErrOwnerImmutable) {
		t.Fatalf("owner demotion must be blocked, got %v", err)
	}
	// Cannot promote anyone to owner via a common role change.
	if err := CanChangeRole(RoleOwner, RoleAdmin, RoleOwner); !errors.Is(err, ErrCannotAssignOwner) {
		t.Fatalf("promotion to owner must be blocked, got %v", err)
	}
}

func TestCanChangeRole_ActorAuthority(t *testing.T) {
	// Owner may manage member/moderator/admin.
	for _, nr := range []Role{RoleMember, RoleModerator, RoleAdmin} {
		if err := CanChangeRole(RoleOwner, RoleMember, nr); err != nil {
			t.Fatalf("owner→%v should be allowed, got %v", nr, err)
		}
	}
	// Admin may manage member/moderator, but NOT create or touch admins.
	if err := CanChangeRole(RoleAdmin, RoleMember, RoleModerator); err != nil {
		t.Fatalf("admin promoting member→moderator should be allowed, got %v", err)
	}
	if err := CanChangeRole(RoleAdmin, RoleMember, RoleAdmin); !errors.Is(err, ErrRoleChangeDenied) {
		t.Fatal("admin must NOT create another admin")
	}
	if err := CanChangeRole(RoleAdmin, RoleAdmin, RoleMember); !errors.Is(err, ErrRoleChangeDenied) {
		t.Fatal("admin must NOT demote a peer admin")
	}
	// Moderators and members can change nobody.
	if err := CanChangeRole(RoleModerator, RoleMember, RoleModerator); !errors.Is(err, ErrRoleChangeDenied) {
		t.Fatal("moderator must not change roles")
	}
	if err := CanChangeRole(RoleMember, RoleMember, RoleModerator); !errors.Is(err, ErrRoleChangeDenied) {
		t.Fatal("member must not change roles")
	}
}

func TestReconcileJoinRole_NeverOverwritesPrivileged(t *testing.T) {
	// A (re-)join must not demote an existing privileged member.
	for _, r := range []Role{RoleOwner, RoleAdmin, RoleModerator} {
		if got := ReconcileJoinRole(r); got != r {
			t.Fatalf("join must preserve %v, got %v", r, got)
		}
	}
	// A fresh/absent membership settles on MEMBER.
	if got := ReconcileJoinRole(RoleUnspecified); got != RoleMember {
		t.Fatalf("fresh join must be RoleMember, got %v", got)
	}
	if got := ReconcileJoinRole(RoleMember); got != RoleMember {
		t.Fatalf("existing member stays member, got %v", got)
	}
}

func TestTransferOwnership_UnsupportedInV1(t *testing.T) {
	if err := TransferOwnership(); !errors.Is(err, ErrTransferUnsupported) {
		t.Fatalf("ownership transfer must be an explicit absent capability, got %v", err)
	}
}
