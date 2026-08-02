// Sprint 4 — publication engine proofs: router failover, provider
// health, anti-spam budgets, ticket fallback, validation, memory
// expansion and the full draft → Social-post workflow.
package application_test

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-nexus/internal/adapters/inmemory"
	"github.com/konoha-labs/insight-nexus/internal/application/antispam"
	"github.com/konoha-labs/insight-nexus/internal/application/contextbuilder"
	"github.com/konoha-labs/insight-nexus/internal/application/draftvalidator"
	"github.com/konoha-labs/insight-nexus/internal/application/llmrouter"
	"github.com/konoha-labs/insight-nexus/internal/application/promptbuilder"
	"github.com/konoha-labs/insight-nexus/internal/application/publisher"
	"github.com/konoha-labs/insight-nexus/internal/domain/agent"
	"github.com/konoha-labs/insight-nexus/internal/domain/decision"
	"github.com/konoha-labs/insight-nexus/internal/domain/draft"
	"github.com/konoha-labs/insight-nexus/internal/domain/memory"
	"github.com/konoha-labs/insight-nexus/internal/domain/persona"
	"github.com/konoha-labs/insight-nexus/internal/domain/publication"
	"github.com/konoha-labs/insight-nexus/internal/ports"
	portllm "github.com/konoha-labs/insight-nexus/internal/ports/llm"
)

// ---- fakes -------------------------------------------------------------------

const goodJSON = `{"title":"Mercado firmando no mandante","summary":"O consenso entre casas segue subindo há três janelas seguidas.","highlights":["consenso +8pp"],"tags":["mercado"],"chart_hints":["implied_probability"]}`

type fakeProvider struct {
	name      string
	healthErr error
	genErr    error
	text      string
	calls     int32
}

func (f *fakeProvider) Name() string { return f.name }

func (f *fakeProvider) Capabilities() portllm.ProviderCapability {
	return portllm.ProviderCapability{Reasoning: true, StructuredOutput: true}
}

func (f *fakeProvider) Health(context.Context) error { return f.healthErr }

func (f *fakeProvider) Generate(context.Context, portllm.GenerateRequest) (*portllm.GenerateResponse, error) {
	atomic.AddInt32(&f.calls, 1)
	if f.genErr != nil {
		return nil, f.genErr
	}
	text := f.text
	if text == "" {
		text = goodJSON
	}
	return &portllm.GenerateResponse{Text: text, Model: f.name + "-model"}, nil
}

type fakeSocial struct {
	posts  []ports.AgentPostRequest
	err    error
	postID string
}

func (f *fakeSocial) PublishAgentPost(_ context.Context, req ports.AgentPostRequest) (string, error) {
	if f.err != nil {
		return "", f.err
	}
	f.posts = append(f.posts, req)
	if f.postID == "" {
		f.postID = "post-1"
	}
	return f.postID, nil
}

type nopPubMetrics struct{}

func (nopPubMetrics) DraftComposed(string)                    {}
func (nopPubMetrics) Published(string)                        {}
func (nopPubMetrics) PublicationFailed(string, string)        {}
func (nopPubMetrics) TicketCreated(string)                    {}
func (nopPubMetrics) SpamPrevented(string)                    {}
func (nopPubMetrics) ProviderHealth(string, llmrouter.Status) {}
func (nopPubMetrics) LLMLatency(string, float64)              {}
func (nopPubMetrics) Fallback(string, string)                 {}

func healthyManager(t *testing.T, providers ...portllm.Provider) *llmrouter.HealthManager {
	t.Helper()
	h := llmrouter.NewHealthManager(providers, time.Minute, nopPubMetrics{}, zerolog.Nop())
	// Two passes → providers with passing Health become healthy.
	h.CheckAll(context.Background())
	h.CheckAll(context.Background())
	return h
}

// ---- harness ---------------------------------------------------------------------

type harness struct {
	engine     *publisher.Engine
	candidates *inmemory.CandidateRepo
	tickets    *inmemory.TicketRepo
	memories   *inmemory.MemoryRepo
	social     *fakeSocial
	spamLog    *inmemory.SpamLog
	agentID    uuid.UUID
	clusterID  uuid.UUID
}

func newHarness(t *testing.T, providers []portllm.Provider, policy antispam.Policy) *harness {
	t.Helper()
	h := &harness{
		candidates: inmemory.NewCandidateRepo(),
		tickets:    inmemory.NewTicketRepo(),
		memories:   inmemory.NewMemoryRepo(),
		social:     &fakeSocial{},
		spamLog:    inmemory.NewSpamLog(),
		agentID:    uuid.New(),
		clusterID:  uuid.New(),
	}
	mgr := healthyManager(t, providers...)
	router := llmrouter.NewRouter(providers, mgr, nopPubMetrics{}, zerolog.Nop())
	spam := antispam.New(policy, h.spamLog, nopPubMetrics{}, nil)
	h.engine = publisher.New(
		inmemory.NewPersonaRepo(), router, draftvalidator.New(), spam,
		h.candidates, h.tickets, h.social, h.memories,
		nopPubMetrics{}, zerolog.Nop(), nil,
	)
	return h
}

func (h *harness) input() publisher.Input {
	return publisher.Input{
		Draft: draft.Draft{
			ID: uuid.New(), AgentID: h.agentID,
			TrendID: "trend-1", MatchID: "match-1",
			Title:      "Consenso de mercado crescendo",
			Summary:    "Consenso subiu de 50% para 85% em três janelas.",
			Highlights: []string{"consenso 85%", "5 casas"},
			Status:     draft.StatusQueued, CreatedAt: time.Now(),
		},
		Context: contextbuilder.DraftContext{
			Agent:       agent.Agent{ID: h.agentID, Name: "ninja"},
			ClusterID:   h.clusterID,
			ClusterType: "market_move",
			Action:      "DRAFT",
			Priority:    "HIGH",
			DraftType:   "INITIAL",
			Sequence:    1,
		},
		Decision: decision.PublicationDecision{
			ID:        uuid.New(),
			Reasoning: []string{"publish_score 0.82 above tier threshold"},
		},
	}
}

// ---- router + failover (Parts 4 + 5) -----------------------------------------------

func TestRouterPrefersFirstPrivateProviderAndRecordsNoFallback(t *testing.T) {
	claude := &fakeProvider{name: "claude"}
	gemini := &fakeProvider{name: "gemini"}
	mgr := healthyManager(t, claude, gemini)
	router := llmrouter.NewRouter([]portllm.Provider{claude, gemini}, mgr,
		nopPubMetrics{}, zerolog.Nop())

	_, route, err := router.Generate(context.Background(),
		portllm.GenerateRequest{}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if route.Provider != "claude" {
		t.Fatalf("provider priority violated: routed to %s", route.Provider)
	}
	if route.FallbackUsed {
		t.Fatal("no fallback should be recorded for a first-provider hit")
	}
	if gemini.calls != 0 {
		t.Fatal("fallback provider must not be touched while primary is healthy")
	}
}

func TestRouterOperatesWithAnySingleProvider(t *testing.T) {
	for _, name := range []string{"claude", "gpt", "gemini"} {
		t.Run(name, func(t *testing.T) {
			provider := &fakeProvider{name: name}
			mgr := healthyManager(t, provider)
			router := llmrouter.NewRouter(
				[]portllm.Provider{provider}, mgr, nopPubMetrics{}, zerolog.Nop())

			_, route, err := router.Generate(
				context.Background(), portllm.GenerateRequest{}, nil)
			if err != nil {
				t.Fatal(err)
			}
			if route.Provider != name {
				t.Fatalf("routed to %q, want %q", route.Provider, name)
			}
			if route.FallbackUsed {
				t.Fatal("single-provider routing must not report fallback")
			}
		})
	}
}

func TestRouterFailsOverAndRecordsChain(t *testing.T) {
	claude := &fakeProvider{name: "claude", genErr: errors.New("oom")}
	gpt := &fakeProvider{name: "gpt", genErr: errors.New("oom")}
	gemini := &fakeProvider{name: "gemini"}
	mgr := healthyManager(t, claude, gpt, gemini)
	router := llmrouter.NewRouter(
		[]portllm.Provider{claude, gpt, gemini}, mgr, nopPubMetrics{}, zerolog.Nop())

	_, route, err := router.Generate(context.Background(),
		portllm.GenerateRequest{}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if route.Provider != "gemini" || !route.FallbackUsed {
		t.Fatalf("expected gemini via fallback, got %+v", route)
	}
	want := []string{"claude:failed", "gpt:failed", "gemini:ok"}
	if fmt.Sprint(route.Chain) != fmt.Sprint(want) {
		t.Fatalf("fallback chain %v, want %v", route.Chain, want)
	}
}

func TestRouterSkipsOfflineProviders(t *testing.T) {
	claude := &fakeProvider{name: "claude", healthErr: errors.New("daemon down")}
	gpt := &fakeProvider{name: "gpt"}
	mgr := healthyManager(t, claude, gpt)
	router := llmrouter.NewRouter([]portllm.Provider{claude, gpt}, mgr,
		nopPubMetrics{}, zerolog.Nop())

	_, route, err := router.Generate(context.Background(),
		portllm.GenerateRequest{}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if route.Provider != "gpt" {
		t.Fatalf("offline provider not skipped: %+v", route)
	}
	if claude.calls != 0 {
		t.Fatal("offline provider must never be invoked")
	}
	if route.Chain[0] != "claude:offline" {
		t.Fatalf("chain must record the skip: %v", route.Chain)
	}
}

func TestRouterMalformedOutputFailsOver(t *testing.T) {
	claude := &fakeProvider{name: "claude", text: "not json at all"}
	gpt := &fakeProvider{name: "gpt"}
	mgr := healthyManager(t, claude, gpt)
	router := llmrouter.NewRouter([]portllm.Provider{claude, gpt}, mgr,
		nopPubMetrics{}, zerolog.Nop())

	_, route, err := router.Generate(context.Background(),
		portllm.GenerateRequest{}, func(text string) error {
			_, perr := publication.ParseComposedPost(text)
			return perr
		})
	if err != nil {
		t.Fatal(err)
	}
	if route.Provider != "gpt" {
		t.Fatalf("malformed output must count as provider failure: %+v", route)
	}
}

// ---- health (Part 4) ----------------------------------------------------------------

func TestHealthTransitions(t *testing.T) {
	p := &fakeProvider{name: "claude"}
	mgr := llmrouter.NewHealthManager([]portllm.Provider{p}, time.Minute,
		nopPubMetrics{}, zerolog.Nop())

	if got := mgr.StatusOf("claude"); got != llmrouter.StatusOffline {
		t.Fatalf("unchecked provider must be offline, got %s", got)
	}
	mgr.CheckAll(context.Background())
	if got := mgr.StatusOf("claude"); got != llmrouter.StatusDegraded {
		t.Fatalf("first pass must be degraded (recovering), got %s", got)
	}
	mgr.CheckAll(context.Background())
	if got := mgr.StatusOf("claude"); got != llmrouter.StatusHealthy {
		t.Fatalf("second pass must be healthy, got %s", got)
	}
	p.healthErr = errors.New("daemon stopped")
	mgr.CheckAll(context.Background())
	if got := mgr.StatusOf("claude"); got != llmrouter.StatusOffline {
		t.Fatalf("failed check must be offline, got %s", got)
	}
	// Generation failures degrade a healthy provider immediately.
	p.healthErr = nil
	mgr.CheckAll(context.Background())
	mgr.CheckAll(context.Background())
	mgr.ReportGenerationFailure("claude", errors.New("oom"))
	if got := mgr.StatusOf("claude"); got != llmrouter.StatusDegraded {
		t.Fatalf("generation failure must degrade, got %s", got)
	}
}

// ---- full publication flow (Part 13) ---------------------------------------------------

func TestDraftPublishesToSocialAsAgent(t *testing.T) {
	h := newHarness(t, []portllm.Provider{&fakeProvider{name: "claude"}},
		antispam.DefaultPolicy())

	cand, err := h.engine.Publish(context.Background(), h.input())
	if err != nil {
		t.Fatal(err)
	}
	if cand.Status != publication.CandidatePublished {
		t.Fatalf("want PUBLISHED, got %s (%s)", cand.Status, cand.StatusReason)
	}
	if len(h.social.posts) != 1 {
		t.Fatal("exactly one Social post expected")
	}
	post := h.social.posts[0]
	// Seeded Social agent id + agent author type (Part 13).
	if post.SocialAuthorID != persona.SocialAuthorIDs["ninja"] {
		t.Fatalf("must publish as the seeded ninja id, got %s", post.SocialAuthorID)
	}
	if post.Metadata["title"] == "" || post.Content == "" {
		t.Fatal("post must carry composed title metadata + summary content")
	}
	// Explainability (Part 12).
	if cand.Provider != "claude" || cand.PromptVersion != promptbuilder.Version {
		t.Fatalf("explainability fields missing: %+v", cand)
	}
	if cand.DecisionID == uuid.Nil || len(cand.TrendIDs) == 0 ||
		cand.PublicationReason == "" {
		t.Fatal("candidate must store decision, trends and reason")
	}
	// Publication memory (Part 8): "I already posted about this story."
	pubs, _ := h.memories.RecentPublications(context.Background(),
		h.agentID, h.clusterID, 5)
	if len(pubs) != 1 || pubs[0].Kind != memory.KindPublication {
		t.Fatal("publication must be remembered")
	}
}

// ---- ticket fallback (Part 14) -----------------------------------------------------------

func TestAllProvidersFailedCreatesTicketNeverPublishes(t *testing.T) {
	providers := []portllm.Provider{
		&fakeProvider{name: "claude", genErr: errors.New("down")},
		&fakeProvider{name: "gpt", genErr: errors.New("down")},
		&fakeProvider{name: "gemini", genErr: errors.New("down")},
	}
	h := newHarness(t, providers, antispam.DefaultPolicy())

	cand, err := h.engine.Publish(context.Background(), h.input())
	if err != nil {
		t.Fatal(err)
	}
	if cand.Status != publication.CandidateTicketed {
		t.Fatalf("want TICKETED, got %s", cand.Status)
	}
	if len(h.social.posts) != 0 {
		t.Fatal("NON-NEGOTIABLE violated: nothing may auto-publish on total failure")
	}
	tickets, _ := h.tickets.List(context.Background(), publication.TicketOpen, 10)
	if len(tickets) != 1 {
		t.Fatal("exactly one OPEN ticket expected")
	}
	tk := tickets[0]
	// Complete enough for manual publication.
	if tk.SuggestedTitle == "" || tk.SuggestedSummary == "" ||
		len(tk.Evidence) == 0 || tk.PublicationReason == "" {
		t.Fatalf("ticket must be complete for human review: %+v", tk)
	}
	if tk.AgentName != "ninja" || tk.Priority != "HIGH" {
		t.Fatalf("ticket context wrong: %+v", tk)
	}
	if len(cand.FallbackChain) != 3 {
		t.Fatalf("full fallback chain must be recorded: %v", cand.FallbackChain)
	}
}

func TestTicketStatusTransitions(t *testing.T) {
	ok := []struct{ from, to publication.TicketStatus }{
		{publication.TicketOpen, publication.TicketUnderReview},
		{publication.TicketUnderReview, publication.TicketApproved},
		{publication.TicketApproved, publication.TicketPublished},
		{publication.TicketUnderReview, publication.TicketRejected},
	}
	for _, c := range ok {
		if !publication.ValidTicketTransition(c.from, c.to) {
			t.Fatalf("%s → %s must be valid", c.from, c.to)
		}
	}
	bad := []struct{ from, to publication.TicketStatus }{
		{publication.TicketOpen, publication.TicketPublished},
		{publication.TicketRejected, publication.TicketApproved},
		{publication.TicketPublished, publication.TicketOpen},
	}
	for _, c := range bad {
		if publication.ValidTicketTransition(c.from, c.to) {
			t.Fatalf("%s → %s must be invalid", c.from, c.to)
		}
	}
}

// ---- anti-spam (Part 11) -----------------------------------------------------------------

func TestAntiSpamCooldownsAreExplained(t *testing.T) {
	h := newHarness(t, []portllm.Provider{&fakeProvider{name: "claude"}},
		antispam.DefaultPolicy())

	if _, err := h.engine.Publish(context.Background(), h.input()); err != nil {
		t.Fatal(err)
	}
	// Immediate second attempt → agent cooldown.
	cand, err := h.engine.Publish(context.Background(), h.input())
	if err != nil {
		t.Fatal(err)
	}
	if cand.Status != publication.CandidateSuppressed {
		t.Fatalf("want SUPPRESSED, got %s", cand.Status)
	}
	if !strings.Contains(cand.StatusReason, "agent_cooldown") {
		t.Fatalf("suppression must be explained: %q", cand.StatusReason)
	}
	if len(h.social.posts) != 1 {
		t.Fatal("suppressed candidate must not publish")
	}
}

func TestAntiSpamDailyLimit(t *testing.T) {
	log := inmemory.NewSpamLog()
	agentID := uuid.New()
	now := time.Now().UTC()
	for i := 0; i < 3; i++ {
		_ = log.Record(context.Background(), antispam.Entry{
			AgentID:     agentID,
			TrendID:     fmt.Sprintf("t%d", i),
			PublishedAt: now.Add(-time.Duration(i+2) * time.Hour),
		})
	}
	engine := antispam.New(antispam.Policy{DailyLimit: 3}, log, nopPubMetrics{},
		func() time.Time { return now })
	verdict, err := engine.Check(context.Background(), agentID, uuid.Nil, "t9", "")
	if err != nil {
		t.Fatal(err)
	}
	if verdict.Allowed || !strings.Contains(verdict.Reason, "daily_limit") {
		t.Fatalf("daily limit must suppress with explanation: %+v", verdict)
	}
}

func TestAntiSpamScopedCooldowns(t *testing.T) {
	log := inmemory.NewSpamLog()
	agentA, agentB := uuid.New(), uuid.New()
	clusterID := uuid.New()
	now := time.Now().UTC()
	_ = log.Record(context.Background(), antispam.Entry{
		AgentID: agentA, ClusterID: clusterID, TrendID: "t1",
		MatchID: "m1", PublishedAt: now.Add(-time.Minute),
	})
	engine := antispam.New(antispam.Policy{
		ClusterCooldown: 15 * time.Minute,
	}, log, nopPubMetrics{}, func() time.Time { return now })

	// Different agent, same STORY → cluster cooldown applies.
	verdict, err := engine.Check(context.Background(), agentB, clusterID, "t2", "m2")
	if err != nil {
		t.Fatal(err)
	}
	if verdict.Allowed || !strings.Contains(verdict.Reason, "cluster_cooldown") {
		t.Fatalf("cluster cooldown must apply across agents: %+v", verdict)
	}
	// Different cluster → allowed.
	verdict, _ = engine.Check(context.Background(), agentB, uuid.New(), "t3", "m3")
	if !verdict.Allowed {
		t.Fatalf("unrelated story must pass: %+v", verdict)
	}
}

// ---- validation (Part 10) -----------------------------------------------------------------

func TestValidatorRules(t *testing.T) {
	v := draftvalidator.New()
	p := persona.Defaults()[0]
	base := publication.ComposedPost{
		Title:   "Mercado firmando",
		Summary: "O consenso entre as casas subiu de forma consistente.",
	}

	if r := v.Validate(base, p, nil); !r.Valid {
		t.Fatalf("baseline must pass: %s", r.Reason)
	}
	cases := []struct {
		name   string
		mutate func(publication.ComposedPost) publication.ComposedPost
		titles []string
		want   string
	}{
		{"empty title", func(c publication.ComposedPost) publication.ComposedPost { c.Title = ""; return c }, nil, "empty_content"},
		{"long title", func(c publication.ComposedPost) publication.ComposedPost {
			c.Title = strings.Repeat("a", 150)
			return c
		}, nil, "length"},
		{"forbidden", func(c publication.ComposedPost) publication.ComposedPost {
			c.Summary = "Aposta garantida no mandante hoje."
			return c
		}, nil, "forbidden_content"},
		{"shouting", func(c publication.ComposedPost) publication.ComposedPost {
			c.Title = "MERCADO EXPLODINDO AGORA MESMO"
			return c
		}, nil, "spam"},
		{"duplicate", func(c publication.ComposedPost) publication.ComposedPost { return c }, []string{"mercado firmando"}, "duplicate"},
		{"score prediction", func(c publication.ComposedPost) publication.ComposedPost {
			c.Summary = "O placar final será 2x0 sem dúvidas."
			return c
		}, nil, "persona"},
	}
	for _, tc := range cases {
		r := v.Validate(tc.mutate(base), p, tc.titles)
		if r.Valid || !strings.Contains(r.Reason, tc.want) {
			t.Fatalf("%s: want reason containing %q, got %+v", tc.name, tc.want, r)
		}
	}
}

func TestInvalidDraftNeverPublishes(t *testing.T) {
	// Provider answers parseable JSON containing forbidden content.
	bad := `{"title":"Dica de hoje","summary":"Aposta garantida no mandante, stake alto."}`
	h := newHarness(t, []portllm.Provider{&fakeProvider{name: "claude", text: bad}},
		antispam.DefaultPolicy())

	cand, err := h.engine.Publish(context.Background(), h.input())
	if err != nil {
		t.Fatal(err)
	}
	if cand.Status != publication.CandidateInvalid {
		t.Fatalf("want INVALID, got %s", cand.Status)
	}
	if len(h.social.posts) != 0 {
		t.Fatal("invalid drafts NEVER publish")
	}
	if !strings.Contains(cand.StatusReason, "forbidden_content") {
		t.Fatalf("rejection must be explained: %q", cand.StatusReason)
	}
}

// ---- prompt builder (Part 6) -------------------------------------------------------------------

func TestPromptBuilderIsDeterministicAndVersioned(t *testing.T) {
	in := promptbuilder.Input{
		Persona: persona.Defaults()[0],
		Draft: draft.Draft{
			Title: "T", Summary: "S", Highlights: []string{"h1", "h2"},
		},
		Context: contextbuilder.DraftContext{
			ClusterType: "market_move", DraftType: "INITIAL",
			Priority: "HIGH", Sequence: 1,
		},
		PreviousTitles: []string{"b-title", "a-title"},
	}
	a := promptbuilder.Build(in)
	b := promptbuilder.Build(in)
	if a.Prompt != b.Prompt || a.System != b.System {
		t.Fatal("prompts must be deterministic for identical inputs")
	}
	if a.Version != promptbuilder.Version || a.Version == "" {
		t.Fatal("prompt version must be set")
	}
	if !strings.Contains(a.Prompt, "YOU ALREADY POSTED") {
		t.Fatal("anti-repetition section missing")
	}
	if !strings.Contains(a.System, "never gives betting advice") {
		t.Fatal("persona restrictions must reach the system prompt")
	}
}

// ---- memory expansion (Part 8) -----------------------------------------------------------------

func TestRepetitionGuardUsesPublicationMemory(t *testing.T) {
	h := newHarness(t, []portllm.Provider{&fakeProvider{name: "claude"}},
		antispam.Policy{}) // budgets off — isolate the duplicate rule

	if _, err := h.engine.Publish(context.Background(), h.input()); err != nil {
		t.Fatal(err)
	}
	// Same story again: the provider returns the SAME title → the
	// duplicate guard (fed by publication memory) rejects it.
	cand, err := h.engine.Publish(context.Background(), h.input())
	if err != nil {
		t.Fatal(err)
	}
	if cand.Status != publication.CandidateInvalid ||
		!strings.Contains(cand.StatusReason, "duplicate") {
		t.Fatalf("repeat title on the same story must be rejected: %+v", cand)
	}
	if len(h.social.posts) != 1 {
		t.Fatal("the repeat must not publish")
	}
}

// ---- social failure ------------------------------------------------------------------------------

func TestSocialFailureRecordsFailedCandidate(t *testing.T) {
	h := newHarness(t, []portllm.Provider{&fakeProvider{name: "claude"}},
		antispam.DefaultPolicy())
	h.social.err = errors.New("unavailable")

	cand, err := h.engine.Publish(context.Background(), h.input())
	if err != nil {
		t.Fatal(err)
	}
	if cand.Status != publication.CandidateFailed ||
		!strings.Contains(cand.StatusReason, "social_publish_failed") {
		t.Fatalf("social failure must be a FAILED candidate: %+v", cand)
	}
}
