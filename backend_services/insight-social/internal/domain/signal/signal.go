// Package signal holds the Signal aggregate.
//
// A Signal is a community/expert/model assertion about a match
// outcome. Its persistence is shared between:
//   - Postgres (signals table — source of truth)
//   - Redis Streams (insight:stream:human_signal:{partition} — the
//     fan-out channel consumed by the gateway broker for SSE)
//
// Identity:
//
//	The DB column `signals.id` is BIGSERIAL (legacy schema). The
//	API surface exposes it as a string — `strconv.FormatInt(id, 10)`.
//	No UUID v5 synthesis here (unlike discussion_messages) because
//	signals are looked up by id more often (validation jobs reference
//	them by their numeric pk) and we want round-trips to stay cheap.
package signal

import (
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
)

const (
	maxLabelLen = 64
	maxBodyLen  = 2048
)

type Signal struct {
	id         int64 // 0 until persisted (BIGSERIAL assigns on insert)
	authorID   uuid.UUID
	matchID    uuid.UUID
	source     Source
	label      string
	body       string
	confidence float64
	state      State
	ts         time.Time
}

// New constructs a fresh Signal. The id stays 0 until the repo
// assigns one via RETURNING; callers MUST call SetID after Insert.
//
// State is always Pending on creation — evolution happens via a
// downstream evaluation job that emits reputation_events.
func New(authorID, matchID uuid.UUID, source Source, label, body string, confidence float64) (*Signal, error) {
	label = strings.TrimSpace(label)
	body = strings.TrimSpace(body)

	if l := len(label); l < 1 || l > maxLabelLen {
		return nil, fmt.Errorf("%w: length %d out of 1..%d", ErrInvalidLabel, l, maxLabelLen)
	}
	if l := len(body); l > maxBodyLen {
		return nil, fmt.Errorf("%w: length %d > %d", ErrInvalidBody, l, maxBodyLen)
	}
	if confidence < 0 || confidence > 1 {
		return nil, fmt.Errorf("%w: %.4f", ErrInvalidConfidence, confidence)
	}
	if source == SourceUnspecified {
		source = SourceCommunity
	}

	return &Signal{
		authorID:   authorID,
		matchID:    matchID,
		source:     source,
		label:      label,
		body:       body,
		confidence: confidence,
		state:      StatePending,
		ts:         time.Now().UTC(),
	}, nil
}

// Reconstitute rebuilds from persisted state (with id already known).
func Reconstitute(id int64, authorID, matchID uuid.UUID, source Source,
	label, body string, confidence float64, state State, ts time.Time) *Signal {
	return &Signal{
		id:         id,
		authorID:   authorID,
		matchID:    matchID,
		source:     source,
		label:      label,
		body:       body,
		confidence: confidence,
		state:      state,
		ts:         ts,
	}
}

func (s *Signal) ID() int64           { return s.id }
func (s *Signal) AuthorID() uuid.UUID { return s.authorID }
func (s *Signal) MatchID() uuid.UUID  { return s.matchID }
func (s *Signal) Source() Source      { return s.source }
func (s *Signal) Label() string       { return s.label }
func (s *Signal) Body() string        { return s.body }
func (s *Signal) Confidence() float64 { return s.confidence }
func (s *Signal) State() State        { return s.state }
func (s *Signal) Ts() time.Time       { return s.ts }

// SetID is called by the repo after the BIGSERIAL id is assigned via
// INSERT ... RETURNING. The aggregate's id is immutable after this.
func (s *Signal) SetID(id int64) {
	if s.id != 0 {
		return // idempotent: re-setting same id is harmless; never overwrite
	}
	s.id = id
}
