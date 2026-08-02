package notification

import (
	"encoding/json"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestNew_ValidatesAndDefaults(t *testing.T) {
	u := uuid.New()
	if _, err := New(uuid.Nil, TypeMention, PriorityNormal, "t", "b", Target{}, nil, "k"); !errors.Is(err, ErrInvalidUser) {
		t.Fatal("nil user must fail")
	}
	if _, err := New(u, TypeUnspecified, PriorityNormal, "t", "b", Target{}, nil, "k"); !errors.Is(err, ErrInvalidType) {
		t.Fatal("unspecified type must fail")
	}
	if _, err := New(u, TypeMention, PriorityNormal, "  ", "b", Target{}, nil, "k"); !errors.Is(err, ErrEmptyTitle) {
		t.Fatal("empty title must fail")
	}
	if _, err := New(u, TypeMention, PriorityNormal, "t", "b", Target{}, nil, ""); !errors.Is(err, ErrEmptyDedupKey) {
		t.Fatal("empty dedup key must fail")
	}
	n, err := New(u, TypeReaction, PriorityUnspecified, "t", "b", Target{}, nil, "k")
	if err != nil {
		t.Fatal(err)
	}
	if n.Priority() != PriorityNormal {
		t.Fatal("unspecified priority must default to normal")
	}
	if string(n.Payload()) != "{}" {
		t.Fatalf("empty payload must default to {}, got %s", n.Payload())
	}
}

func TestNotification_ImmutableExceptRead_StatusDerived(t *testing.T) {
	// A freshly created notification is unread; status derives from read_at.
	n, _ := New(uuid.New(), TypeMention, PriorityHigh, "t", "b", Target{}, nil, "k")
	if n.Status() != StatusUnread || n.IsRead() {
		t.Fatal("new notification must be unread")
	}
	// Reconstitute with a read_at → derived READ (no stored status column).
	ts := time.Now().UTC()
	read := Reconstitute(n.ID(), n.UserID(), TypeMention, PriorityHigh, "t", "b", Target{},
		json.RawMessage(`{}`), "k", ts, &ts)
	if read.Status() != StatusRead || !read.IsRead() {
		t.Fatal("read_at set must derive READ")
	}
	// Type/priority/title are stable (no mutators exist on the aggregate).
	if read.Type() != TypeMention || read.Priority() != PriorityHigh {
		t.Fatal("immutable fields must be stable")
	}
}

func TestDedupKey_DeterministicNotTimestamp(t *testing.T) {
	a := DedupKey("reaction", "discussion", "842", "user", "18")
	b := DedupKey("reaction", "discussion", "842", "user", "18")
	if a != b {
		t.Fatal("same event must produce the same key")
	}
	if a != "reaction:discussion:842:user:18" {
		t.Fatalf("unexpected key shape: %s", a)
	}
	// Different event → different key.
	if a == DedupKey("reply", "discussion", "842", "comment", "991") {
		t.Fatal("different events must differ")
	}
	// Empty parts are dropped (no ambiguous '::').
	if DedupKey("mention", "", "user", "55") != "mention:user:55" {
		t.Fatal("empty parts must be dropped")
	}
	// Ref helper.
	id := uuid.New()
	if Ref("Community", id) != "community:"+id.String() {
		t.Fatal("Ref must lowercase kind + append id")
	}
}

func TestCursor_RoundTripAndMalformed(t *testing.T) {
	ts := time.Date(2026, 5, 1, 10, 0, 0, 0, time.UTC)
	id := uuid.New()
	enc := EncodeCursor(ts, id)
	got, err := DecodeCursor(enc)
	if err != nil || got == nil || !got.C.Equal(ts) || got.I != id {
		t.Fatalf("round-trip failed: %+v %v", got, err)
	}
	if g, err := DecodeCursor(""); err != nil || g != nil {
		t.Fatal("empty cursor => nil,nil (first page)")
	}
	if _, err := DecodeCursor("@@notbase64@@"); !errors.Is(err, ErrInvalidCursor) {
		t.Fatal("malformed cursor must be rejected")
	}
}
