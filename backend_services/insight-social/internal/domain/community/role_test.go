package community

import "testing"

func TestRole_StringParseRoundTrip(t *testing.T) {
	for _, r := range []Role{RoleOwner, RoleAdmin, RoleModerator, RoleMember} {
		if got := ParseRole(r.String()); got != r {
			t.Fatalf("round-trip %v: got %v", r, got)
		}
	}
}

func TestRole_ParseUnknownIsLeastPrivilege(t *testing.T) {
	if ParseRole("superadmin") != RoleMember {
		t.Fatal("unknown role must fall back to RoleMember (least privilege)")
	}
	if ParseRole("") != RoleMember {
		t.Fatal("empty role must fall back to RoleMember")
	}
}

func TestRole_PriorityOrdersOwnerFirst(t *testing.T) {
	// Strictly increasing priority number = less privileged / shown later.
	want := []Role{RoleOwner, RoleAdmin, RoleModerator, RoleMember}
	for i := 1; i < len(want); i++ {
		if !(want[i-1].Priority() < want[i].Priority()) {
			t.Fatalf("priority not ordered: %v(%d) !< %v(%d)",
				want[i-1], want[i-1].Priority(), want[i], want[i].Priority())
		}
	}
	if RoleOwner.Priority() != 0 {
		t.Fatal("owner must have priority 0 (listed first)")
	}
}

func TestRole_LegacyIsModeratorCompat(t *testing.T) {
	// is_moderator (deprecated) must be true for moderator and ABOVE, so old
	// readers still treat privileged members as moderators.
	cases := map[Role]bool{
		RoleOwner: true, RoleAdmin: true, RoleModerator: true, RoleMember: false,
	}
	for r, want := range cases {
		if r.LegacyIsModerator() != want {
			t.Fatalf("%v.LegacyIsModerator()=%v want %v", r, r.LegacyIsModerator(), want)
		}
		if r.IsPrivileged() != want {
			t.Fatalf("%v.IsPrivileged()=%v want %v", r, r.IsPrivileged(), want)
		}
	}
}
