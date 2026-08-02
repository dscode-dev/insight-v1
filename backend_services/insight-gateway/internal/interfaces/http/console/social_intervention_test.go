// CONSOLE-SOCIAL-B — pure-unit proofs for the intervention command plane:
// capability→permission authorization (fail-closed), map completeness, and the
// structural actor-strip (operator identity can never come from the body).
package console

import (
	"encoding/json"
	"testing"
)

// allCommandCapabilities are the capabilities the 13 typed endpoints authorize.
var allCommandCapabilities = []string{
	"social.user.suspend", "social.user.ban",
	"social.content.hide", "social.content.restore",
	"social.agent.deactivate", "social.agent.reactivate",
	"trust.report.review", "trust.report.resolve", "trust.report.dismiss",
}

func TestCapPermission_CoversEveryCommand(t *testing.T) {
	for _, c := range allCommandCapabilities {
		if _, ok := capPermission[c]; !ok {
			t.Fatalf("capability %s has no permission mapping (fail-closed would deny it)", c)
		}
	}
}

func TestAuthorizeCap_SuperAdminAllowed(t *testing.T) {
	for _, c := range allCommandCapabilities {
		if _, ok := authorizeCap("super_admin", c); !ok {
			t.Fatalf("SuperAdmin must be authorized for %s", c)
		}
	}
}

func TestAuthorizeCap_ReadOnlyDenied(t *testing.T) {
	// A ReadOnly/analyst role lacks user.ban / feed.hide etc.
	for _, c := range []string{"social.user.ban", "social.content.hide", "social.agent.deactivate"} {
		if _, ok := authorizeCap("analyst", c); ok {
			t.Fatalf("ReadOnly/analyst must NOT be authorized for %s", c)
		}
	}
}

func TestAuthorizeCap_UnmappedCapabilityDenied(t *testing.T) {
	if _, ok := authorizeCap("super_admin", "social.user.delete"); ok {
		t.Fatal("unmapped capability must be denied even for SuperAdmin")
	}
}

// TestInterventionBody_StripsActorFields proves operator/moderator/actor fields
// in the request body are NEVER decoded — identity is server-derived only.
func TestInterventionBody_StripsActorFields(t *testing.T) {
	raw := `{"reason":"spam","operator_id":"spoofed","moderator_id":"spoofed","actor_id":"spoofed","session_id":"spoofed","suspend_days":7}`
	var b interventionBody
	if err := json.Unmarshal([]byte(raw), &b); err != nil {
		t.Fatal(err)
	}
	if b.Reason != "spam" || b.SuspendDays != 7 {
		t.Fatalf("legit fields must decode: %+v", b)
	}
	// Re-marshal the decoded struct and confirm no actor field survived.
	out, _ := json.Marshal(b)
	for _, forbidden := range []string{"operator", "moderator", "actor", "session"} {
		if containsField(string(out), forbidden) {
			t.Fatalf("actor field %q leaked into decoded command payload: %s", forbidden, out)
		}
	}
}

func containsField(s, sub string) bool {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}
