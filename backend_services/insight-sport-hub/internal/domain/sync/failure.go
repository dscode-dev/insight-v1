// SyncJobFailure — Sprint 4 dead-letter contract.
//
// Records a terminal failure for a SyncJob whose retry chain has
// been exhausted (or whose failure type is non-retryable). The
// queue's Fail() method constructs this and hands it to the
// DeadLetterStore port.
//
// Sprint 4 ships the contract + a NOOP store. Sprint 5 lands a
// Postgres-backed store + admin tooling to inspect / replay. The
// contract here is what both will share.
package sync

import (
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
)

// SyncJobFailure is the persisted-failure shape. All fields are
// required; FailedAt is normalized to UTC at construction.
type SyncJobFailure struct {
	JobID         JobID
	ProviderID    string
	CompetitionID uuid.UUID
	SyncType      SyncType
	Reason        string
	Attempts      int
	FailedAt      time.Time
}

var (
	ErrFailureMissingReason   = errors.New("syncjobfailure: reason required")
	ErrFailureMissingProvider = errors.New("syncjobfailure: provider_id required")
)

// NewSyncJobFailure validates the contract. Caller passes an
// already-failed job + the reason summary; the helper bundles the
// fields and stamps FailedAt.UTC().
func NewSyncJobFailure(job SyncJob, reason string, at time.Time) (SyncJobFailure, error) {
	if job.ProviderID == "" {
		return SyncJobFailure{}, ErrFailureMissingProvider
	}
	if reason == "" {
		return SyncJobFailure{}, ErrFailureMissingReason
	}
	if at.IsZero() {
		return SyncJobFailure{}, fmt.Errorf("syncjobfailure: failed_at required")
	}
	return SyncJobFailure{
		JobID:         job.JobID,
		ProviderID:    job.ProviderID,
		CompetitionID: job.CompetitionID,
		SyncType:      job.SyncType,
		Reason:        reason,
		Attempts:      job.CurrentAttempt,
		FailedAt:      at.UTC(),
	}, nil
}
