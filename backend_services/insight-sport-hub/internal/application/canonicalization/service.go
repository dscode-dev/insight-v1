// Package canonicalization — CanonicalizationService.
//
// Merges N RawSportsEvents that share an Identity into one
// CanonicalSportsEvent. The merge strategy in Sprint 1 is
// deliberately simple:
//
//   - group raws by Identity (the orchestrator typically passes
//     raws already filtered to one identity; the service handles
//     the multi-identity case too)
//   - pick the merged payload via "latest observed_at wins" across
//     authoritative (non-candidate) raws; if all raws are candidate,
//     latest among them wins
//   - preserve EVERY contributing SourceRef in the canonical's
//     sources slice — lineage rule
//   - status assignment + confidence are NOT done here — the
//     orchestrator drives those services in sequence
//
// Future iterations can introduce a per-event-type merge plug-in
// (e.g. odds need numeric weighted average; lineups need
// last-writer-wins; goals need ordered union). The current shape
// returns a "merge plan" struct that those plug-ins can hook into.
package canonicalization

import (
	"errors"
	"fmt"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
)

type Service struct{}

func New() *Service { return &Service{} }

var ErrEmptyRawSet = errors.New("canonicalization: empty raw set")

// Build constructs a fresh CanonicalSportsEvent from a set of raws
// sharing one Identity. Returns ErrEmptyRawSet when called with no
// raws.
//
// All raws MUST share the same Identity — the orchestrator filters
// upstream. We assert defensively and return an error rather than
// silently picking one.
//
// The new canonical's status is StatusCandidate per the domain
// constructor's default; the orchestrator promotes via the
// ConflictDetectionService's result.
func (s *Service) Build(
	canonicalID uuid.UUID,
	raws []*event.RawSportsEvent,
	confidence float64,
) (*event.CanonicalSportsEvent, error) {
	if len(raws) == 0 {
		return nil, ErrEmptyRawSet
	}

	identity := identityOf(raws[0])
	for _, r := range raws[1:] {
		if !identityOf(r).Equal(identity) {
			return nil, fmt.Errorf(
				"canonicalization: raws span multiple identities (%v vs %v)",
				identity, identityOf(r),
			)
		}
	}

	merged := mergePayload(raws)
	sources := collectSources(raws)

	// occurred_at = latest observed_at across the raws — this is the
	// best approximation of "when did this thing actually happen"
	// when raws don't carry an explicit occurred_at field.
	occurredAt := raws[0].ObservedAt()
	for _, r := range raws[1:] {
		if r.ObservedAt().After(occurredAt) {
			occurredAt = r.ObservedAt()
		}
	}

	return event.NewCanonical(
		canonicalID,
		identity,
		"", // season unknown at this layer in Sprint 1 — Sprint 2 wires the match catalogue
		occurredAt,
		merged,
		sources,
		confidence,
	)
}

// MergeInto applies a new batch of raws to an EXISTING canonical:
// payload is recomputed from the union of existing canonical's
// payload + the new raws, every new SourceRef is appended (de-duped
// via CanonicalSportsEvent.AddSource), and the confidence is
// re-applied by the caller.
//
// The orchestrator uses Build for the first canonical of an
// identity + MergeInto for subsequent raws.
func (s *Service) MergeInto(
	existing *event.CanonicalSportsEvent,
	newRaws []*event.RawSportsEvent,
	confidence float64,
) error {
	if len(newRaws) == 0 {
		return nil
	}
	for _, r := range newRaws {
		if !identityOf(r).Equal(existing.Identity()) {
			return fmt.Errorf(
				"canonicalization: raw %s does not match canonical identity",
				r.RawEventID(),
			)
		}
	}

	// Re-merge payload from canonical's current payload + raws.
	// Wraps the existing canonical's payload as the "earliest"
	// pseudo-raw via mergePayloadFromInputs.
	merged := mergePayloadFromInputs(existing.Payload(), existing.OccurredAt(), newRaws)
	if err := existing.ReplacePayload(merged); err != nil {
		return err
	}

	for _, r := range newRaws {
		if err := existing.AddSource(r.Source()); err != nil {
			return err
		}
	}
	return existing.SetConfidence(confidence)
}

// ---- helpers ----

func identityOf(r *event.RawSportsEvent) event.Identity {
	return event.Identity{
		Sport:         r.Sport(),
		CompetitionID: r.CompetitionID(),
		MatchID:       deriveMatchID(r),
		EventType:     r.EventType(),
	}
}

// deriveMatchID — Sprint 1 placeholder: until the match catalogue
// ships in Sprint 2, we treat the external_match_id as a stable id
// and namespace it via UUIDv5 over a fixed namespace. This produces
// deterministic match_id values per (source_id, external_match_id)
// — collisions across providers (when two providers refer to the
// same real-world match with different external ids) get reconciled
// in Sprint 2 via the catalogue.
//
// IMPORTANT: this is NOT the final match identity strategy. It's
// scoped to Sprint 1 so the canonical contracts work end-to-end
// against real raws. Documented as a TODO in the README.
var matchIDNamespace = uuid.MustParse("8e2e3f9c-3d23-4ad1-9c1e-2b91a1f9c6f0")

func deriveMatchID(r *event.RawSportsEvent) uuid.UUID {
	key := r.Source().SourceID + "::" + r.ExternalMatchID()
	return uuid.NewSHA1(matchIDNamespace, []byte(key))
}

// mergePayload — last-observed-wins across raws. Authoritative raws
// take priority; candidate raws only contribute keys that no
// authoritative raw set.
func mergePayload(raws []*event.RawSportsEvent) map[string]any {
	auth := make([]*event.RawSportsEvent, 0, len(raws))
	cand := make([]*event.RawSportsEvent, 0, len(raws))
	for _, r := range raws {
		if r.Source().IsCandidate() {
			cand = append(cand, r)
		} else {
			auth = append(auth, r)
		}
	}
	// If everything is candidate, candidates ARE the input.
	if len(auth) == 0 {
		auth = cand
		cand = nil
	}

	merged := map[string]any{}
	// Authoritative: apply in observed_at order so latest wins.
	sortByObservedAtAsc(auth)
	for _, r := range auth {
		for k, v := range r.Payload() {
			merged[k] = v
		}
	}
	// Candidate fill — only keys not yet present.
	sortByObservedAtAsc(cand)
	for _, r := range cand {
		for k, v := range r.Payload() {
			if _, ok := merged[k]; !ok {
				merged[k] = v
			}
		}
	}
	return merged
}

// mergePayloadFromInputs — variant for MergeInto: prepends the
// existing canonical's payload as a synthetic "earliest observation"
// so new authoritative raws can overwrite it.
func mergePayloadFromInputs(
	existing map[string]any,
	_ /* existingOccurredAt */ interface{},
	newRaws []*event.RawSportsEvent,
) map[string]any {
	// Start with existing payload (no provenance — it already came
	// from a prior merge).
	out := map[string]any{}
	for k, v := range existing {
		out[k] = v
	}
	// Apply new raws, authoritative first, latest wins per key.
	merged := mergePayload(newRaws)
	for k, v := range merged {
		out[k] = v
	}
	return out
}

// collectSources extracts the SourceRef from every raw. De-dup is
// done at the canonical level (AddSource is idempotent on
// (source_id, observed_at)).
func collectSources(raws []*event.RawSportsEvent) []source.SourceRef {
	out := make([]source.SourceRef, 0, len(raws))
	for _, r := range raws {
		out = append(out, r.Source())
	}
	return out
}

// sortByObservedAtAsc — small in-place insertion sort. Input
// slices are small (typically <10 raws per merge); avoiding the
// sort package keeps allocations + imports minimal.
func sortByObservedAtAsc(rs []*event.RawSportsEvent) {
	for i := 1; i < len(rs); i++ {
		j := i
		for j > 0 && rs[j].ObservedAt().Before(rs[j-1].ObservedAt()) {
			rs[j], rs[j-1] = rs[j-1], rs[j]
			j--
		}
	}
}
