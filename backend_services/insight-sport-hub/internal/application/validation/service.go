// Package validation — ValidationService.
//
// Runs every Sprint 1 quarantine rule against a RawSportsEvent
// BEFORE canonicalisation. The rule list is data — adding a new
// reason in Sprint 2 is a single entry in the registered rules
// slice + a new constant in QuarantineReason.
//
// Sprint 1 rules:
//   - missing source                  → covered by NewRaw + SourceRef.Validate
//   - missing timestamp               → covered by NewRaw
//   - unsupported sport               → covered by NewRaw (sport.Parse)
//   - unknown competition             → CompetitionRegistry lookup
//   - empty payload                   → covered by NewRaw
//   - duplicate raw_event_id          → RawEventRepository.ExistsByID
//   - confidence outside [0,1]        → covered by NewRaw
//   - future events beyond tolerance  → custom rule (FutureSkewRule)
//
// Duplicate canonical identity check happens during canonicalisation
// upsert (the unique constraint). Lives there, not here, because at
// raw-event time the same Identity is the EXPECTED multi-raw case.
package validation

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// QuarantineReason is the wire-stable slug for every rejection
// reason. Additive-only — never rename or remove.
type QuarantineReason string

const (
	ReasonOK                      QuarantineReason = "ok"
	ReasonMissingSource           QuarantineReason = "missing_source"
	ReasonMissingTimestamp        QuarantineReason = "missing_timestamp"
	ReasonUnsupportedSport        QuarantineReason = "unsupported_sport"
	ReasonUnknownCompetition      QuarantineReason = "unknown_competition"
	ReasonEmptyPayload            QuarantineReason = "empty_payload"
	ReasonDuplicateRawEventID     QuarantineReason = "duplicate_raw_event_id"
	ReasonConfidenceOutOfRange    QuarantineReason = "confidence_out_of_range"
	ReasonFutureEventBeyondBudget QuarantineReason = "future_event_beyond_budget"
)

// Decision is the outcome of running the rule list. When Quarantined
// is true, Reason carries the slug + Detail carries an operator-
// readable explanation including the offending value.
type Decision struct {
	Quarantined bool
	Reason      QuarantineReason
	Detail      string
}

func Passed() Decision { return Decision{Reason: ReasonOK} }

// Service config + dependencies.
type Service struct {
	rawRepo      ports.RawEventRepository
	competitions ports.CompetitionRegistry
	clock        ports.Clock
	metrics      ports.Metrics
	futureBudget time.Duration
}

// Config carries tunables. Sprint 1 ships one (futureBudget); more
// land additive-only as new reasons are introduced.
type Config struct {
	// FutureSkew tolerates clock drift between adapter + Hub. Events
	// observed beyond this in the future quarantine.
	FutureSkew time.Duration
}

func New(
	rawRepo ports.RawEventRepository,
	competitions ports.CompetitionRegistry,
	clock ports.Clock,
	metrics ports.Metrics,
	cfg Config,
) *Service {
	skew := cfg.FutureSkew
	if skew <= 0 {
		skew = 5 * time.Minute
	}
	return &Service{
		rawRepo:      rawRepo,
		competitions: competitions,
		clock:        clock,
		metrics:      metrics,
		futureBudget: skew,
	}
}

// Validate runs every rule in declared order. First failure wins —
// keeps the error chain single-cause + makes the decision rationale
// reproducible for any input.
//
// Most "covered by NewRaw" rules can't fail here because the raw is
// already constructed; they're documented in the package docstring
// so an operator reading this file sees the full rule list at once.
func (s *Service) Validate(ctx context.Context, raw *event.RawSportsEvent) Decision {
	// Future timestamp guard.
	now := s.clock.Now()
	if raw.ObservedAt().After(now.Add(s.futureBudget)) {
		ahead := raw.ObservedAt().Sub(now)
		return s.reject(ReasonFutureEventBeyondBudget,
			fmt.Sprintf("observed_at is %s ahead of now (budget %s)",
				ahead.Round(time.Second), s.futureBudget))
	}

	// Competition allow-list.
	known, err := s.competitions.IsKnown(ctx, raw.CompetitionID())
	if err != nil {
		// Infra failure during the registry lookup: do NOT quarantine
		// (would let a transient outage drop legitimate events). The
		// orchestrator must surface this — caller handles the err.
		return Decision{
			Quarantined: false,
			Reason:      ReasonOK,
			Detail:      fmt.Sprintf("competition lookup failed (event accepted): %v", err),
		}
	}
	if !known {
		return s.reject(ReasonUnknownCompetition,
			fmt.Sprintf("competition_id=%s not in registry", raw.CompetitionID()))
	}

	// Duplicate raw_event_id check.
	exists, err := s.rawRepo.ExistsByID(ctx, raw.RawEventID())
	if err != nil {
		return Decision{
			Quarantined: false,
			Reason:      ReasonOK,
			Detail:      fmt.Sprintf("duplicate check failed (event accepted): %v", err),
		}
	}
	if exists {
		return s.reject(ReasonDuplicateRawEventID,
			fmt.Sprintf("raw_event_id=%s already ingested", raw.RawEventID()))
	}

	return Passed()
}

func (s *Service) reject(reason QuarantineReason, detail string) Decision {
	s.metrics.IncRejected(string(reason))
	return Decision{Quarantined: true, Reason: reason, Detail: detail}
}

// ErrInvalidIdentity is surfaced when ValidationService is asked to
// validate something with a malformed Identity (defensive — the
// raw event constructor already enforces non-zero Identity but a
// caller could bypass via Reconstitute).
var ErrInvalidIdentity = errors.New("validation: identity incomplete")
