package ops

import (
	"context"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
)

func TestEmitter_DisabledWhenUnconfigured(t *testing.T) {
	e := &Emitter{client: &http.Client{}} // no baseURL/token
	if e.Enabled() {
		t.Fatal("emitter should be disabled without url+token")
	}
	// must be a no-op (no panic, no request) — just ensure it returns
	e.EmitEvent(context.Background(), "sporthub.stream.lag", "WARNING", "noop", nil)
}

func TestEmitter_PostsWhenConfigured(t *testing.T) {
	var hits int32
	var gotToken string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&hits, 1)
		gotToken = r.Header.Get("X-Ops-Token")
		w.WriteHeader(http.StatusAccepted)
	}))
	defer srv.Close()

	e := &Emitter{baseURL: srv.URL, token: "secret", service: "sport-hub", client: srv.Client()}
	if !e.Enabled() {
		t.Fatal("emitter should be enabled")
	}
	e.EmitEvent(context.Background(), "sporthub.provider.degraded", "ERROR", "api down", map[string]any{"provider": "api-football"})
	e.OpenTicket(context.Background(), "ingestion_failure", "ERROR", "no events", "check provider", "sport-hub::ingestion_failure")
	if atomic.LoadInt32(&hits) != 2 {
		t.Fatalf("want 2 posts, got %d", hits)
	}
	if gotToken != "secret" {
		t.Fatalf("token header missing/wrong: %q", gotToken)
	}
}
