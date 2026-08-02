// SSE foundation tests — Sprint 2.5 Parts 15 + 16.
package events

import (
	"context"
	"errors"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
)

type fakeDecoder struct{ fail bool }

func (f fakeDecoder) DecodeAccess(string) (uuid.UUID, error) {
	if f.fail {
		return uuid.Nil, errors.New("bad token")
	}
	return uuid.New(), nil
}

func TestStreamRequiresAuth(t *testing.T) {
	h := NewHandler(fakeDecoder{}, time.Second)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/events/stream", nil)
	h.Stream(rec, req)
	if rec.Code != 401 {
		t.Fatalf("missing token must 401, got %d", rec.Code)
	}

	rec = httptest.NewRecorder()
	req = httptest.NewRequest("GET", "/v1/events/stream?access_token=x", nil)
	NewHandler(fakeDecoder{fail: true}, time.Second).Stream(rec, req)
	if rec.Code != 401 {
		t.Fatalf("invalid token must 401, got %d", rec.Code)
	}
}

func TestStreamHelloHeartbeatAndGracefulClose(t *testing.T) {
	h := NewHandler(fakeDecoder{}, 30*time.Millisecond)

	ctx, cancel := context.WithCancel(context.Background())
	req := httptest.NewRequest("GET", "/v1/events/stream?access_token=ok", nil).
		WithContext(ctx)
	rec := httptest.NewRecorder()

	done := make(chan struct{})
	go func() {
		h.Stream(rec, req) // returns on ctx cancel = graceful disconnect
		close(done)
	}()

	// Allow hello + at least two heartbeats.
	time.Sleep(110 * time.Millisecond)
	cancel()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("stream must return promptly on client disconnect")
	}

	body := rec.Body.String()
	if !strings.Contains(body, "event: hello") {
		t.Fatalf("hello event missing: %q", body)
	}
	if !strings.Contains(body, "heartbeat_seconds") {
		t.Fatal("hello must advertise the heartbeat cadence")
	}
	if !strings.Contains(body, ": hb 1") || !strings.Contains(body, ": hb 2") {
		t.Fatalf("expected ≥2 heartbeats, got: %q", body)
	}
	if rec.Header().Get("Content-Type") != "text/event-stream" {
		t.Fatal("must be an SSE response")
	}
	// Foundation only: NO business events.
	if strings.Contains(body, "event: feed") || strings.Contains(body, "event: post") {
		t.Fatal("no business events may ride the stream yet")
	}
}
