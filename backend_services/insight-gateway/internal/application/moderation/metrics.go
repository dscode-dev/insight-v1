package moderation

// Metrics records UGC-safety counters (Store-A). Interface lives in the
// application layer so the service has no Prometheus dependency; the concrete
// implementation is infrastructure/modmetrics. A nil Metrics disables
// instrumentation (the service guards every call).
type Metrics interface {
	// Block records a block/unblock action (action: "block" | "unblock").
	Block(action string)
	// Report records a content report (label: reason).
	Report(reason string)
	// ModerationAction records an admin action (label: action).
	ModerationAction(action string)
}
