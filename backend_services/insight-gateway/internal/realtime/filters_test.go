package realtime

import (
	"strings"
	"testing"
)

func TestParseFilters_Empty(t *testing.T) {
	f, err := ParseFilters("", "")
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if f.MatchIDs != nil || f.EventTypes != nil {
		t.Fatalf("expected nil filters, got %+v", f)
	}
}

func TestParseFilters_Trims(t *testing.T) {
	f, err := ParseFilters("  a , b ,, c ", "X,Y")
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if len(f.MatchIDs) != 3 {
		t.Fatalf("MatchIDs len=%d", len(f.MatchIDs))
	}
	for _, want := range []string{"a", "b", "c"} {
		if _, ok := f.MatchIDs[want]; !ok {
			t.Fatalf("MatchIDs missing %q", want)
		}
	}
	if len(f.EventTypes) != 2 {
		t.Fatalf("EventTypes len=%d", len(f.EventTypes))
	}
}

func TestParseFilters_RejectsTooLongToken(t *testing.T) {
	long := strings.Repeat("a", maxTokenLen+1)
	if _, err := ParseFilters(long, ""); err != ErrInvalidFilter {
		t.Fatalf("expected ErrInvalidFilter, got %v", err)
	}
}

func TestSubscriptionFilters_Match(t *testing.T) {
	tt := []struct {
		name    string
		filters SubscriptionFilters
		ev      Event
		want    bool
	}{
		{
			"no filters → accept all",
			SubscriptionFilters{},
			Event{MatchID: "m1", EventType: "MARKET_SNAPSHOT"},
			true,
		},
		{
			"match_ids includes",
			SubscriptionFilters{MatchIDs: setOf("m1", "m2")},
			Event{MatchID: "m1", EventType: "X"},
			true,
		},
		{
			"match_ids excludes",
			SubscriptionFilters{MatchIDs: setOf("m1", "m2")},
			Event{MatchID: "m3", EventType: "X"},
			false,
		},
		{
			"event_types AND with match_ids",
			SubscriptionFilters{
				MatchIDs:   setOf("m1"),
				EventTypes: setOf("MARKET_SNAPSHOT"),
			},
			Event{MatchID: "m1", EventType: "METRIC_TICK"},
			false,
		},
		{
			"event_types both match",
			SubscriptionFilters{
				MatchIDs:   setOf("m1"),
				EventTypes: setOf("MARKET_SNAPSHOT"),
			},
			Event{MatchID: "m1", EventType: "MARKET_SNAPSHOT"},
			true,
		},
	}
	for _, tc := range tt {
		t.Run(tc.name, func(t *testing.T) {
			if got := tc.filters.Match(&tc.ev); got != tc.want {
				t.Fatalf("got %v want %v", got, tc.want)
			}
		})
	}
}

func setOf(vs ...string) map[string]struct{} {
	out := make(map[string]struct{}, len(vs))
	for _, v := range vs {
		out[v] = struct{}{}
	}
	return out
}
