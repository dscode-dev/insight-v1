// Console operations API — Sprint 4.5, hardened in V1.1. The mutation
// surface the Insight Console consumes: ticket review, manual
// publication, persona editing, the immutable audit log and the trend
// DLQ (inspect/replay).
//
// EVERY mutation records an audit event whose actor is the VERIFIED
// operator identity validated by Insight Gateway (ActorFromContext). Request
// bodies cannot declare an actor; Gateway-issued permissions are enforced by
// RequireAuth before any handler here runs.
package httpapi

import (
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-nexus/internal/application/publisher"
	"github.com/konoha-labs/insight-nexus/internal/domain/persona"
	"github.com/konoha-labs/insight-nexus/internal/domain/publication"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

// ConsoleOpsDeps — all optional as a block (nil Tickets disables).
type ConsoleOpsDeps struct {
	Tickets                    ports.TicketRepository
	Personas                   ports.PersonaRepository
	Audit                      ports.AuditRepository
	Publisher                  *publisher.Engine // nil when publication is disabled or unavailable
	PublisherUnavailableReason string
	DLQ                        ports.TrendDLQ // nil when the Redis consumer is disabled
	Logger                     zerolog.Logger
	Now                        func() time.Time
}

// opActor resolves the verified operator identity set by RequireAuth.
func opActor(r *http.Request) string {
	if c, ok := ActorFromContext(r.Context()); ok {
		return c.Subject
	}
	return ""
}

// RegisterConsoleOps mounts the Sprint 4.5 mutation endpoints.
func RegisterConsoleOps(mux *http.ServeMux, d ConsoleOpsDeps) {
	if d.Now == nil {
		d.Now = func() time.Time { return time.Now().UTC() }
	}

	// GET /v1/publications/tickets/{id} — single ticket (Console
	// detail page).
	mux.HandleFunc("GET /v1/publications/tickets/{id}", func(w http.ResponseWriter, r *http.Request) {
		id, err := uuid.Parse(r.PathValue("id"))
		if err != nil {
			pubBadRequest(w, "invalid ticket id")
			return
		}
		ticket, err := d.Tickets.Get(r.Context(), id)
		if err != nil {
			if errors.Is(err, ports.ErrNotFound) {
				pubNotFound(w)
				return
			}
			pubError(w, err)
			return
		}
		pubJSON(w, map[string]any{"ticket": ticket})
	})

	// PATCH /v1/publications/tickets/{id} — review transition (+
	// optional suggested-content edits). Body:
	// {status, reason, edits:{suggested_title, suggested_summary, evidence}}
	mux.HandleFunc("PATCH /v1/publications/tickets/{id}", func(w http.ResponseWriter, r *http.Request) {
		actor := opActor(r)
		if actor == "" {
			authError(w, http.StatusUnauthorized, "verified actor required")
			return
		}
		id, err := uuid.Parse(r.PathValue("id"))
		if err != nil {
			pubBadRequest(w, "invalid ticket id")
			return
		}
		var body struct {
			Status string `json:"status"`
			Reason string `json:"reason"`
			Edits  *struct {
				SuggestedTitle   string   `json:"suggested_title"`
				SuggestedSummary string   `json:"suggested_summary"`
				Evidence         []string `json:"evidence"`
			} `json:"edits"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			pubBadRequest(w, "invalid json")
			return
		}
		ticket, err := d.Tickets.Get(r.Context(), id)
		if err != nil {
			if errors.Is(err, ports.ErrNotFound) {
				pubNotFound(w)
				return
			}
			pubError(w, err)
			return
		}
		before := ticketSnapshot(ticket)

		if body.Edits != nil {
			if body.Edits.SuggestedTitle != "" {
				ticket.SuggestedTitle = body.Edits.SuggestedTitle
			}
			if body.Edits.SuggestedSummary != "" {
				ticket.SuggestedSummary = body.Edits.SuggestedSummary
			}
			if body.Edits.Evidence != nil {
				ticket.Evidence = body.Edits.Evidence
			}
		}
		if body.Status != "" {
			next := publication.TicketStatus(body.Status)
			if !publication.ValidTicketTransition(ticket.Status, next) {
				pubBadRequest(w, "invalid transition "+string(ticket.Status)+" → "+string(next))
				return
			}
			now := d.Now()
			ticket.Status = next
			switch next {
			case publication.TicketUnderReview, publication.TicketApproved,
				publication.TicketRejected:
				ticket.ReviewedBy = actor
				ticket.ReviewedAt = &now
			case publication.TicketPublished:
				ticket.PublishedBy = actor
				ticket.PublishedAt = &now
			}
		}
		if err := d.Tickets.Save(r.Context(), ticket); err != nil {
			pubError(w, err)
			return
		}
		recordAudit(r, d, actor, "ticket."+actionOf(body.Status, body.Edits != nil),
			"ticket", ticket.ID.String(), before, ticketSnapshot(ticket), body.Reason)
		pubJSON(w, map[string]any{"ticket": ticket})
	})

	// POST /v1/publications/tickets/{id}/publish — publish a ticket's
	// (possibly edited) content as the agent. Approved tickets only.
	mux.HandleFunc("POST /v1/publications/tickets/{id}/publish", func(w http.ResponseWriter, r *http.Request) {
		actor := opActor(r)
		if actor == "" {
			authError(w, http.StatusUnauthorized, "verified actor required")
			return
		}
		if d.Publisher == nil {
			pubUnavailable(w, publisherUnavailableReason(d))
			return
		}
		id, err := uuid.Parse(r.PathValue("id"))
		if err != nil {
			pubBadRequest(w, "invalid ticket id")
			return
		}
		var body struct {
			Reason string `json:"reason"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			pubBadRequest(w, "invalid json")
			return
		}
		ticket, err := d.Tickets.Get(r.Context(), id)
		if err != nil {
			pubNotFound(w)
			return
		}
		if ticket.Status != publication.TicketApproved {
			pubBadRequest(w, "only APPROVED tickets publish (current: "+string(ticket.Status)+")")
			return
		}
		before := ticketSnapshot(ticket)
		cand, err := d.Publisher.PublishManual(r.Context(), publisher.ManualInput{
			AgentSlug: ticket.AgentName,
			Title:     ticket.SuggestedTitle,
			Summary:   ticket.SuggestedSummary,
			// Evidence is reviewer-facing context and can exceed the
			// post highlight budget — publish at most the validator's
			// cap (the operator can edit evidence before approving to
			// choose which lines survive).
			Highlights: capHighlights(ticket.Evidence),
			MatchID:    ticket.MatchID,
			TrendIDs:   ticket.TrendIDs,
			ClusterID:  ticket.ClusterID,
			Actor:      actor,
			Reason:     "ticket " + ticket.ID.String() + ": " + body.Reason,
		})
		if err != nil {
			pubError(w, err)
			return
		}
		if cand.Status == publication.CandidatePublished {
			now := d.Now()
			ticket.Status = publication.TicketPublished
			ticket.PublishedBy = actor
			ticket.PublishedAt = &now
			if err := d.Tickets.Save(r.Context(), ticket); err != nil {
				pubError(w, err)
				return
			}
		}
		recordAudit(r, d, actor, "ticket.publish", "ticket",
			ticket.ID.String(), before, ticketSnapshot(ticket), body.Reason)
		pubJSON(w, map[string]any{"ticket": ticket, "candidate": cand})
	})

	// POST /v1/publications/manual — admin-authored publication as any
	// agent (Select Agent → Draft → Review → Publish on the Console).
	mux.HandleFunc("POST /v1/publications/manual", func(w http.ResponseWriter, r *http.Request) {
		actor := opActor(r)
		if actor == "" {
			authError(w, http.StatusUnauthorized, "verified actor required")
			return
		}
		if d.Publisher == nil {
			pubUnavailable(w, publisherUnavailableReason(d))
			return
		}
		var body struct {
			AgentSlug  string   `json:"agent_slug"`
			Title      string   `json:"title"`
			Summary    string   `json:"summary"`
			Highlights []string `json:"highlights"`
			Tags       []string `json:"tags"`
			ChartHints []string `json:"chart_hints"`
			MatchID    string   `json:"match_id"`
			Reason     string   `json:"reason"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			pubBadRequest(w, "invalid json")
			return
		}
		if body.AgentSlug == "" {
			pubBadRequest(w, "agent_slug required")
			return
		}
		cand, err := d.Publisher.PublishManual(r.Context(), publisher.ManualInput{
			AgentSlug:  body.AgentSlug,
			Title:      body.Title,
			Summary:    body.Summary,
			Highlights: body.Highlights,
			Tags:       body.Tags,
			ChartHints: body.ChartHints,
			MatchID:    body.MatchID,
			Actor:      actor,
			Reason:     body.Reason,
		})
		if err != nil {
			if errors.Is(err, ports.ErrNotFound) {
				pubBadRequest(w, "unknown agent "+body.AgentSlug)
				return
			}
			pubError(w, err)
			return
		}
		recordAudit(r, d, actor, "publication.manual", "candidate",
			cand.ID.String(), nil,
			map[string]any{"status": cand.Status, "title": cand.Title,
				"agent": cand.AgentName, "social_post_id": cand.SocialPostID},
			body.Reason)
		pubJSON(w, map[string]any{"candidate": cand})
	})

	// GET /v1/personas + PUT /v1/personas/{slug} — persona management.
	mux.HandleFunc("GET /v1/personas", func(w http.ResponseWriter, r *http.Request) {
		out, err := d.Personas.List(r.Context())
		if err != nil {
			pubError(w, err)
			return
		}
		pubJSON(w, map[string]any{"personas": out})
	})
	mux.HandleFunc("PUT /v1/personas/{slug}", func(w http.ResponseWriter, r *http.Request) {
		actor := opActor(r)
		if actor == "" {
			authError(w, http.StatusUnauthorized, "verified actor required")
			return
		}
		slug := r.PathValue("slug")
		var body struct {
			persona.AgentPersona
			Reason string `json:"reason"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			pubBadRequest(w, "invalid json")
			return
		}
		var before map[string]any
		if prev, err := d.Personas.Get(r.Context(), slug); err == nil {
			before = personaSnapshot(prev)
		}
		p := body.AgentPersona
		p.Slug = slug
		p.UpdatedAt = d.Now()
		if err := p.Validate(); err != nil {
			pubBadRequest(w, err.Error())
			return
		}
		if err := d.Personas.Upsert(r.Context(), p); err != nil {
			pubError(w, err)
			return
		}
		recordAudit(r, d, actor, "persona.update", "persona", slug,
			before, personaSnapshot(p), body.Reason)
		pubJSON(w, map[string]any{"persona": p})
	})

	// Audit log: immutable — record + search only. POSTs carry the
	// console-side action detail; the actor is ALWAYS the verified
	// token subject (a forged actor field is overwritten).
	mux.HandleFunc("POST /v1/audit/events", func(w http.ResponseWriter, r *http.Request) {
		actor := opActor(r)
		if actor == "" {
			authError(w, http.StatusUnauthorized, "verified actor required")
			return
		}
		var e publication.AuditEvent
		if err := json.NewDecoder(r.Body).Decode(&e); err != nil {
			pubBadRequest(w, "invalid json")
			return
		}
		if e.Action == "" {
			pubBadRequest(w, "action required")
			return
		}
		e.ID = uuid.New()
		e.Actor = actor
		e.CreatedAt = d.Now()
		if err := d.Audit.Record(r.Context(), e); err != nil {
			pubError(w, err)
			return
		}
		pubJSON(w, map[string]any{"event": e})
	})
	mux.HandleFunc("GET /v1/audit/events", func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		events, err := d.Audit.List(r.Context(), ports.AuditFilter{
			Actor:      q.Get("actor"),
			Action:     q.Get("action"),
			EntityType: q.Get("entity_type"),
			EntityID:   q.Get("entity_id"),
			Limit:      pubLimit(r, 100),
		})
		if err != nil {
			pubError(w, err)
			return
		}
		pubJSON(w, map[string]any{"events": events})
	})

	// V1.1 — trend DLQ: inspect + replay (never silently discarded).
	if d.DLQ != nil {
		mux.HandleFunc("GET /v1/dlq/trends", func(w http.ResponseWriter, r *http.Request) {
			entries, err := d.DLQ.List(r.Context(), int64(pubLimit(r, 100)))
			if err != nil {
				pubError(w, err)
				return
			}
			depth, _ := d.DLQ.Depth(r.Context())
			pubJSON(w, map[string]any{"entries": entries, "depth": depth})
		})
		mux.HandleFunc("GET /v1/dlq/trends/{id}", func(w http.ResponseWriter, r *http.Request) {
			e, err := d.DLQ.Get(r.Context(), r.PathValue("id"))
			if err != nil {
				pubNotFound(w)
				return
			}
			pubJSON(w, map[string]any{"entry": e})
		})
		mux.HandleFunc("POST /v1/dlq/trends/{id}/replay", func(w http.ResponseWriter, r *http.Request) {
			actor := opActor(r)
			if actor == "" {
				authError(w, http.StatusUnauthorized, "verified actor required")
				return
			}
			id := r.PathValue("id")
			if err := d.DLQ.Replay(r.Context(), id); err != nil {
				pubError(w, err)
				return
			}
			recordAudit(r, d, actor, "dlq.replay", "dlq_entry", id, nil,
				map[string]any{"replayed": true}, "")
			pubJSON(w, map[string]any{"replayed": id})
		})
	}
}

func publisherUnavailableReason(d ConsoleOpsDeps) string {
	if d.PublisherUnavailableReason != "" {
		return d.PublisherUnavailableReason
	}
	return "publication engine unavailable"
}

func recordAudit(
	r *http.Request, d ConsoleOpsDeps,
	actor, action, entityType, entityID string,
	before, after map[string]any, reason string,
) {
	if d.Audit == nil {
		return
	}
	if err := d.Audit.Record(r.Context(), publication.AuditEvent{
		ID: uuid.New(), Actor: actor, Action: action,
		EntityType: entityType, EntityID: entityID,
		Before: before, After: after, Reason: reason,
		CreatedAt: d.Now(),
	}); err != nil {
		d.Logger.Error().Err(err).Str("action", action).Msg("audit_record_failed")
	}
}

// capHighlights trims reviewer evidence to the publishable highlight
// budget (keep in sync with draftvalidator maxHighlights).
func capHighlights(evidence []string) []string {
	const max = 3
	if len(evidence) <= max {
		return evidence
	}
	return evidence[:max]
}

func ticketSnapshot(t publication.Ticket) map[string]any {
	return map[string]any{
		"status":            string(t.Status),
		"suggested_title":   t.SuggestedTitle,
		"suggested_summary": t.SuggestedSummary,
		"evidence":          t.Evidence,
		"reviewed_by":       t.ReviewedBy,
		"published_by":      t.PublishedBy,
	}
}

func personaSnapshot(p persona.AgentPersona) map[string]any {
	return map[string]any{
		"style": p.Style, "tone": p.Tone, "expertise": p.Expertise,
		"restrictions": p.Restrictions, "posting_behavior": p.PostingBehavior,
	}
}

func actionOf(status string, edited bool) string {
	if status != "" {
		return "transition_" + status
	}
	if edited {
		return "edit"
	}
	return "touch"
}

func pubBadRequest(w http.ResponseWriter, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusBadRequest)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": msg})
}

func pubNotFound(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusNotFound)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": "not_found"})
}

func pubUnavailable(w http.ResponseWriter, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusServiceUnavailable)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": msg})
}
