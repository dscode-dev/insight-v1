// Package sentiment holds the SentimentSnapshot value type.
//
// Snapshots are produced by a downstream rollup job (Atlas
// intelligence territory — NOT this service) which reads recent signals
// and writes rows into `sentiment_snapshots`. This package only
// READS them and presents derived fields to the gRPC surface.
//
// Derivation of proto fields from the stored row:
//
//	home_lean  = home_pct - away_pct                     (range -1..1)
//	dispersion = 1 - max(home_pct, draw_pct, away_pct)   (proxy for split)
//	pressure   = min(1, log10(1 + participants) / log10(101))
//	                                                     (compresses 0..100+
//	                                                      into 0..1)
package sentiment

import (
	"math"
	"time"

	"github.com/google/uuid"
)

type Snapshot struct {
	MatchID      uuid.UUID
	HomePct      float64
	DrawPct      float64
	AwayPct      float64
	Participants int64
	CapturedAt   time.Time
}

// HomeLean returns home_pct - away_pct, clamped to -1..1.
func (s Snapshot) HomeLean() float64 {
	lean := s.HomePct - s.AwayPct
	if lean > 1 {
		return 1
	}
	if lean < -1 {
		return -1
	}
	return lean
}

// Dispersion: 1 - max share. A perfect consensus (one bucket = 1.0)
// has dispersion 0; a 3-way tie (1/3 each) has ~0.67.
func (s Snapshot) Dispersion() float64 {
	m := s.HomePct
	if s.DrawPct > m {
		m = s.DrawPct
	}
	if s.AwayPct > m {
		m = s.AwayPct
	}
	d := 1 - m
	if d < 0 {
		return 0
	}
	return d
}

// Pressure: log-compressed engagement signal. 0 participants → 0,
// 100 participants → 1.0. Beyond 100 we still cap at 1.0 (engagement
// "heat" doesn't grow forever in UI terms — beyond saturation a
// linear bump means nothing visually).
func (s Snapshot) Pressure() float64 {
	if s.Participants <= 0 {
		return 0
	}
	const ref = 101.0 // pin: 100 participants -> 1.0
	v := math.Log10(1+float64(s.Participants)) / math.Log10(ref)
	if v > 1 {
		return 1
	}
	return v
}

// Point is a denormalised time-series sample used by HistoryForMatch.
type Point struct {
	Ts       time.Time
	HomeLean float64
	Pressure float64
}
