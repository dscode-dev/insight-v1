// /v1/events/stream — Sprint 2.5 Part 15: the SSE FOUNDATION.
//
// Deliberately carries NO business events yet. It establishes the
// authenticated long-lived channel + heartbeat + graceful-disconnect
// contract that feed updates, notifications and live match signals
// will ride later: producers will publish named SSE events onto this
// stream without the endpoint (or the mobile client's connection
// code) changing.
//
// Wire behaviour:
//   - auth: access_token query param (EventSource can't set headers)
//     or Authorization: Bearer fallback — same posture as the
//     existing /v1/realtime/sse handler.
//   - on connect: `event: hello` with the negotiated heartbeat.
//   - every interval: `: hb <n>` comment heartbeat (comments are
//     ignored by EventSource but keep proxies + NATs from idling out).
//   - on server shutdown or client disconnect: clean return.
package events

import (
	"fmt"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog"
)

// TokenDecoder is the slice of the JWT codec the stream needs —
// matches auth.TokenCodec's DecodeAccess so the domain codec
// satisfies it directly.
type TokenDecoder interface {
	DecodeAccess(token string) (uuid.UUID, error)
}

type Handler struct {
	decoder   TokenDecoder
	heartbeat time.Duration
}

func NewHandler(decoder TokenDecoder, heartbeat time.Duration) *Handler {
	if heartbeat <= 0 {
		heartbeat = 15 * time.Second
	}
	return &Handler{decoder: decoder, heartbeat: heartbeat}
}

func (h *Handler) Stream(w http.ResponseWriter, r *http.Request) {
	logger := zerolog.Ctx(r.Context())

	token := r.URL.Query().Get("access_token")
	if token == "" {
		if v := r.Header.Get("Authorization"); len(v) > 7 && v[:7] == "Bearer " {
			token = v[7:]
		}
	}
	if token == "" {
		writeAuthError(w, "missing_access_token")
		return
	}
	uid, err := h.decoder.DecodeAccess(token)
	if err != nil {
		writeAuthError(w, "invalid_access_token")
		return
	}
	userID := uid.String()

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)

	// Hello event: confirms the channel + advertises cadence so the
	// client can detect a dead connection (2 missed beats = reconnect).
	fmt.Fprintf(w, "event: hello\ndata: {\"heartbeat_seconds\": %d}\n\n",
		int(h.heartbeat.Seconds()))
	flusher.Flush()

	logger.Info().Str("user_id", userID).Msg("events_stream_open")
	ticker := time.NewTicker(h.heartbeat)
	defer ticker.Stop()

	beat := 0
	for {
		select {
		case <-r.Context().Done():
			// Client went away or server is draining — graceful close.
			logger.Info().Str("user_id", userID).Msg("events_stream_closed")
			return
		case <-ticker.C:
			beat++
			if _, err := fmt.Fprintf(w, ": hb %d\n\n", beat); err != nil {
				return
			}
			flusher.Flush()
		}
	}
}

func writeAuthError(w http.ResponseWriter, code string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusUnauthorized)
	fmt.Fprintf(w, `{"error":%q}`, code)
}
