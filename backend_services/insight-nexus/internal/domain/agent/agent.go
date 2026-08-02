// Package agent — the Nexus agent aggregate.
//
// An agent is a configurable communication persona that consumes a
// slice of Atlas's trend taxonomy and produces structured drafts.
// Agents are PERSISTED + EDITABLE: nothing about them is hardcoded —
// the five official agents (Ninja, Pulse, Oracle, Sentinel, Echo) are
// database seeds, and admin APIs can create/disable/edit any agent.
//
// Architectural rule: agents NEVER hold intelligence logic. They route
// + present Atlas's evaluated output; Atlas alone decides what matters.
package agent

import (
	"errors"
	"strings"
	"time"

	"github.com/google/uuid"
)

var (
	ErrMissingName      = errors.New("agent: name required")
	ErrMissingSpecialty = errors.New("agent: specialty required")
	ErrNoTrendTypes     = errors.New("agent: at least one trend type or category required")
)

// Agent is the persisted, editable communication persona.
type Agent struct {
	ID        uuid.UUID
	Name      string // unique slug ("ninja", "pulse", …)
	Avatar    string // URL or asset key
	Bio       string
	Active    bool
	Specialty string

	// TrendTypes — which trend types AND/OR trend categories this
	// agent consumes (matched against the Contract V3 trend_type and
	// category fields). DB-driven: routing changes are config edits,
	// never code changes.
	TrendTypes []string

	// PostingRules — opaque JSON bag the future publishing sprints
	// interpret (cadence caps, tier minimums, quiet hours, …).
	PostingRules map[string]any

	// RAGSources — references the future content sprints may consult.
	// Stored, not used in this sprint.
	RAGSources []string

	// SystemContext — the persona context future sprints hand to the
	// content layer. Stored + editable, NEVER executed here (no LLM in
	// this sprint).
	SystemContext string

	CreatedAt time.Time
	UpdatedAt time.Time
}

// Validate enforces the aggregate invariants.
func (a Agent) Validate() error {
	if strings.TrimSpace(a.Name) == "" {
		return ErrMissingName
	}
	if strings.TrimSpace(a.Specialty) == "" {
		return ErrMissingSpecialty
	}
	if len(a.TrendTypes) == 0 {
		return ErrNoTrendTypes
	}
	return nil
}

// Consumes reports whether the agent's configuration matches a trend's
// type or category (both are accepted in TrendTypes — the matching is
// case-insensitive on the stable wire slugs).
func (a Agent) Consumes(trendType, category string) bool {
	for _, t := range a.TrendTypes {
		if strings.EqualFold(t, trendType) || strings.EqualFold(t, category) {
			return true
		}
	}
	return false
}

// QueueName — the per-agent publishing queue key. Derived from the
// agent's slug so admin-created agents get queues automatically.
func (a Agent) QueueName() string {
	return "insight:queue:nexus:" + strings.ToLower(strings.TrimSpace(a.Name))
}
