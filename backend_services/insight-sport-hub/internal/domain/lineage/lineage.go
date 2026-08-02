// Package lineage holds the value type that links Raw → Canonical.
//
// Modelled as its own package (not a method on CanonicalSportsEvent)
// because the relationship has its own queries — "which raws produced
// canonical X", "which canonicals consumed raw Y" — and admin
// dashboards inspect the graph directly. Keeping it standalone makes
// repository methods read-only against either event type without
// circular imports.
package lineage

import (
	"time"

	"github.com/google/uuid"
)

// Link is one Raw → Canonical relationship row. Many-to-many: one
// raw can contribute to several canonicals (rare but legal — e.g. a
// "match.lineup_published" raw informing both the lineup canonical
// AND a tangentially related "match.team_changes" canonical), and
// one canonical always has ≥1 raw.
//
// LinkedAt is when the lineage entry itself was created — distinct
// from raw.observed_at and canonical.occurred_at.
type Link struct {
	CanonicalEventID uuid.UUID
	RawEventID       uuid.UUID
	LinkedAt         time.Time
}

// Graph is the projection returned by lineage queries. Holds the
// canonical id at the centre + every raw_event_id that contributed.
//
// Future admin UI: render as a 1-level fan-out tree, click any raw
// node to drill into its full SourceRef + payload.
type Graph struct {
	CanonicalEventID uuid.UUID
	Raws             []RawSnapshot
}

// RawSnapshot is a thin projection of RawSportsEvent for lineage
// dashboards — full SourceRef + a few high-level columns, but NOT
// the payload (which is large; UI fetches on-demand).
type RawSnapshot struct {
	RawEventID      uuid.UUID
	SourceID        string
	SourceType      string
	ExternalMatchID string
	EventType       string
	ObservedAt      time.Time
	RawConfidence   float64
	LinkedAt        time.Time
}
