// FailureType — Sprint 5 explicit failure taxonomy.
//
// Sprint 4 introduced Retry / Ack / Fail on ports.JobQueue. The
// runner picked the lifecycle method from local heuristics
// ("fetch_failed" → Retry; "unknown_provider" → Fail). Sprint 5
// pulls that decision into the domain by classifying every failure
// into one of four bands:
//
//	Transient        — provider hiccup / quota burst / network glitch
//	Permanent        — semantic dead-end (unknown provider, sport
//	                   not supported, competition disabled)
//	Provider         — a sub-class of Transient: provider returned
//	                   a 4xx/5xx whose retry MAY help
//	Infrastructure   — our infra broke (Redis down, DB down). Distinct
//	                   so observability + alerting can pivot quickly.
//	Validation       — malformed payload from the provider. Routes
//	                   to Fail because no retry will fix the wire.
//
// Decision matrix (spec verbatim):
//
//	Provider Timeout           → Transient
//	Redis Unavailable          → Infrastructure
//	Malformed Payload          → Validation
//	Unknown Provider           → Permanent
//	Rate Limit                 → Transient
//	Competition Disabled       → Permanent
//
// Architectural rule: this taxonomy lives in `domain/sync` because
// the queue adapter (Sprint 4) + the runner (Sprint 3) + future
// DLQ store (Sprint 5+) all need to agree on the classification.
// Putting it on either side would force a one-way import.
package sync

// FailureType is the band a runtime failure belongs to. The queue
// adapter consults the type to decide Retry vs Fail; observability
// pivots metrics + logs on the same enum.
type FailureType string

const (
	// FailureTransient — short-lived, retry will likely succeed.
	// Includes provider 5xx, network glitches, brief contention.
	FailureTransient FailureType = "transient"

	// FailureProvider — provider-side error that MAY recover (4xx
	// edge cases like a stale auth token, or 503 on a single host
	// of a load-balanced cluster). Same retry semantics as
	// Transient; reported separately so dashboards can attribute
	// outages to specific upstreams.
	FailureProvider FailureType = "provider"

	// FailureInfrastructure — OUR infra broke (Redis unreachable,
	// Postgres down, queue write rejected). Retry, but page ops.
	FailureInfrastructure FailureType = "infrastructure"

	// FailureValidation — wire payload could not be parsed /
	// failed schema. No retry will fix this. Goes to Fail.
	FailureValidation FailureType = "validation"

	// FailurePermanent — semantic dead-end (no adapter registered,
	// competition disabled, unsupported sync_type). No retry will
	// fix this either; goes to Fail.
	FailurePermanent FailureType = "permanent"
)

// Retryable reports whether the queue adapter should call Retry
// (instead of Fail) on a delivery that hit this failure.
//
// Validation + Permanent return false — both are dead-ends where
// retry cannot recover. Everything else returns true. The queue
// adapter additionally short-circuits exhausted attempts to Fail
// even for retryable types — that logic lives in the queue, not
// here, because attempt-counting is per-delivery state, not per-
// failure-type.
func (f FailureType) Retryable() bool {
	switch f {
	case FailureValidation, FailurePermanent:
		return false
	default:
		return true
	}
}

// Reason slugs — the per-cause strings the runner stamps onto a
// Retry/Fail call. Kept as constants so dashboards + log aggregators
// can pivot on a stable vocabulary. These slugs are the SECOND
// dimension on top of FailureType (e.g. "provider_timeout" implies
// FailureTransient; "redis_unavailable" implies FailureInfrastructure).
const (
	ReasonProviderTimeout   = "provider_timeout"
	ReasonProviderError     = "provider_error"
	ReasonProviderRateLimit = "rate_limit"
	ReasonRedisUnavailable  = "redis_unavailable"
	ReasonDatabaseError     = "database_error"
	ReasonMalformedPayload  = "malformed_payload"
	ReasonUnknownProvider   = "unknown_provider"
	ReasonCompetitionOff    = "competition_disabled"
	ReasonUnsupportedSync   = "unsupported_sync_type"
	ReasonAttemptsExhausted = "attempts_exhausted"
)

// ClassifyReason — pure lookup from reason slug to FailureType.
// The runner emits a reason; the queue adapter calls Classify to
// decide Retry vs Fail. Unknown reasons default to FailureTransient
// (conservative — better to retry once than silently fail).
func ClassifyReason(reason string) FailureType {
	switch reason {
	case ReasonProviderTimeout:
		return FailureProvider
	case ReasonProviderError:
		return FailureProvider
	case ReasonProviderRateLimit:
		return FailureTransient
	case ReasonRedisUnavailable, ReasonDatabaseError:
		return FailureInfrastructure
	case ReasonMalformedPayload:
		return FailureValidation
	case ReasonUnknownProvider, ReasonCompetitionOff, ReasonUnsupportedSync:
		return FailurePermanent
	case ReasonAttemptsExhausted:
		// Special case: this is the queue adapter's OWN reason
		// after it's already decided the chain has no retries
		// left. By definition not retryable.
		return FailurePermanent
	default:
		return FailureTransient
	}
}
