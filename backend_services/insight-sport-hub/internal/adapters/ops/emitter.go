// Package ops emits operations events/tickets to the Robozão Gateway operations
// API (ML-C.5e). Fire-and-forget + fail-safe: emission never blocks or fails the
// realtime ingestion path. Config from env:
//
//	OPERATIONS_GATEWAY_URL  e.g. http://robozao-gateway:8095  (empty → disabled)
//	OPS_INGEST_TOKEN        shared service token             (empty → disabled)
//	INSIGHT_SERVICE         service name (default "sport-hub")
package ops

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"os"
	"time"
)

type Emitter struct {
	baseURL string
	token   string
	service string
	client  *http.Client
}

func New() *Emitter {
	svc := os.Getenv("INSIGHT_SERVICE")
	if svc == "" {
		svc = "sport-hub"
	}
	return &Emitter{
		baseURL: trimRight(os.Getenv("OPERATIONS_GATEWAY_URL")),
		token:   os.Getenv("OPS_INGEST_TOKEN"),
		service: svc,
		client:  &http.Client{Timeout: 3 * time.Second},
	}
}

func (e *Emitter) Enabled() bool { return e.baseURL != "" && e.token != "" }

// EmitEvent pushes one ops event. Severity: INFO|WARNING|ERROR|CRITICAL.
func (e *Emitter) EmitEvent(ctx context.Context, eventType, severity, message string, metadata map[string]any) {
	e.post(ctx, "/operations/events", map[string]any{
		"event_type": eventType, "service": e.service, "severity": severity,
		"message": message, "metadata": metadata,
	})
}

// OpenTicket pushes one ops ticket (meaningful failure only).
func (e *Emitter) OpenTicket(ctx context.Context, reason, severity, impact, recommendation, dedupKey string) {
	e.post(ctx, "/operations/tickets", map[string]any{
		"service": e.service, "severity": severity, "reason": reason,
		"impact": impact, "recommendation": recommendation, "dedup_key": dedupKey,
	})
}

func (e *Emitter) post(ctx context.Context, path string, body map[string]any) {
	if !e.Enabled() {
		return
	}
	// Never let observability break the work.
	defer func() { _ = recover() }()
	data, err := json.Marshal(body)
	if err != nil {
		return
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, e.baseURL+path, bytes.NewReader(data))
	if err != nil {
		return
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Ops-Token", e.token)
	resp, err := e.client.Do(req)
	if err != nil {
		return
	}
	_ = resp.Body.Close()
}

func trimRight(s string) string {
	for len(s) > 0 && s[len(s)-1] == '/' {
		s = s[:len(s)-1]
	}
	return s
}
