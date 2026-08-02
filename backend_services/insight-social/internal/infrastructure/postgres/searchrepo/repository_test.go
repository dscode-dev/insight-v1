package searchrepo

import (
	"testing"

	domsearch "github.com/konoha-labs/insight-social/internal/domain/search"
)

func row(id string) keyed[string] {
	return keyed[string]{item: id, cur: domsearch.Cursor{Cat: "users", S1: "1", ID: id}}
}

// limit+1 fetch semantics: the overflow row proves more pages; the emitted
// cursor belongs to the LAST KEPT row (never the overflow row).
func TestPageOut(t *testing.T) {
	// Fewer than limit → no next cursor.
	p := pageOut([]keyed[string]{row("a"), row("b")}, 5)
	if len(p.Items) != 2 || p.NextCursor != "" {
		t.Fatalf("partial page must have no cursor: %+v", p)
	}
	// Exactly limit (no overflow row) → last page, no cursor.
	p = pageOut([]keyed[string]{row("a"), row("b")}, 2)
	if len(p.Items) != 2 || p.NextCursor != "" {
		t.Fatalf("exact page without overflow must have no cursor: %+v", p)
	}
	// limit+1 rows → trim to limit, cursor = last KEPT row ("b", not "c").
	p = pageOut([]keyed[string]{row("a"), row("b"), row("c")}, 2)
	if len(p.Items) != 2 {
		t.Fatalf("must trim to limit: %+v", p.Items)
	}
	cur, err := domsearch.DecodeCursor(p.NextCursor, domsearch.CategoryUsers)
	if err != nil || cur.ID != "b" {
		t.Fatalf("cursor must resume after last KEPT row, got %+v err=%v", cur, err)
	}
	// Empty input.
	if p := pageOut([]keyed[string]{}, 2); len(p.Items) != 0 || p.NextCursor != "" {
		t.Fatal("empty input must be empty page")
	}
}
