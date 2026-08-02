// Package realtime exposes the SSE endpoint.
//
// Wire format mirrors the legacy BFF byte-for-byte so Flutter clients
// connected through either runtime see identical streams:
//
//	id: <event_id>
//	event: <event_type>
//	data: <json>
//	\n\n
//
// Plus periodic ": keepalive\n\n" comment lines so intermediary
// proxies (nginx / Envoy) don't idle-close the connection.
package realtime

import (
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-gateway/internal/domain/auth"
	"github.com/konoha-labs/insight-gateway/internal/realtime"
)

// Handler holds the dependencies the SSE endpoint needs.
type Handler struct {
	broker    *realtime.Broker
	tokens    auth.TokenCodec
	keepalive time.Duration
}

func NewHandler(broker *realtime.Broker, tokens auth.TokenCodec, keepalive time.Duration) *Handler {
	if keepalive <= 0 {
		keepalive = 15 * time.Second
	}
	return &Handler{broker: broker, tokens: tokens, keepalive: keepalive}
}

// Stream is the GET /v1/realtime/sse handler. Lives long — one
// goroutine per connected client, blocking until the request context
// fires (client disconnect, server shutdown, idle timeout).
func (h *Handler) Stream(w http.ResponseWriter, r *http.Request) {
	// JWT lives in the query string because EventSource (browser +
	// Flutter `flutter_client_sse`) can't set custom headers reliably.
	// We accept the Authorization header too as a fallback for tests
	// + future WebSocket-over-HTTP-Upgrade callers.
	token := r.URL.Query().Get("access_token")
	if token == "" {
		if v := r.Header.Get("Authorization"); len(v) > 7 && v[:7] == "Bearer " {
			token = v[7:]
		}
	}
	if token == "" {
		writeSSEAuthError(w, http.StatusUnauthorized, "missing_access_token")
		return
	}
	if _, err := h.tokens.DecodeAccess(token); err != nil {
		writeSSEAuthError(w, http.StatusUnauthorized, "invalid_access_token")
		return
	}

	filters, err := realtime.ParseFilters(
		r.URL.Query().Get("match_ids"),
		r.URL.Query().Get("event_types"),
	)
	if err != nil {
		writeSSEAuthError(w, http.StatusBadRequest, "invalid_filter")
		return
	}

	flusher, ok := w.(http.Flusher)
	if !ok {
		// Should be impossible with net/http's default server — but bail
		// cleanly rather than silently buffering forever.
		http.Error(w, "streaming_unsupported", http.StatusInternalServerError)
		return
	}

	// Open the stream. Headers MUST be set before the first write.
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no") // tell nginx not to buffer
	w.WriteHeader(http.StatusOK)
	flusher.Flush()

	sub := h.broker.Subscribe(filters)
	defer sub.Close()

	logger := zerolog.Ctx(r.Context()).With().
		Str("subscription_id", sub.ID).
		Int("filter_match_ids", len(filters.MatchIDs)).
		Int("filter_event_types", len(filters.EventTypes)).
		Logger()
	logger.Info().Msg("sse_open")
	defer logger.Info().Msg("sse_close")

	keepaliveTick := time.NewTicker(h.keepalive)
	defer keepaliveTick.Stop()

	ctx := r.Context()
	for {
		select {
		case <-ctx.Done():
			return

		case ev, ok := <-sub.Events:
			if !ok {
				// Subscription was force-closed by the broker (shutdown).
				return
			}
			if err := writeSSEEvent(w, ev); err != nil {
				logger.Warn().Err(err).Msg("sse_write_failed")
				return
			}
			flusher.Flush()

		case <-keepaliveTick.C:
			if _, err := fmt.Fprintf(w, ": keepalive\n\n"); err != nil {
				return
			}
			flusher.Flush()
		}
	}
}

// writeSSEEvent serializes the envelope using the wire format
// the legacy BFF produced (orjson-equivalent), so existing Flutter parsers
// don't have to branch on runtime.
func writeSSEEvent(w http.ResponseWriter, ev *realtime.Event) error {
	// Compose the JSON payload by hand to avoid a per-event allocation
	// for the wrapper map.
	envelope := struct {
		EventID    string          `json:"event_id"`
		MatchID    string          `json:"match_id,omitempty"`
		EventType  string          `json:"event_type"`
		RegionCode string          `json:"region_code,omitempty"`
		TsIngest   string          `json:"ts_ingest,omitempty"`
		Payload    json.RawMessage `json:"payload,omitempty"`
		Stream     string          `json:"stream,omitempty"`
	}{
		EventID:    ev.EventID,
		MatchID:    ev.MatchID,
		EventType:  ev.EventType,
		RegionCode: ev.RegionCode,
		TsIngest:   ev.TsIngest,
		Payload:    ev.Payload,
		Stream:     ev.Stream,
	}
	body, err := json.Marshal(envelope)
	if err != nil {
		return err
	}
	if _, err := fmt.Fprintf(w, "id: %s\nevent: %s\ndata: %s\n\n",
		ev.EventID, ev.EventType, body); err != nil {
		return err
	}
	return nil
}

// writeSSEAuthError writes an error response BEFORE the SSE stream
// opens. After the stream opens we can't change the status — the
// browser already moved into EventSource mode. So all validation
// runs first.
func writeSSEAuthError(w http.ResponseWriter, status int, detail string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = fmt.Fprintf(w, `{"detail":%q}`, detail)
}
