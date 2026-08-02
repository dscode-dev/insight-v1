package signal

// State mirrors social.v1.SignalState.
//
// W2.1b note: the schema doesn't store this column. The state is
// *derived* at read time by joining against reputation_events:
//   - `kind = 'signal_validated'` → StateValidated
//   - `kind = 'signal_flagged'`   → StateFlagged
//   - `kind = 'signal_invalidated'` → StateInvalidated
//   - no event yet                 → StatePending
//
// The repo's read paths do the join; the publisher emits StatePending
// always (validation lives in a downstream consumer, not this RPC).
type State int

const (
	StateUnspecified State = 0
	StatePending     State = 1
	StateValidated   State = 2
	StateFlagged     State = 3
	StateInvalidated State = 4
)

func (s State) String() string {
	switch s {
	case StatePending:
		return "pending"
	case StateValidated:
		return "validated"
	case StateFlagged:
		return "flagged"
	case StateInvalidated:
		return "invalidated"
	default:
		return "unspecified"
	}
}

// ParseStateFromEventKind maps the reputation_events.kind values that
// represent signal evaluation outcomes back to a State. Anything else
// (regular reputation deltas) returns StateUnspecified.
func ParseStateFromEventKind(kind string) State {
	switch kind {
	case "signal_validated":
		return StateValidated
	case "signal_flagged":
		return StateFlagged
	case "signal_invalidated":
		return StateInvalidated
	default:
		return StateUnspecified
	}
}
