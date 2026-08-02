// Package event holds the RawSportsEvent + CanonicalSportsEvent
// aggregates + the Status enum that gates downstream behaviour.
package event

import "errors"

// Status declares where a CanonicalSportsEvent sits in its lifecycle.
//
// Lifecycle (mostly forward; rejected/stale are terminal):
//
//	candidate    initial state — only one raw seen, or sources still
//	             being accumulated. Confidence is provisional.
//	confirmed    enough corroborating raws + no contradictions —
//	             this is "platform truth". Downstream ML consumes it.
//	conflicting  >1 raw disagrees on the payload for the same identity.
//	             Confidence is dropped; downstream MUST treat the event
//	             as ambiguous (the frontend should NOT render it as
//	             confirmed fact).
//	rejected     violated a validation rule (e.g. malformed payload,
//	             confidence outside [0,1]). Persisted for audit; the
//	             publishing layer must never emit a rejected event.
//	stale        ingested but no longer current (e.g. observed_at >
//	             configured staleness budget at re-check time). Soft-
//	             archived: surfaces in audit, never in inference.
type Status string

const (
	StatusCandidate   Status = "candidate"
	StatusConfirmed   Status = "confirmed"
	StatusConflicting Status = "conflicting"
	StatusRejected    Status = "rejected"
	StatusStale       Status = "stale"
)

var allStatuses = []Status{
	StatusCandidate, StatusConfirmed, StatusConflicting, StatusRejected, StatusStale,
}

// AllStatuses returns a copy of every valid Status. Used by the
// postgres CHECK constraint generator + tests.
func AllStatuses() []Status {
	out := make([]Status, len(allStatuses))
	copy(out, allStatuses)
	return out
}

// IsValid reports whether s is one of the declared constants.
func (s Status) IsValid() bool {
	for _, v := range allStatuses {
		if v == s {
			return true
		}
	}
	return false
}

// IsTerminal — rejected + stale never advance to confirmed without
// human intervention. Used by the orchestrator to short-circuit
// re-evaluation cycles.
func (s Status) IsTerminal() bool {
	return s == StatusRejected || s == StatusStale
}

// ErrInvalidStatus is the canonical error when an invalid status
// string lands at the boundary (e.g. cache replay from an older
// schema version that added/removed values).
var ErrInvalidStatus = errors.New("event: invalid status")
