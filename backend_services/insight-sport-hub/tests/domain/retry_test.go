// Retry contract tests — Sprint 4 domain.
//
// Validates the SyncJob retry fields + the exponential backoff
// helper + the SyncJobFailure DLQ contract. These types are the
// language the queue adapter speaks; pinning them here prevents
// silent regressions when Sprint 5 wires Postgres-backed DLQ
// persistence.
package domain_test

import (
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"

	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
)

func mustJob(t *testing.T) syncdom.SyncJob {
	t.Helper()
	j, err := syncdom.NewSyncJob(
		syncdom.NewJobID(), "p", uuid.New(),
		syncdom.TypeFixtures, syncdom.PriorityNormal,
		time.Now(), nil,
	)
	if err != nil {
		t.Fatalf("build job: %v", err)
	}
	return j
}

func TestNewSyncJobDefaultsRetryFields(t *testing.T) {
	j := mustJob(t)
	if j.MaxAttempts != syncdom.DefaultMaxAttempts {
		t.Errorf("MaxAttempts = %d, want %d", j.MaxAttempts, syncdom.DefaultMaxAttempts)
	}
	if j.CurrentAttempt != 0 {
		t.Errorf("CurrentAttempt must default to 0, got %d", j.CurrentAttempt)
	}
	if !j.RetryAfter.IsZero() {
		t.Errorf("RetryAfter must be zero on first emit, got %v", j.RetryAfter)
	}
}

func TestNextRetryDelayExponential(t *testing.T) {
	base := syncdom.BaseRetryDelay
	cases := map[int]time.Duration{
		1: base,
		2: base * 2,
		3: base * 4,
		4: base * 8,
	}
	for attempt, want := range cases {
		got := syncdom.NextRetryDelay(attempt)
		if got != want {
			t.Errorf("NextRetryDelay(%d) = %v, want %v", attempt, got, want)
		}
	}
}

func TestNextRetryDelayClampsLowAndHigh(t *testing.T) {
	if got := syncdom.NextRetryDelay(0); got != syncdom.BaseRetryDelay {
		t.Errorf("attempt 0 should clamp to base; got %v", got)
	}
	if got := syncdom.NextRetryDelay(100); got <= 0 {
		t.Errorf("attempt 100 should not overflow; got %v", got)
	}
}

func TestPreparedForRetryBumpsAttemptAndStampsRetryAfter(t *testing.T) {
	j := mustJob(t)
	now := time.Date(2026, 6, 1, 12, 0, 0, 0, time.UTC)
	r := j.PreparedForRetry(now)
	if r.CurrentAttempt != 1 {
		t.Errorf("attempt = %d, want 1", r.CurrentAttempt)
	}
	if !r.RetryAfter.Equal(now.Add(syncdom.BaseRetryDelay)) {
		t.Errorf("RetryAfter = %v, want %v", r.RetryAfter, now.Add(syncdom.BaseRetryDelay))
	}
	// Original must not be mutated — PreparedForRetry returns a copy.
	if j.CurrentAttempt != 0 {
		t.Errorf("original CurrentAttempt mutated: %d", j.CurrentAttempt)
	}
}

func TestAttemptsExhausted(t *testing.T) {
	j := mustJob(t)
	if j.AttemptsExhausted() {
		t.Error("fresh job should not be exhausted")
	}
	j.CurrentAttempt = j.MaxAttempts
	if !j.AttemptsExhausted() {
		t.Error("job at MaxAttempts must report exhausted")
	}
}

// ---------------------------------------------------------------------------
// SyncJobFailure
// ---------------------------------------------------------------------------

func TestNewSyncJobFailureHappyPath(t *testing.T) {
	j := mustJob(t)
	j.CurrentAttempt = 3
	at := time.Now()
	f, err := syncdom.NewSyncJobFailure(j, "fetch_failed", at)
	if err != nil {
		t.Fatalf("build failure: %v", err)
	}
	if f.Reason != "fetch_failed" || f.Attempts != 3 {
		t.Errorf("failure shape wrong: %+v", f)
	}
	if !f.FailedAt.Equal(at.UTC()) {
		t.Errorf("FailedAt not UTC-coerced: %v", f.FailedAt)
	}
}

func TestNewSyncJobFailureRejectsMissingReason(t *testing.T) {
	j := mustJob(t)
	_, err := syncdom.NewSyncJobFailure(j, "", time.Now())
	if !errors.Is(err, syncdom.ErrFailureMissingReason) {
		t.Errorf("expected ErrFailureMissingReason, got %v", err)
	}
}

func TestNewSyncJobFailureRejectsMissingProvider(t *testing.T) {
	j := mustJob(t)
	j.ProviderID = ""
	_, err := syncdom.NewSyncJobFailure(j, "x", time.Now())
	if !errors.Is(err, syncdom.ErrFailureMissingProvider) {
		t.Errorf("expected ErrFailureMissingProvider, got %v", err)
	}
}
