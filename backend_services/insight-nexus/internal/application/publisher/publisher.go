// Publication Engine — Sprint 4 Parts 13 + 14.
//
//	Draft (deterministic, queued)
//	    ↓ anti-spam check          → SUPPRESSED candidate (explained)
//	    ↓ prompt builder           (versioned, persona-driven)
//	    ↓ LLM router               (claude → gpt → gemini)
//	    ↓ all providers failed?    → PUBLICATION TICKET (never auto-publish,
//	    ↓                            never a template post)
//	    ↓ draft validator          → INVALID candidate (explained)
//	    ↓ Social PostService       → PUBLISHED candidate + memory + log
//
// Atlas decided; Nexus communicates. The LLM only phrases — every
// candidate stores trend ids, cluster, decision, reason, prompt
// version, provider, model and the fallback chain (Part 12).
package publisher

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-nexus/internal/application/antispam"
	"github.com/konoha-labs/insight-nexus/internal/application/contextbuilder"
	"github.com/konoha-labs/insight-nexus/internal/application/draftvalidator"
	"github.com/konoha-labs/insight-nexus/internal/application/llmrouter"
	"github.com/konoha-labs/insight-nexus/internal/application/promptbuilder"
	"github.com/konoha-labs/insight-nexus/internal/domain/decision"
	"github.com/konoha-labs/insight-nexus/internal/domain/draft"
	"github.com/konoha-labs/insight-nexus/internal/domain/memory"
	"github.com/konoha-labs/insight-nexus/internal/domain/publication"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

// Metrics — observability seam.
type Metrics interface {
	DraftComposed(agent string)
	Published(agent string)
	PublicationFailed(agent string, stage string)
	TicketCreated(agent string)
}

// Input — everything one publication attempt needs (assembled by the
// pipeline after decision/state/evolution ran).
type Input struct {
	Draft    draft.Draft
	Context  contextbuilder.DraftContext
	Decision decision.PublicationDecision
}

type Engine struct {
	personas   ports.PersonaRepository
	router     *llmrouter.Router
	validator  *draftvalidator.Validator
	spam       *antispam.Engine
	candidates ports.CandidateRepository
	tickets    ports.TicketRepository
	social     ports.SocialPublisher
	memories   ports.MemoryRepository

	metrics Metrics
	logger  zerolog.Logger
	now     func() time.Time
}

func New(
	personas ports.PersonaRepository,
	router *llmrouter.Router,
	validator *draftvalidator.Validator,
	spam *antispam.Engine,
	candidates ports.CandidateRepository,
	tickets ports.TicketRepository,
	social ports.SocialPublisher,
	memories ports.MemoryRepository,
	metrics Metrics,
	logger zerolog.Logger,
	now func() time.Time,
) *Engine {
	if now == nil {
		now = func() time.Time { return time.Now().UTC() }
	}
	return &Engine{
		personas: personas, router: router, validator: validator,
		spam: spam, candidates: candidates, tickets: tickets,
		social: social, memories: memories,
		metrics: metrics, logger: logger, now: now,
	}
}

// Publish runs the full workflow for one queued draft. Errors are
// returned only for infrastructure failures — product outcomes
// (suppressed / invalid / ticketed) are recorded, not errors.
func (e *Engine) Publish(ctx context.Context, in Input) (publication.Candidate, error) {
	base := e.baseCandidate(in)

	// 1. Anti-spam budgets (Part 11). Every suppression is recorded
	// AND explained.
	verdict, err := e.spam.Check(ctx, in.Draft.AgentID,
		in.Context.ClusterID, in.Draft.TrendID, in.Draft.MatchID)
	if err != nil {
		return base, fmt.Errorf("antispam check: %w", err)
	}
	if !verdict.Allowed {
		base.Status = publication.CandidateSuppressed
		base.StatusReason = verdict.Reason
		e.metrics.PublicationFailed(in.Context.Agent.Name, "suppressed")
		return base, e.candidates.Save(ctx, base)
	}

	// 2. Persona + repetition memory (Part 8): previous publication
	// titles on this story feed both the prompt and the validator.
	personaDef, err := e.personas.Get(ctx, in.Context.Agent.Name)
	if err != nil {
		return base, fmt.Errorf("persona %q: %w", in.Context.Agent.Name, err)
	}
	prevTitles := e.previousTitles(ctx, in)

	// 3. Versioned prompt (Part 6).
	req := promptbuilder.Build(promptbuilder.Input{
		Persona:        personaDef,
		Draft:          in.Draft,
		Context:        in.Context,
		PreviousTitles: prevTitles,
	})
	base.PromptVersion = req.Version

	// 4. Routed generation (Part 5) with per-attempt parse validation.
	var composed publication.ComposedPost
	resp, route, err := e.router.Generate(ctx, req.GenerateRequest,
		func(text string) error {
			parsed, perr := publication.ParseComposedPost(text)
			if perr != nil {
				return perr
			}
			composed = parsed
			return nil
		})
	base.FallbackChain = route.Chain
	if err != nil {
		if errors.Is(err, llmrouter.ErrAllProvidersFailed) {
			// Part 14: NEVER auto-publish, NEVER template-post.
			return e.ticketFallback(ctx, in, base)
		}
		return base, fmt.Errorf("llm generate: %w", err)
	}
	_ = resp
	base.Provider = route.Provider
	base.Model = route.Model
	base.FallbackUsed = route.FallbackUsed
	base.Title = composed.Title
	base.Summary = composed.Summary
	base.Highlights = composed.Highlights
	base.Tags = composed.Tags
	base.ChartHints = composed.ChartHints
	e.metrics.DraftComposed(in.Context.Agent.Name)

	// 5. Validation (Part 10). Invalid drafts never publish.
	result := e.validator.Validate(composed, personaDef, prevTitles)
	if !result.Valid {
		base.Status = publication.CandidateInvalid
		base.StatusReason = result.Reason
		e.metrics.PublicationFailed(in.Context.Agent.Name, "invalid")
		return base, e.candidates.Save(ctx, base)
	}

	// 6. Social publication (Part 13) — APIs only, author_type=agent,
	// seeded Social author id.
	postID, err := e.social.PublishAgentPost(ctx, ports.AgentPostRequest{
		SocialAuthorID: personaDef.SocialAuthorID,
		Content:        composed.Summary,
		Metadata:       e.postMetadata(in, base, composed),
		Visibility:     "public",
	})
	if err != nil {
		base.Status = publication.CandidateFailed
		base.StatusReason = "social_publish_failed: " + err.Error()
		e.metrics.PublicationFailed(in.Context.Agent.Name, "social")
		return base, e.candidates.Save(ctx, base)
	}

	now := e.now()
	base.Status = publication.CandidatePublished
	base.SocialPostID = postID
	base.PublishedAt = &now
	if err := e.candidates.Save(ctx, base); err != nil {
		return base, err
	}
	// Publication memory (Part 8): "I already posted about this story."
	_ = e.memories.Save(ctx, memory.Memory{
		ID:          uuid.New(),
		AgentID:     in.Draft.AgentID,
		MatchID:     in.Draft.MatchID,
		TrendID:     in.Draft.TrendID,
		ClusterType: in.Context.ClusterType,
		ClusterID:   in.Context.ClusterID,
		Kind:        memory.KindPublication,
		Summary:     "published: " + composed.Title,
		Narrative:   composed.Title,
		CreatedAt:   now,
	})
	// Anti-spam log (persisted budgets).
	if err := e.spam.RecordPublication(ctx, in.Draft.AgentID,
		in.Context.ClusterID, in.Draft.TrendID, in.Draft.MatchID); err != nil {
		e.logger.Error().Err(err).Msg("antispam_record_failed")
	}
	e.metrics.Published(in.Context.Agent.Name)
	e.logger.Info().
		Str("agent", in.Context.Agent.Name).
		Str("social_post_id", postID).
		Str("provider", base.Provider).
		Bool("fallback_used", base.FallbackUsed).
		Msg("agent_post_published")
	return base, nil
}

// ticketFallback creates the human-review ticket (Part 14): complete
// enough for manual publication, suggested content comes from the
// DETERMINISTIC draft (never an LLM template).
func (e *Engine) ticketFallback(
	ctx context.Context, in Input, base publication.Candidate,
) (publication.Candidate, error) {
	ticket := publication.Ticket{
		ID:        uuid.New(),
		AgentID:   in.Draft.AgentID,
		AgentName: in.Context.Agent.Name,
		TrendIDs:  base.TrendIDs,
		ClusterID: in.Context.ClusterID,
		Context: map[string]any{
			"cluster_type": in.Context.ClusterType,
			"match_id":     in.Draft.MatchID,
			"action":       in.Context.Action,
			"priority":     in.Context.Priority,
			"agent_state":  in.Context.AgentState,
			"draft_type":   in.Context.DraftType,
			"sequence":     in.Context.Sequence,
		},
		PublicationReason: base.PublicationReason,
		SuggestedTitle:    in.Draft.Title,
		SuggestedSummary:  in.Draft.Summary,
		Evidence:          in.Draft.Highlights,
		Priority:          in.Context.Priority,
		MatchID:           in.Draft.MatchID,
		Status:            publication.TicketOpen,
		CreatedAt:         e.now(),
	}
	if err := e.tickets.Save(ctx, ticket); err != nil {
		return base, fmt.Errorf("ticket save: %w", err)
	}
	base.Status = publication.CandidateTicketed
	base.StatusReason = "all_providers_failed: ticket " + ticket.ID.String()
	e.metrics.TicketCreated(in.Context.Agent.Name)
	e.logger.Warn().
		Str("agent", in.Context.Agent.Name).
		Str("ticket_id", ticket.ID.String()).
		Strs("fallback_chain", base.FallbackChain).
		Msg("publication_ticket_created")
	return base, e.candidates.Save(ctx, base)
}

func (e *Engine) baseCandidate(in Input) publication.Candidate {
	return publication.Candidate{
		ID:                uuid.New(),
		DraftID:           in.Draft.ID,
		AgentID:           in.Draft.AgentID,
		AgentName:         in.Context.Agent.Name,
		TrendIDs:          []string{in.Draft.TrendID},
		ClusterID:         in.Context.ClusterID,
		DecisionID:        in.Decision.ID,
		PublicationReason: publicationReason(in.Decision),
		DraftVersion:      in.Context.Sequence,
		MatchID:           in.Draft.MatchID,
		CreatedAt:         e.now(),
	}
}

func (e *Engine) previousTitles(ctx context.Context, in Input) []string {
	if in.Context.ClusterID == uuid.Nil {
		return nil
	}
	pubs, err := e.memories.RecentPublications(ctx, in.Draft.AgentID,
		in.Context.ClusterID, 5)
	if err != nil {
		e.logger.Warn().Err(err).Msg("recent_publications_lookup_failed")
		return nil
	}
	titles := make([]string, 0, len(pubs))
	for _, m := range pubs {
		if m.Narrative != "" {
			titles = append(titles, m.Narrative)
		}
	}
	return titles
}

// postMetadata — the Social post metadata block: matches the agent
// post shape Azteca's FeedAgentMeta consumes (title, highlights,
// tags) plus explainability references.
func (e *Engine) postMetadata(
	in Input, base publication.Candidate, composed publication.ComposedPost,
) map[string]string {
	meta := map[string]string{
		"title":      composed.Title,
		"trend_id":   in.Draft.TrendID,
		"cluster_id": in.Context.ClusterID.String(),
		"draft_type": in.Context.DraftType,
		"priority":   in.Context.Priority,
	}
	if len(composed.Highlights) > 0 {
		if raw, err := json.Marshal(composed.Highlights); err == nil {
			meta["highlights"] = string(raw)
		}
	}
	if len(composed.Tags) > 0 {
		if raw, err := json.Marshal(composed.Tags); err == nil {
			meta["tags"] = string(raw)
		}
	}
	if len(composed.ChartHints) > 0 {
		if raw, err := json.Marshal(composed.ChartHints); err == nil {
			meta["chart_hints"] = string(raw)
		}
	}
	if in.Draft.MatchID != "" {
		meta["match_id"] = in.Draft.MatchID
	}
	return meta
}

func publicationReason(d decision.PublicationDecision) string {
	if len(d.Reasoning) == 0 {
		return string(d.Action)
	}
	reason := d.Reasoning[0]
	for _, r := range d.Reasoning[1:] {
		reason += "; " + r
	}
	return reason
}

// ---- Sprint 4.5 — Console manual publication ------------------------------

// ManualInput — an admin-authored (or admin-edited) publication. The
// content is human-written; it still passes the SAME validator and
// publishes through the SAME Social API as automatic posts.
type ManualInput struct {
	AgentSlug  string
	Title      string
	Summary    string
	Highlights []string
	Tags       []string
	ChartHints []string
	MatchID    string
	TrendIDs   []string
	ClusterID  uuid.UUID
	// Actor — the admin performing the publication (attribution).
	Actor string
	// Reason — why this manual publication exists (e.g. "ticket abc
	// approved", "editorial post").
	Reason string
}

// PublishManual publishes admin-authored content as an agent. Skips
// anti-spam budgets (a human is the rate limiter) but NEVER skips
// validation or the Social API path.
func (e *Engine) PublishManual(ctx context.Context, in ManualInput) (publication.Candidate, error) {
	personaDef, err := e.personas.Get(ctx, in.AgentSlug)
	if err != nil {
		return publication.Candidate{}, fmt.Errorf("persona %q: %w", in.AgentSlug, err)
	}
	composed := publication.ComposedPost{
		Title:      in.Title,
		Summary:    in.Summary,
		Highlights: in.Highlights,
		Tags:       in.Tags,
		ChartHints: in.ChartHints,
	}
	cand := publication.Candidate{
		ID:                uuid.New(),
		DraftID:           uuid.New(),
		AgentID:           personaDef.SocialAuthorID,
		AgentName:         in.AgentSlug,
		TrendIDs:          in.TrendIDs,
		ClusterID:         in.ClusterID,
		PublicationReason: "manual: " + in.Reason,
		PromptVersion:     "manual",
		Provider:          "manual",
		Model:             "human:" + in.Actor,
		Title:             composed.Title,
		Summary:           composed.Summary,
		Highlights:        composed.Highlights,
		Tags:              composed.Tags,
		ChartHints:        composed.ChartHints,
		MatchID:           in.MatchID,
		CreatedAt:         e.now(),
	}
	result := e.validator.Validate(composed, personaDef, nil)
	if !result.Valid {
		cand.Status = publication.CandidateInvalid
		cand.StatusReason = result.Reason
		e.metrics.PublicationFailed(in.AgentSlug, "invalid")
		return cand, e.candidates.Save(ctx, cand)
	}
	meta := map[string]string{"title": composed.Title, "manual": "true"}
	if len(composed.Highlights) > 0 {
		if raw, err := json.Marshal(composed.Highlights); err == nil {
			meta["highlights"] = string(raw)
		}
	}
	if len(composed.Tags) > 0 {
		if raw, err := json.Marshal(composed.Tags); err == nil {
			meta["tags"] = string(raw)
		}
	}
	if in.MatchID != "" {
		meta["match_id"] = in.MatchID
	}
	postID, err := e.social.PublishAgentPost(ctx, ports.AgentPostRequest{
		SocialAuthorID: personaDef.SocialAuthorID,
		Content:        composed.Summary,
		Metadata:       meta,
		Visibility:     "public",
	})
	if err != nil {
		cand.Status = publication.CandidateFailed
		cand.StatusReason = "social_publish_failed: " + err.Error()
		e.metrics.PublicationFailed(in.AgentSlug, "social")
		return cand, e.candidates.Save(ctx, cand)
	}
	now := e.now()
	cand.Status = publication.CandidatePublished
	cand.SocialPostID = postID
	cand.PublishedAt = &now
	e.metrics.Published(in.AgentSlug)
	return cand, e.candidates.Save(ctx, cand)
}
