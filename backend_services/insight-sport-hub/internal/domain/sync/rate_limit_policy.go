// RateLimitPolicy — Sprint 2.1 contract.
//
// Declares per-provider quota envelopes. CONTRACT ONLY — Sprint 2.1
// neither enforces nor exposes limiters. The Scheduler (Sprint 3)
// owns the enforcement; adapters NEVER read or write this type.
//
// Architectural rule: providers must NOT know their own rate limits.
// Embedding quotas inside an adapter creates two failure modes:
//  1. Misconfigured quota in one tenant takes down the adapter for
//     every tenant sharing it.
//  2. Re-quoting the limit per adapter means we can't centralise
//     backoff/burst-shaping in the scheduler.
//
// The policy is therefore a piece of configuration the scheduler
// reads; the adapter remains stateless.
package sync

import "errors"

// RateLimitPolicy bundles every quota dimension a single provider
// can have. Zero in any field == "no explicit limit on this axis".
// The scheduler interprets the combination — usually the tightest
// limit binds.
type RateLimitPolicy struct {
	ProviderID        string // matches Source.SourceID slug
	RequestsPerMinute int
	RequestsPerHour   int
	DailyLimit        int
	BurstLimit        int
}

var (
	ErrPolicyMissingProvider = errors.New("ratelimit: provider_id required")
	ErrPolicyNegative        = errors.New("ratelimit: negative values not allowed")
)

// NewRateLimitPolicy validates invariants. The Scheduler calls this
// when loading policy rows; admin tooling calls it when writing them.
func NewRateLimitPolicy(
	providerID string,
	rpm, rph, daily, burst int,
) (RateLimitPolicy, error) {
	if providerID == "" {
		return RateLimitPolicy{}, ErrPolicyMissingProvider
	}
	if rpm < 0 || rph < 0 || daily < 0 || burst < 0 {
		return RateLimitPolicy{}, ErrPolicyNegative
	}
	return RateLimitPolicy{
		ProviderID:        providerID,
		RequestsPerMinute: rpm,
		RequestsPerHour:   rph,
		DailyLimit:        daily,
		BurstLimit:        burst,
	}, nil
}

// IsUnlimited reports whether every dimension is zero — convenient
// flag for tests + scheduler shortcuts.
func (p RateLimitPolicy) IsUnlimited() bool {
	return p.RequestsPerMinute == 0 &&
		p.RequestsPerHour == 0 &&
		p.DailyLimit == 0 &&
		p.BurstLimit == 0
}
