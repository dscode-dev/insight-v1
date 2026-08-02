package community

import (
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestNewTopic_RequiresOwner(t *testing.T) {
	if _, err := NewTopic("tatica-fc", "Tática FC", "4-3-3 e afins", "", uuid.Nil); !errors.Is(err, ErrOwnerRequired) {
		t.Fatalf("new topic community without owner must fail, got %v", err)
	}
	owner := uuid.New()
	c, err := NewTopic("tatica-fc", "Tática FC", "4-3-3 e afins", "", owner)
	if err != nil {
		t.Fatalf("valid owned community should construct: %v", err)
	}
	if !c.OwnerAssigned() || c.OwnerUserID() == nil || *c.OwnerUserID() != owner {
		t.Fatal("owner must be set on the new community")
	}
	if c.Kind() != KindTopic {
		t.Fatal("expected KindTopic")
	}
}

func TestReconstitute_OwnerUnassignedLegacy(t *testing.T) {
	// A legacy/competition community reconstitutes with nil owner and reports
	// OWNER_UNASSIGNED honestly (never a fabricated owner).
	c := Reconstitute(uuid.New(), "brasileirao", "Brasileirão", "Série A",
		KindCompetition, nil, "#5BA8FF", 10, 2, time.Now().UTC(), nil)
	if c.OwnerAssigned() {
		t.Fatal("legacy/competition community must be OWNER_UNASSIGNED")
	}
	if c.OwnerUserID() != nil {
		t.Fatal("owner must be nil, not fabricated")
	}
}

func TestMembersCursor_RoundTripAndStableOrder(t *testing.T) {
	u := uuid.New()
	j := time.Date(2026, 3, 1, 12, 0, 0, 0, time.UTC)
	enc := EncodeMembersCursor(RoleModerator, j, u)
	got, err := DecodeMembersCursor(enc)
	if err != nil || got == nil {
		t.Fatalf("decode failed: %v", err)
	}
	if got.P != RoleModerator.Priority() || !got.J.Equal(j) || got.U != u {
		t.Fatalf("cursor round-trip mismatch: %+v", got)
	}
	// The cursor leads with role priority — the stable primary sort key.
	if EncodeMembersCursor(RoleOwner, j, u) == EncodeMembersCursor(RoleMember, j, u) {
		t.Fatal("different roles must yield different cursors (priority is part of the key)")
	}
}

func TestMembersCursor_EmptyAndMalformed(t *testing.T) {
	got, err := DecodeMembersCursor("")
	if err != nil || got != nil {
		t.Fatalf("empty cursor => first page (nil, nil), got %+v %v", got, err)
	}
	if _, err := DecodeMembersCursor("!!!not-base64!!!"); !errors.Is(err, ErrInvalidMembersCursor) {
		t.Fatalf("malformed cursor must be rejected, got %v", err)
	}
}
