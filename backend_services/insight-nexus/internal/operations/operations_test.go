package operations

import "testing"

func TestCapabilityEnabledReportsDisabledSubsystem(t *testing.T) {
	capability := CapabilityEnabled("publication", "controlled publishing", false)
	if capability.Enabled {
		t.Fatal("disabled subsystem must not be advertised as enabled")
	}
	if capability.Name != "publication" {
		t.Fatalf("capability name = %q", capability.Name)
	}
}
