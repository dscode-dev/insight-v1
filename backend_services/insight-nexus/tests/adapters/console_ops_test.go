package adapters_test

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-nexus/internal/adapters/httpapi"
	"github.com/konoha-labs/insight-nexus/internal/adapters/inmemory"
	"github.com/konoha-labs/insight-nexus/internal/application/antispam"
	"github.com/konoha-labs/insight-nexus/internal/application/draftvalidator"
	"github.com/konoha-labs/insight-nexus/internal/application/llmrouter"
	"github.com/konoha-labs/insight-nexus/internal/application/publisher"
	"github.com/konoha-labs/insight-nexus/internal/domain/publication"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

// ---- nop metrics ------------------------------------------------------------------

type nopMetrics struct{}

func (nopMetrics) DraftComposed(string)                        {}
func (nopMetrics) Published(string)                            {}
func (nopMetrics) PublicationFailed(string, string)            {}
func (nopMetrics) TicketCreated(string)                        {}
func (nopMetrics) PostPublishBookkeepingFailed(string, string) {}
func (nopMetrics) SpamPrevented(string)                        {}
func (nopMetrics) ProviderHealth(string, llmrouter.Status)     {}
func (nopMetrics) LLMLatency(string, float64)                  {}
func (nopMetrics) Fallback(string, string)                     {}

// ---- fakes ------------------------------------------------------------------------

type fakeSocial struct {
	posts []ports.AgentPostRequest
}

func (f *fakeSocial) PublishAgentPost(_ context.Context, req ports.AgentPostRequest) (string, error) {
	f.posts = append(f.posts, req)
	return "post-1", nil
}

// ---- harness ----------------------------------------------------------------------

type opsHarness struct {
	mux        *http.ServeMux
	handler    http.Handler // mux wrapped in RequireAuth
	token      string       // bearer for the next requests ("" = none)
	tickets    *inmemory.TicketRepo
	candidates *inmemory.CandidateRepo
	audit      *inmemory.AuditRepo
	personas   *inmemory.PersonaRepo
	social     *fakeSocial
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(req *http.Request) (*http.Response, error) {
	return f(req)
}

// as switches the opaque Gateway session used by the next request.
func (h *opsHarness) as(t *testing.T, sub, role string) {
	t.Helper()
	h.token = role + ":" + sub
}

func newOpsHarness(t *testing.T) *opsHarness {
	t.Helper()
	h := &opsHarness{
		mux:        http.NewServeMux(),
		tickets:    inmemory.NewTicketRepo(),
		candidates: inmemory.NewCandidateRepo(),
		audit:      inmemory.NewAuditRepo(),
		personas:   inmemory.NewPersonaRepo(),
		social:     &fakeSocial{},
	}
	identityClient := &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		token := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
		if token == "" || token == "invalid" || token == "expired" {
			return &http.Response{
				StatusCode: http.StatusUnauthorized,
				Body:       io.NopCloser(strings.NewReader(`{"detail":"unauthorized"}`)),
				Header:     make(http.Header),
			}, nil
		}
		role, subject, ok := strings.Cut(token, ":")
		if !ok {
			return &http.Response{
				StatusCode: http.StatusUnauthorized,
				Body:       io.NopCloser(strings.NewReader(`{"detail":"unauthorized"}`)),
				Header:     make(http.Header),
			}, nil
		}
		permissions := []string{"console.access"}
		if role != "viewer" {
			permissions = append(permissions, "config.write", "dlq.replay")
		}
		body, err := json.Marshal(map[string]any{
			"operator": map[string]any{
				"id": "operator-1", "email": subject, "role": role,
				"permissions": permissions,
			},
		})
		if err != nil {
			return nil, err
		}
		return &http.Response{
			StatusCode: http.StatusOK,
			Body:       io.NopCloser(bytes.NewReader(body)),
			Header:     make(http.Header),
		}, nil
	})}
	mgr := llmrouter.NewHealthManager(nil, time.Minute, nopMetrics{}, zerolog.Nop())
	router := llmrouter.NewRouter(nil, mgr, nopMetrics{}, zerolog.Nop())
	engine := publisher.New(
		h.personas, router, draftvalidator.New(),
		antispam.New(antispam.DefaultPolicy(), inmemory.NewSpamLog(), nopMetrics{}, nil),
		h.candidates, h.tickets, h.social, inmemory.NewMemoryRepo(),
		nopMetrics{}, zerolog.Nop(), nil,
	)
	httpapi.RegisterConsoleOps(h.mux, httpapi.ConsoleOpsDeps{
		Tickets:   h.tickets,
		Personas:  h.personas,
		Audit:     h.audit,
		Publisher: engine,
		Logger:    zerolog.Nop(),
	})
	h.handler = httpapi.RequireAuth(httpapi.AuthConfig{
		IdentityURL: "https://gateway.test/v1/operator/auth/me",
		Client:      identityClient,
	}, h.mux)
	h.as(t, "admin@konohalabs", "admin")
	return h
}

func (h *opsHarness) do(t *testing.T, method, path string, body any) *httptest.ResponseRecorder {
	t.Helper()
	var buf bytes.Buffer
	if body != nil {
		if err := json.NewEncoder(&buf).Encode(body); err != nil {
			t.Fatal(err)
		}
	}
	req := httptest.NewRequest(method, path, &buf)
	if h.token != "" {
		req.Header.Set("Authorization", "Bearer "+h.token)
	}
	rec := httptest.NewRecorder()
	h.handler.ServeHTTP(rec, req)
	return rec
}

func (h *opsHarness) seedTicket(t *testing.T, status publication.TicketStatus) publication.Ticket {
	t.Helper()
	tk := publication.Ticket{
		ID:               uuid.New(),
		AgentName:        "ninja",
		TrendIDs:         []string{"trend-1"},
		ClusterID:        uuid.New(),
		SuggestedTitle:   "Consenso de mercado crescendo",
		SuggestedSummary: "Consenso subiu de 50% para 85% em três janelas de observação.",
		Evidence:         []string{"consenso 85%", "5 casas"},
		MatchID:          "match-1",
		Status:           status,
		CreatedAt:        time.Now().UTC(),
	}
	if err := h.tickets.Save(context.Background(), tk); err != nil {
		t.Fatal(err)
	}
	return tk
}

func (h *opsHarness) auditEvents(t *testing.T) []publication.AuditEvent {
	t.Helper()
	events, err := h.audit.List(context.Background(), ports.AuditFilter{})
	if err != nil {
		t.Fatal(err)
	}
	return events
}

// ---- ticket review ----------------------------------------------------------------

func TestTicketTransitionValid(t *testing.T) {
	h := newOpsHarness(t)
	tk := h.seedTicket(t, publication.TicketOpen)

	rec := h.do(t, http.MethodPatch, "/v1/publications/tickets/"+tk.ID.String(), map[string]any{
		"status": "UNDER_REVIEW", "reason": "triaging",
	})
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d body=%s", rec.Code, rec.Body.String())
	}
	got, err := h.tickets.Get(context.Background(), tk.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.Status != publication.TicketUnderReview {
		t.Fatalf("status = %s", got.Status)
	}
	if got.ReviewedBy != "admin@konohalabs" || got.ReviewedAt == nil {
		t.Fatalf("review attribution missing: %+v", got)
	}
	events := h.auditEvents(t)
	if len(events) != 1 {
		t.Fatalf("audit events = %d", len(events))
	}
	if events[0].Action != "ticket.transition_UNDER_REVIEW" || events[0].Actor != "admin@konohalabs" {
		t.Fatalf("audit = %+v", events[0])
	}
	if events[0].Before["status"] != "OPEN" || events[0].After["status"] != "UNDER_REVIEW" {
		t.Fatalf("before/after = %v / %v", events[0].Before, events[0].After)
	}
}

func TestTicketTransitionInvalidRejected(t *testing.T) {
	h := newOpsHarness(t)
	tk := h.seedTicket(t, publication.TicketOpen)

	// OPEN → PUBLISHED skips review: must be rejected, nothing audited.
	rec := h.do(t, http.MethodPatch, "/v1/publications/tickets/"+tk.ID.String(), map[string]any{
		"status": "PUBLISHED",
	})
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d", rec.Code)
	}
	got, _ := h.tickets.Get(context.Background(), tk.ID)
	if got.Status != publication.TicketOpen {
		t.Fatalf("ticket mutated on invalid transition: %s", got.Status)
	}
	if len(h.auditEvents(t)) != 0 {
		t.Fatal("invalid transition must not audit")
	}
}

func TestTicketActorRequired(t *testing.T) {
	h := newOpsHarness(t)
	tk := h.seedTicket(t, publication.TicketOpen)

	// V1.1: the actor comes from the verified token — no token, no
	// mutation. A body "actor" field can no longer smuggle identity.
	h.token = ""
	rec := h.do(t, http.MethodPatch, "/v1/publications/tickets/"+tk.ID.String(), map[string]any{
		"status": "UNDER_REVIEW", "actor": "forged@evil",
	})
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("tokenless mutation accepted: %d", rec.Code)
	}
	if len(h.auditEvents(t)) != 0 {
		t.Fatal("unauthenticated request must not audit")
	}
}

func TestTicketEditAudited(t *testing.T) {
	h := newOpsHarness(t)
	tk := h.seedTicket(t, publication.TicketUnderReview)

	h.as(t, "editor@konohalabs", "admin")
	rec := h.do(t, http.MethodPatch, "/v1/publications/tickets/"+tk.ID.String(), map[string]any{
		"reason": "title tightened",
		"edits":  map[string]any{"suggested_title": "Consenso de mercado em alta"},
	})
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d body=%s", rec.Code, rec.Body.String())
	}
	got, _ := h.tickets.Get(context.Background(), tk.ID)
	if got.SuggestedTitle != "Consenso de mercado em alta" {
		t.Fatalf("edit not applied: %q", got.SuggestedTitle)
	}
	events := h.auditEvents(t)
	if len(events) != 1 || events[0].Action != "ticket.edit" {
		t.Fatalf("audit = %+v", events)
	}
	if events[0].Before["suggested_title"] == events[0].After["suggested_title"] {
		t.Fatal("before/after must differ on edit")
	}
}

// ---- ticket publish ----------------------------------------------------------------

func TestTicketPublishApprovedFlow(t *testing.T) {
	h := newOpsHarness(t)
	tk := h.seedTicket(t, publication.TicketApproved)

	rec := h.do(t, http.MethodPost, "/v1/publications/tickets/"+tk.ID.String()+"/publish", map[string]any{
		"reason": "approved by editorial",
	})
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d body=%s", rec.Code, rec.Body.String())
	}
	if len(h.social.posts) != 1 {
		t.Fatalf("social posts = %d", len(h.social.posts))
	}
	got, _ := h.tickets.Get(context.Background(), tk.ID)
	if got.Status != publication.TicketPublished || got.PublishedBy != "admin@konohalabs" || got.PublishedAt == nil {
		t.Fatalf("ticket = %+v", got)
	}
	var body struct {
		Candidate publication.Candidate `json:"candidate"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if body.Candidate.Status != publication.CandidatePublished {
		t.Fatalf("candidate status = %s reason=%s", body.Candidate.Status, body.Candidate.StatusReason)
	}
	if body.Candidate.Provider != "manual" || body.Candidate.Model != "human:admin@konohalabs" {
		t.Fatalf("attribution = %s/%s", body.Candidate.Provider, body.Candidate.Model)
	}
	events := h.auditEvents(t)
	if len(events) != 1 || events[0].Action != "ticket.publish" {
		t.Fatalf("audit = %+v", events)
	}
}

func TestTicketPublishRequiresApproved(t *testing.T) {
	h := newOpsHarness(t)
	tk := h.seedTicket(t, publication.TicketOpen)

	rec := h.do(t, http.MethodPost, "/v1/publications/tickets/"+tk.ID.String()+"/publish", map[string]any{
		"reason": "premature",
	})
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("OPEN ticket published: %d", rec.Code)
	}
	if len(h.social.posts) != 0 {
		t.Fatal("nothing may reach Social without approval")
	}
}

// ---- manual publication -------------------------------------------------------------

func TestManualPublication(t *testing.T) {
	h := newOpsHarness(t)

	h.as(t, "editor@konohalabs", "admin")
	rec := h.do(t, http.MethodPost, "/v1/publications/manual", map[string]any{
		"agent_slug": "pulse",
		"title":      "Ritmo de gols acima da média na rodada",
		"summary":    "A rodada registrou média de 3.2 gols por partida, bem acima do padrão recente da competição.",
		"highlights": []string{"3.2 gols/jogo", "média histórica 2.4"},
		"reason":     "editorial weekend recap",
	})
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d body=%s", rec.Code, rec.Body.String())
	}
	if len(h.social.posts) != 1 {
		t.Fatalf("social posts = %d", len(h.social.posts))
	}
	if h.social.posts[0].Metadata["manual"] != "true" {
		t.Fatal("manual marker missing from social metadata")
	}
	events := h.auditEvents(t)
	if len(events) != 1 || events[0].Action != "publication.manual" || events[0].Actor != "editor@konohalabs" {
		t.Fatalf("audit = %+v", events)
	}
}

func TestManualPublicationForbiddenContentBlocked(t *testing.T) {
	h := newOpsHarness(t)

	rec := h.do(t, http.MethodPost, "/v1/publications/manual", map[string]any{
		"agent_slug": "ninja",
		"title":      "Oportunidade imperdível",
		"summary":    "Aposte agora nessa tendência de consenso do mercado para lucrar.",
		"reason":     "test",
	})
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d body=%s", rec.Code, rec.Body.String())
	}
	var body struct {
		Candidate publication.Candidate `json:"candidate"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if body.Candidate.Status != publication.CandidateInvalid {
		t.Fatalf("forbidden content not blocked: %s", body.Candidate.Status)
	}
	if len(h.social.posts) != 0 {
		t.Fatal("forbidden content reached Social")
	}
}

func TestManualPublicationUnknownAgent(t *testing.T) {
	h := newOpsHarness(t)
	rec := h.do(t, http.MethodPost, "/v1/publications/manual", map[string]any{
		"agent_slug": "nope", "title": "x", "summary": "y", "reason": "r",
	})
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("unknown agent accepted: %d body=%s", rec.Code, rec.Body.String())
	}
}

// ---- personas -----------------------------------------------------------------------

func TestPersonaUpdateAudited(t *testing.T) {
	h := newOpsHarness(t)

	current, err := h.personas.Get(context.Background(), "ninja")
	if err != nil {
		t.Fatal(err)
	}
	current.Tone = "mais direto, menos jargão"
	payload := map[string]any{
		"slug": "ninja", "social_author_id": current.SocialAuthorID,
		"style": current.Style, "tone": current.Tone,
		"expertise": current.Expertise, "restrictions": current.Restrictions,
		"posting_behavior": current.PostingBehavior,
		"reason":           "voice tuning",
	}
	h.as(t, "super@konohalabs", "super_admin")
	rec := h.do(t, http.MethodPut, "/v1/personas/ninja", payload)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d body=%s", rec.Code, rec.Body.String())
	}
	got, _ := h.personas.Get(context.Background(), "ninja")
	if got.Tone != "mais direto, menos jargão" {
		t.Fatalf("tone = %q", got.Tone)
	}
	events := h.auditEvents(t)
	if len(events) != 1 || events[0].Action != "persona.update" {
		t.Fatalf("audit = %+v", events)
	}
	if events[0].Before == nil {
		t.Fatal("persona update must snapshot previous state")
	}
}

func TestPersonaListServed(t *testing.T) {
	h := newOpsHarness(t)
	rec := h.do(t, http.MethodGet, "/v1/personas", nil)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d", rec.Code)
	}
	var body struct {
		Personas []json.RawMessage `json:"personas"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if len(body.Personas) != 5 {
		t.Fatalf("personas = %d", len(body.Personas))
	}
}

// ---- audit api ----------------------------------------------------------------------

func TestAuditEventsRecordAndFilter(t *testing.T) {
	h := newOpsHarness(t)

	// Actor is ALWAYS the token subject — even when the body claims
	// otherwise (the forged value below must be overwritten).
	type ev struct {
		sub  string
		body map[string]any
	}
	for _, e := range []ev{
		{"a@k", map[string]any{"action": "console.login", "entity_type": "session", "entity_id": "s1", "actor": "forged@evil"}},
		{"b@k", map[string]any{"action": "console.login", "entity_type": "session", "entity_id": "s2"}},
		{"a@k", map[string]any{"action": "agent.disable", "entity_type": "agent", "entity_id": "ninja"}},
	} {
		h.as(t, e.sub, "admin")
		if rec := h.do(t, http.MethodPost, "/v1/audit/events", e.body); rec.Code != http.StatusOK {
			t.Fatalf("record = %d body=%s", rec.Code, rec.Body.String())
		}
	}

	rec := h.do(t, http.MethodGet, "/v1/audit/events?actor=a@k", nil)
	var body struct {
		Events []publication.AuditEvent `json:"events"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if len(body.Events) != 2 {
		t.Fatalf("filtered events = %d", len(body.Events))
	}

	rec = h.do(t, http.MethodGet, "/v1/audit/events?action=agent.disable", nil)
	body.Events = nil
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if len(body.Events) != 1 || body.Events[0].EntityID != "ninja" {
		t.Fatalf("action filter = %+v", body.Events)
	}
}

func TestAuditEventRequiresAction(t *testing.T) {
	h := newOpsHarness(t)
	rec := h.do(t, http.MethodPost, "/v1/audit/events", map[string]any{"entity_type": "x"})
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("action-less audit accepted: %d", rec.Code)
	}
}

// ---- V1.1 admin auth ---------------------------------------------------------------

func TestViewerCanReadButNotMutate(t *testing.T) {
	h := newOpsHarness(t)
	tk := h.seedTicket(t, publication.TicketOpen)
	h.as(t, "viewer@konohalabs", "viewer")

	if rec := h.do(t, http.MethodGet, "/v1/personas", nil); rec.Code != http.StatusOK {
		t.Fatalf("viewer read = %d", rec.Code)
	}
	rec := h.do(t, http.MethodPatch, "/v1/publications/tickets/"+tk.ID.String(),
		map[string]any{"status": "UNDER_REVIEW"})
	if rec.Code != http.StatusForbidden {
		t.Fatalf("viewer mutation = %d (want 403)", rec.Code)
	}
}

func TestInvalidGatewaySessionRejected(t *testing.T) {
	h := newOpsHarness(t)
	h.token = "invalid"
	if rec := h.do(t, http.MethodGet, "/v1/personas", nil); rec.Code != http.StatusUnauthorized {
		t.Fatalf("invalid Gateway session accepted: %d", rec.Code)
	}
}

func TestExpiredGatewaySessionRejected(t *testing.T) {
	h := newOpsHarness(t)
	h.token = "expired"
	if rec := h.do(t, http.MethodGet, "/v1/personas", nil); rec.Code != http.StatusUnauthorized {
		t.Fatalf("expired Gateway session accepted: %d", rec.Code)
	}
}

func TestNoGatewayIdentityEndpointLocksAdminAPI(t *testing.T) {
	h := newOpsHarness(t)
	locked := httpapi.RequireAuth(httpapi.AuthConfig{}, h.mux)
	req := httptest.NewRequest(http.MethodGet, "/v1/personas", nil)
	req.Header.Set("Authorization", "Bearer "+h.token)
	rec := httptest.NewRecorder()
	locked.ServeHTTP(rec, req)
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("unconfigured Gateway endpoint must lock, got %d", rec.Code)
	}
}
