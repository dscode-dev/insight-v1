package search

import (
	"strings"
	"testing"
)

func TestNormalizeQuery(t *testing.T) {
	q, err := NormalizeQuery("  Neymar   JR  ")
	if err != nil || q != "neymar jr" {
		t.Fatalf("normalize: got %q err=%v", q, err)
	}
	if _, err := NormalizeQuery(" a "); err != ErrQueryTooShort {
		t.Fatalf("1 rune must be too short, got %v", err)
	}
	if _, err := NormalizeQuery(strings.Repeat("x", MaxQueryLen+1)); err != ErrQueryTooLong {
		t.Fatalf("overlong must be rejected, got %v", err)
	}
	// Rune-counted: two multi-byte runes are valid.
	if _, err := NormalizeQuery("çã"); err != nil {
		t.Fatalf("2 multibyte runes must pass, got %v", err)
	}
}

func TestEscapeLike_WildcardAbuse(t *testing.T) {
	got := EscapeLike(`100%_\x`)
	want := `100\%\_\\x`
	if got != want {
		t.Fatalf("escape: got %q want %q", got, want)
	}
}

func TestClampLimit(t *testing.T) {
	if ClampLimit(0) != DefaultLimit || ClampLimit(-3) != DefaultLimit {
		t.Fatal("non-positive → default")
	}
	if ClampLimit(999) != MaxLimit {
		t.Fatal("over-max → clamped")
	}
	if ClampLimit(7) != 7 {
		t.Fatal("in-range preserved")
	}
}

func TestCursorRoundTripAndTypeTag(t *testing.T) {
	c := Cursor{Cat: string(CategoryUsers), B: 2, S1: "87", ID: "0f0e0d0c-0b0a-4908-8706-050403020100"}
	enc := c.Encode()

	dec, err := DecodeCursor(enc, CategoryUsers)
	if err != nil || dec == nil || *dec != c {
		t.Fatalf("round-trip failed: %+v err=%v", dec, err)
	}
	// A users cursor MUST NOT be replayable against another category.
	if _, err := DecodeCursor(enc, CategoryPosts); err != ErrCursorCategory {
		t.Fatalf("cross-category replay must fail, got %v", err)
	}
	// Empty = first page.
	if cur, err := DecodeCursor("", CategoryUsers); err != nil || cur != nil {
		t.Fatal("empty cursor must mean first page")
	}
	// Garbage / tampered input is an explicit error.
	if _, err := DecodeCursor("!!not-base64!!", CategoryUsers); err != ErrInvalidCursor {
		t.Fatalf("garbage must be invalid, got %v", err)
	}
	if _, err := DecodeCursor("e30", CategoryUsers); err == nil { // "{}" — no id
		t.Fatal("cursor without id must be invalid")
	}
}
