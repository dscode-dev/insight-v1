// Package realtime owns the SSE/WebSocket fan-out of derived-stream
// events to subscribed Flutter clients.
//
// Pipeline:
//
//	Atlas → Redis stream (insight:stream:derived:p0..p7)
//	                      │
//	                      ▼  XREAD batched
//	               RealtimeBroker (1 goroutine)
//	                      │
//	          ┌───────────┼───────────┐
//	          ▼           ▼           ▼  per-subscriber filter + chan
//	     Subscription Subscription Subscription
//	          │           │           │
//	          ▼           ▼           ▼  SSE handler streams to client
//	       client      client      client
//
// Wire format on the Redis side is Atlas's DerivedPublisher envelope
// — we don't mutate it, just decode + filter.
package realtime

// Event is one decoded derived-stream entry. The payload is left as a
// raw JSON string (encoded by Atlas via orjson) — the SSE handler
// writes it through unmodified so the Flutter client sees exactly the
// published shape.
type Event struct {
	EventID    string `json:"event_id"`
	MatchID    string `json:"match_id,omitempty"`
	EventType  string `json:"event_type"`
	RegionCode string `json:"region_code,omitempty"`
	TsIngest   string `json:"ts_ingest,omitempty"`
	Stream     string `json:"stream,omitempty"`
	// Payload is the JSON value the Atlas emitter published. Stored
	// as []byte so we serialize without re-parsing.
	Payload []byte `json:"payload"`
}
