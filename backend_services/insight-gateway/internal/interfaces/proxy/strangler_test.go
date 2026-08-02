package proxy

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestStrangler_FallbackProxiesEverything(t *testing.T) {
	// Stand up a fake legacy upstream that echoes the path it received.
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, "from-upstream:"+r.URL.Path)
	}))
	defer upstream.Close()

	s, err := New(upstream.URL)
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/v1/feed", nil)
	s.ServeHTTP(rec, req)

	body := rec.Body.String()
	if !strings.Contains(body, "from-upstream:/v1/feed") {
		t.Fatalf("expected proxy fallback to upstream, got %q", body)
	}
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
}

func TestStrangler_NativeHandlerWins(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, "from-upstream")
	}))
	defer upstream.Close()

	s, err := New(upstream.URL)
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	// Register a native handler that should preempt the proxy.
	s.Native(http.MethodGet, "/healthz", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, "native-ok")
	}))

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	s.ServeHTTP(rec, req)

	if rec.Body.String() != "native-ok" {
		t.Fatalf("expected native handler, got %q", rec.Body.String())
	}
}

func TestStrangler_PreservesXForwardedHeaders(t *testing.T) {
	var sawHost, sawProto string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sawHost = r.Header.Get("X-Forwarded-Host")
		sawProto = r.Header.Get("X-Forwarded-Proto")
	}))
	defer upstream.Close()

	s, err := New(upstream.URL)
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/v1/feed", nil)
	req.Host = "insight.konohalabs.com"
	s.ServeHTTP(rec, req)

	if sawHost != "insight.konohalabs.com" {
		t.Fatalf("expected X-Forwarded-Host preserved, got %q", sawHost)
	}
	if sawProto == "" {
		t.Fatalf("expected X-Forwarded-Proto set")
	}
}
