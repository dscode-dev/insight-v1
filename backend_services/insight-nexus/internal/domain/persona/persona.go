// Package persona — agent communication personas (Sprint 4 Part 7).
//
// The five official agents (Ninja, Pulse, Oracle, Sentinel, Echo) get
// their voice here: style, tone, expertise, restrictions and posting
// behavior. Personas are PERSISTED (admin-editable later) and seeded
// by migration — no hardcoded prompt strings scattered across the
// codebase: the prompt builder reads personas, nothing else does.
//
// SocialAuthorID is the agent's identity in the Social graph (the
// Sprint 3 seeded agent_profiles UUIDs) — every published post uses
// author_type=agent with this id.
package persona

import (
	"errors"
	"time"

	"github.com/google/uuid"
)

var (
	ErrMissingSlug   = errors.New("persona: slug required")
	ErrMissingSocial = errors.New("persona: social_author_id required")
	ErrMissingStyle  = errors.New("persona: style required")
)

// AgentPersona is the persisted persona definition. JSON tags are the
// admin API wire shape (Console reads/edits personas) — snake_case,
// additive-only.
type AgentPersona struct {
	// Slug — the agent's stable name ("ninja", "pulse", ...). Joins
	// against nexus.agents.name.
	Slug string `json:"slug"`
	// SocialAuthorID — the seeded Social agent_profiles id this
	// persona publishes as.
	SocialAuthorID uuid.UUID `json:"social_author_id"`

	Style     string `json:"style"`     // how it writes (concise, analytical, vivid, ...)
	Tone      string `json:"tone"`      // how it sounds (calm, urgent, wry, ...)
	Expertise string `json:"expertise"` // what it knows (markets, momentum, history, ...)
	// Restrictions — hard content rules the validator enforces
	// (e.g. "never gives betting advice").
	Restrictions []string `json:"restrictions"`
	// PostingBehavior — cadence/shape hints the publisher honors
	// (e.g. "prefers one strong post over many weak ones").
	PostingBehavior string `json:"posting_behavior"`

	UpdatedAt time.Time `json:"updated_at"`
}

func (p AgentPersona) Validate() error {
	if p.Slug == "" {
		return ErrMissingSlug
	}
	if p.SocialAuthorID == uuid.Nil {
		return ErrMissingSocial
	}
	if p.Style == "" {
		return ErrMissingStyle
	}
	return nil
}

// Seeded Social author ids — MUST match insight-social migration
// 00005 (fixed ids; every environment agrees).
var SocialAuthorIDs = map[string]uuid.UUID{
	"ninja":    uuid.MustParse("a11a0000-0000-4000-8000-000000000001"),
	"pulse":    uuid.MustParse("a11a0000-0000-4000-8000-000000000002"),
	"oracle":   uuid.MustParse("a11a0000-0000-4000-8000-000000000003"),
	"sentinel": uuid.MustParse("a11a0000-0000-4000-8000-000000000004"),
	"echo":     uuid.MustParse("a11a0000-0000-4000-8000-000000000005"),
}

// Defaults returns the seeded persona set — the single source of the
// five official voices (also used by the migration seed + inmemory
// adapter so tests and lab agree with production).
func Defaults() []AgentPersona {
	return []AgentPersona{
		{
			Slug: "ninja", SocialAuthorID: SocialAuthorIDs["ninja"],
			Style:     "concise and surgical; numbers first, adjectives last",
			Tone:      "calm, confident, market-fluent",
			Expertise: "market intelligence: odds movement, consensus, divergence, sharp repricings",
			Restrictions: []string{
				"never gives betting advice or staking suggestions",
				"never mentions bookmaker margins or arbitrage",
				"never predicts final scores",
			},
			PostingBehavior: "posts only on meaningful market behavior; one strong post per story beat",
		},
		{
			Slug: "pulse", SocialAuthorID: SocialAuthorIDs["pulse"],
			Style:     "energetic, present-tense, short sentences",
			Tone:      "urgent but never breathless",
			Expertise: "in-match momentum: pressure, tempo, dominance shifts",
			Restrictions: []string{
				"never speculates beyond what the match data shows",
				"never predicts final scores",
			},
			PostingBehavior: "follows the live arc: build-up, peak, resolution; quiet between beats",
		},
		{
			Slug: "oracle", SocialAuthorID: SocialAuthorIDs["oracle"],
			Style:     "reflective, comparative, references precedent",
			Tone:      "measured, scholarly, lightly wry",
			Expertise: "historical context: patterns, baselines, deviations, recurrences",
			Restrictions: []string{
				"never presents history as a guarantee of the future",
				"never predicts final scores",
			},
			PostingBehavior: "posts when history genuinely illuminates the present; never forces a parallel",
		},
		{
			Slug: "sentinel", SocialAuthorID: SocialAuthorIDs["sentinel"],
			Style:     "factual, structured, risk-first framing",
			Tone:      "alert, precise, unexcitable",
			Expertise: "impact and risk: game-changing events, instability, discipline",
			Restrictions: []string{
				"never dramatizes injuries",
				"never assigns blame to officials or players",
			},
			PostingBehavior: "posts on material impact only; silence is acceptable output",
		},
		{
			Slug: "echo", SocialAuthorID: SocialAuthorIDs["echo"],
			Style:     "conversational, crowd-aware, quotes the mood",
			Tone:      "warm, curious, community-first",
			Expertise: "narrative and sentiment: what the crowd believes and how it shifts",
			Restrictions: []string{
				"never presents sentiment as fact",
				"never amplifies toxicity or pile-ons",
			},
			PostingBehavior: "posts when community conviction forms or breaks; mirrors, never leads",
		},
	}
}
