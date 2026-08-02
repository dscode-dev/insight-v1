package console

import "testing"

func TestCapabilityValidation(t *testing.T) {
	valid := []string{"social.content.moderate", "platform.operation.create", "atlas.intelligence.read"}
	for _, c := range valid {
		if !capabilityRe.MatchString(c) {
			t.Errorf("expected %q to be a valid capability", c)
		}
	}
	invalid := []string{"", "bad", "a.b", "A.B.C", "social..moderate", "social content moderate", "../../etc"}
	for _, c := range invalid {
		if capabilityRe.MatchString(c) {
			t.Errorf("expected %q to be INVALID", c)
		}
	}
}

func TestAuditStatuses(t *testing.T) {
	for _, s := range []string{"AUTHORIZED", "DENIED", "STARTED", "COMPLETED", "FAILED", "CANCELLED"} {
		if !auditStatuses[s] {
			t.Errorf("expected %q to be a valid status", s)
		}
	}
	for _, s := range []string{"", "BOGUS", "authorized", "DELETED"} {
		if auditStatuses[s] {
			t.Errorf("expected %q to be INVALID", s)
		}
	}
}

func TestSanitizeMetaDropsSecretsAndObjects(t *testing.T) {
	in := map[string]any{
		"action":        "remove_content",
		"token":         "SECRET",
		"authorization": "Bearer x",
		"password":      "p",
		"x-internal":    "y",
		"nested":        map[string]any{"a": 1}, // object dropped
		"list":          []any{1, 2},            // array dropped
		"count":         float64(3),
		"flag":          true,
	}
	out := sanitizeMeta(in)
	if out["action"] != "remove_content" || out["count"] != float64(3) || out["flag"] != true {
		t.Fatalf("scalar fields not preserved: %+v", out)
	}
	for _, k := range []string{"token", "authorization", "password", "x-internal", "nested", "list"} {
		if _, ok := out[k]; ok {
			t.Errorf("expected %q to be dropped from metadata", k)
		}
	}
}

func TestClipBounds(t *testing.T) {
	long := make([]byte, 1000)
	for i := range long {
		long[i] = 'x'
	}
	if got := clip(string(long), 512); len(got) != 512 {
		t.Fatalf("expected clip to 512, got %d", len(got))
	}
	if got := clip("short", 512); got != "short" {
		t.Fatalf("expected passthrough, got %q", got)
	}
}
