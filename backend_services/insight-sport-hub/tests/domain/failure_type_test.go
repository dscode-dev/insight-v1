// FailureType classification — Sprint 5.
//
// Locks in the decision matrix the spec calls out verbatim:
//
//	Provider Timeout            → Transient
//	Redis Unavailable           → Infrastructure
//	Malformed Payload           → Validation
//	Unknown Provider            → Permanent
//	Rate Limit                  → Transient
//	Competition Disabled        → Permanent
//
// Plus the Retryable() contract used by the queue's Settle method
// to choose Retry vs Fail.
package domain_test

import (
	"testing"

	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
)

func TestClassifyReasonMatrix(t *testing.T) {
	cases := map[string]syncdom.FailureType{
		syncdom.ReasonProviderTimeout:   syncdom.FailureProvider,
		syncdom.ReasonProviderError:     syncdom.FailureProvider,
		syncdom.ReasonProviderRateLimit: syncdom.FailureTransient,
		syncdom.ReasonRedisUnavailable:  syncdom.FailureInfrastructure,
		syncdom.ReasonDatabaseError:     syncdom.FailureInfrastructure,
		syncdom.ReasonMalformedPayload:  syncdom.FailureValidation,
		syncdom.ReasonUnknownProvider:   syncdom.FailurePermanent,
		syncdom.ReasonCompetitionOff:    syncdom.FailurePermanent,
		syncdom.ReasonUnsupportedSync:   syncdom.FailurePermanent,
		syncdom.ReasonAttemptsExhausted: syncdom.FailurePermanent,
	}
	for reason, want := range cases {
		if got := syncdom.ClassifyReason(reason); got != want {
			t.Errorf("ClassifyReason(%q) = %q, want %q", reason, got, want)
		}
	}
}

func TestClassifyReasonUnknownDefaultsToTransient(t *testing.T) {
	if got := syncdom.ClassifyReason("totally-new-failure"); got != syncdom.FailureTransient {
		t.Errorf("unknown reason should default to Transient, got %q", got)
	}
}

func TestFailureTypeRetryable(t *testing.T) {
	retryable := []syncdom.FailureType{
		syncdom.FailureTransient,
		syncdom.FailureProvider,
		syncdom.FailureInfrastructure,
	}
	terminal := []syncdom.FailureType{
		syncdom.FailureValidation,
		syncdom.FailurePermanent,
	}
	for _, f := range retryable {
		if !f.Retryable() {
			t.Errorf("%q must be retryable", f)
		}
	}
	for _, f := range terminal {
		if f.Retryable() {
			t.Errorf("%q must NOT be retryable", f)
		}
	}
}
