// Sync contracts — Sprint 2.1.
//
// SyncJob, RateLimitPolicy, PollPolicy are PURE CONTRACTS at this
// stage; no scheduler reads them. The tests below pin the invariants
// so a future scheduler can rely on them.
package domain_test

import (
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"

	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
)

// ---------------------------------------------------------------------------
// SyncType
// ---------------------------------------------------------------------------

func TestParseSyncTypeAcceptsKnown(t *testing.T) {
	for _, st := range syncdom.All() {
		got, err := syncdom.ParseSyncType(string(st))
		if err != nil {
			t.Errorf("ParseSyncType(%q) err: %v", st, err)
		}
		if got != st {
			t.Errorf("ParseSyncType(%q) = %q", st, got)
		}
	}
}

func TestParseSyncTypeRejectsUnknown(t *testing.T) {
	_, err := syncdom.ParseSyncType("commentary")
	if !errors.Is(err, syncdom.ErrUnknownSyncType) {
		t.Errorf("expected ErrUnknownSyncType, got %v", err)
	}
}

// ---------------------------------------------------------------------------
// SyncJob
// ---------------------------------------------------------------------------

func TestNewSyncJobHappyPath(t *testing.T) {
	id := syncdom.NewJobID()
	cid := uuid.New()
	at := time.Now().Add(5 * time.Minute)
	job, err := syncdom.NewSyncJob(
		id, "api_football", cid,
		syncdom.TypeFixtures, syncdom.PriorityNormal,
		at, map[string]string{"trace": "abc"},
	)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if job.JobID != id {
		t.Error("job id lost")
	}
	if job.ProviderID != "api_football" {
		t.Errorf("provider id lost: %q", job.ProviderID)
	}
	if job.CompetitionID != cid {
		t.Error("competition id lost")
	}
	if job.SyncType != syncdom.TypeFixtures {
		t.Errorf("sync_type lost: %q", job.SyncType)
	}
	if job.Priority != syncdom.PriorityNormal {
		t.Errorf("priority lost: %d", job.Priority)
	}
	if !job.ScheduledAt.Equal(at.UTC()) {
		t.Errorf("scheduled_at not UTC-coerced: %v", job.ScheduledAt)
	}
	if job.Metadata["trace"] != "abc" {
		t.Error("metadata lost")
	}
}

func TestNewSyncJobRejectsMissingFields(t *testing.T) {
	id := syncdom.NewJobID()
	at := time.Now().Add(time.Minute)

	if _, err := syncdom.NewSyncJob(id, "", uuid.New(),
		syncdom.TypeFixtures, syncdom.PriorityNormal, at, nil,
	); !errors.Is(err, syncdom.ErrJobMissingProvider) {
		t.Errorf("expected ErrJobMissingProvider, got %v", err)
	}
	if _, err := syncdom.NewSyncJob(id, "p", uuid.Nil,
		syncdom.TypeFixtures, syncdom.PriorityNormal, at, nil,
	); !errors.Is(err, syncdom.ErrJobMissingCompetition) {
		t.Errorf("expected ErrJobMissingCompetition, got %v", err)
	}
	if _, err := syncdom.NewSyncJob(id, "p", uuid.New(),
		syncdom.TypeFixtures, syncdom.PriorityNormal, time.Time{}, nil,
	); !errors.Is(err, syncdom.ErrJobMissingSchedule) {
		t.Errorf("expected ErrJobMissingSchedule, got %v", err)
	}
	if _, err := syncdom.NewSyncJob(id, "p", uuid.New(),
		syncdom.SyncType("bogus"), syncdom.PriorityNormal, at, nil,
	); !errors.Is(err, syncdom.ErrUnknownSyncType) {
		t.Errorf("expected ErrUnknownSyncType, got %v", err)
	}
}

func TestNewSyncJobMetadataDefensiveCopy(t *testing.T) {
	meta := map[string]string{"k": "v"}
	job, err := syncdom.NewSyncJob(
		syncdom.NewJobID(), "p", uuid.New(),
		syncdom.TypeResults, syncdom.PriorityLiveWindow,
		time.Now().Add(time.Minute), meta,
	)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	meta["k"] = "mutated"
	if job.Metadata["k"] != "v" {
		t.Error("metadata is shared with caller — defensive copy failed")
	}
}

// ---------------------------------------------------------------------------
// RateLimitPolicy
// ---------------------------------------------------------------------------

func TestNewRateLimitPolicyHappyPath(t *testing.T) {
	p, err := syncdom.NewRateLimitPolicy("api_football", 10, 300, 100, 20)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if p.ProviderID != "api_football" {
		t.Errorf("provider lost: %q", p.ProviderID)
	}
	if p.IsUnlimited() {
		t.Error("policy with rpm=10 should NOT report unlimited")
	}
}

func TestNewRateLimitPolicyRejectsMissingProvider(t *testing.T) {
	_, err := syncdom.NewRateLimitPolicy("", 1, 1, 1, 1)
	if !errors.Is(err, syncdom.ErrPolicyMissingProvider) {
		t.Errorf("expected ErrPolicyMissingProvider, got %v", err)
	}
}

func TestNewRateLimitPolicyRejectsNegative(t *testing.T) {
	_, err := syncdom.NewRateLimitPolicy("p", -1, 0, 0, 0)
	if !errors.Is(err, syncdom.ErrPolicyNegative) {
		t.Errorf("expected ErrPolicyNegative, got %v", err)
	}
}

func TestRateLimitPolicyUnlimitedWhenAllZero(t *testing.T) {
	p, _ := syncdom.NewRateLimitPolicy("p", 0, 0, 0, 0)
	if !p.IsUnlimited() {
		t.Error("all-zero policy must report unlimited")
	}
}

// ---------------------------------------------------------------------------
// PollPolicy
// ---------------------------------------------------------------------------

func TestNewPollPolicyHappyPath(t *testing.T) {
	p, err := syncdom.NewPollPolicy(
		"api_football", syncdom.TypeResults,
		15*time.Minute, 15*time.Second, true,
	)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if !p.Enabled {
		t.Error("enabled lost")
	}
	if p.EffectiveInterval(true) != 15*time.Second {
		t.Errorf("live interval not honoured: %v", p.EffectiveInterval(true))
	}
	if p.EffectiveInterval(false) != 15*time.Minute {
		t.Errorf("baseline interval not honoured: %v", p.EffectiveInterval(false))
	}
}

func TestNewPollPolicyRejectsZeroInterval(t *testing.T) {
	_, err := syncdom.NewPollPolicy(
		"p", syncdom.TypeFixtures, 0, 0, true,
	)
	if !errors.Is(err, syncdom.ErrPollPolicyMissingInterval) {
		t.Errorf("expected ErrPollPolicyMissingInterval, got %v", err)
	}
}

func TestNewPollPolicyRejectsLooseLiveInterval(t *testing.T) {
	// Live cadence must be tighter (smaller) than baseline.
	_, err := syncdom.NewPollPolicy(
		"p", syncdom.TypeResults,
		1*time.Minute, 5*time.Minute, true,
	)
	if !errors.Is(err, syncdom.ErrPollPolicyInvalidLive) {
		t.Errorf("expected ErrPollPolicyInvalidLive, got %v", err)
	}
}

func TestNewPollPolicyRejectsBadSyncType(t *testing.T) {
	_, err := syncdom.NewPollPolicy(
		"p", syncdom.SyncType("bogus"),
		time.Minute, 0, true,
	)
	if !errors.Is(err, syncdom.ErrUnknownSyncType) {
		t.Errorf("expected ErrUnknownSyncType, got %v", err)
	}
}

func TestPollPolicyEffectiveIntervalFallsBackWhenNoLive(t *testing.T) {
	p, _ := syncdom.NewPollPolicy(
		"p", syncdom.TypeStandings,
		6*time.Hour, 0, true,
	)
	if p.EffectiveInterval(true) != 6*time.Hour {
		t.Errorf("no-live policy must return baseline even when live=true")
	}
}
