package realtime

import (
	"errors"
	"strings"
)

// ErrInvalidFilter — parsing failed (bad UUID, too long token, ...).
// SSE handler maps to HTTP 400 before opening the stream.
var ErrInvalidFilter = errors.New("invalid_filter")

// SubscriptionFilters narrows the firehose to events the caller cares
// about. Nil set = no filter on that dimension (accept all).
//
// Both filters are AND-combined: an event matches when its match_id
// is in MatchIDs AND its event_type is in EventTypes.
type SubscriptionFilters struct {
	MatchIDs   map[string]struct{}
	EventTypes map[string]struct{}
}

// Match returns true when the event passes both filter dimensions.
func (f SubscriptionFilters) Match(ev *Event) bool {
	if f.MatchIDs != nil {
		if _, ok := f.MatchIDs[ev.MatchID]; !ok {
			return false
		}
	}
	if f.EventTypes != nil {
		if _, ok := f.EventTypes[ev.EventType]; !ok {
			return false
		}
	}
	return true
}

// ParseFilters reads the query-string forms used by the SSE endpoint:
//
//	match_ids="<uuid>,<uuid>,..."
//	event_types="MARKET_SNAPSHOT,METRIC_TICK,HUMAN_SIGNAL,..."
//
// Empty input on either side = "no filter on that axis".
//
// Defensive limits prevent absurd inputs from blowing memory:
//   - tokens trimmed to 64 chars each (matches the legacy BFF's cap)
//   - up to 256 unique entries per dimension
func ParseFilters(matchIDsRaw, eventTypesRaw string) (SubscriptionFilters, error) {
	out := SubscriptionFilters{}
	if mids, err := parseCSV(matchIDsRaw); err != nil {
		return out, err
	} else if len(mids) > 0 {
		out.MatchIDs = mids
	}
	if ets, err := parseCSV(eventTypesRaw); err != nil {
		return out, err
	} else if len(ets) > 0 {
		out.EventTypes = ets
	}
	return out, nil
}

const (
	maxTokenLen   = 64
	maxFilterSize = 256
)

func parseCSV(raw string) (map[string]struct{}, error) {
	if raw == "" {
		return nil, nil
	}
	out := make(map[string]struct{})
	for _, piece := range strings.Split(raw, ",") {
		p := strings.TrimSpace(piece)
		if p == "" {
			continue
		}
		if len(p) > maxTokenLen {
			return nil, ErrInvalidFilter
		}
		out[p] = struct{}{}
		if len(out) > maxFilterSize {
			return nil, ErrInvalidFilter
		}
	}
	return out, nil
}
