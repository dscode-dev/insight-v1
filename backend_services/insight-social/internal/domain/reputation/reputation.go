// Package reputation models the User reputation score + tier + accuracy
// surface.
//
// Source-of-truth: reputation_events.delta (additive ledger). The
// `users.reputation` column is a denormalised cache of SUM(delta);
// Recompute rebuilds it from the ledger and writes it back. Get
// reads the cache directly.
//
// Score clamping: scores are clamped to 0..100 at the cache layer.
// The ledger itself is unbounded — if cumulative deltas push past
// 100 or below 0, only the cached projection clamps.
//
// Tier derivation lives in domain/user (TierForScore). We reuse it
// here rather than duplicating the boundaries.
package reputation

import (
	"github.com/google/uuid"

	domuser "github.com/konoha-labs/insight-social/internal/domain/user"
)

const (
	MinScore = 0
	MaxScore = 100
)

// Reputation is the read-model returned by Get / Recompute.
type Reputation struct {
	UserID   uuid.UUID
	Score    int
	Tier     domuser.Tier
	Accuracy float64 // 0..1
}

// ClampScore enforces the 0..100 invariant on the cached projection.
// The reputation_events ledger is allowed to drift outside this
// range — Recompute is responsible for projecting back into bounds.
func ClampScore(score int) int {
	if score < MinScore {
		return MinScore
	}
	if score > MaxScore {
		return MaxScore
	}
	return score
}
