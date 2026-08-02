// Mapper — pure DTO → RawSportsEvent translation. No I/O.
//
// Every produced raw carries a fully-populated SourceRef + the
// provider's payload preserved verbatim under a flat map so the
// lineage rule holds across the pipeline.
//
// Event types emitted:
//
//	match.fixture       — status not yet "finished"
//	match.result        — status finished
//	competition.standings — single per call (the full table)
package api_football

import (
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/sport"
)

// mapper holds the identity values it stamps on every produced
// raw. Stateless — fields are read-only after construction.
type mapper struct {
	sourceID          string
	sourceName        string
	sourceType        source.SourceType
	adapterVersion    string
	apiVersion        string
	defaultConfidence float64
}

func newMapper(
	sourceID, sourceName string,
	sourceType source.SourceType,
	adapterVersion, apiVersion string,
	defaultConfidence float64,
) *mapper {
	return &mapper{
		sourceID:          sourceID,
		sourceName:        sourceName,
		sourceType:        sourceType,
		adapterVersion:    adapterVersion,
		apiVersion:        apiVersion,
		defaultConfidence: defaultConfidence,
	}
}

// sourceRef constructs the canonical SourceRef stamped on every
// raw the mapper emits. Metadata fields are wire-stable — the
// downstream debugging story relies on them being present + named
// the same across every call.
func (m *mapper) sourceRef(observedAt time.Time, endpoint string) source.SourceRef {
	av := m.adapterVersion
	return source.SourceRef{
		SourceID:       m.sourceID,
		SourceName:     m.sourceName,
		Type:           m.sourceType,
		Confidence:     m.defaultConfidence,
		ObservedAt:     observedAt,
		AdapterVersion: &av,
		Metadata: map[string]any{
			"endpoint":    endpoint,
			"api_version": m.apiVersion,
		},
	}
}

// MapFixture translates one provider fixture into a RawSportsEvent.
// `competitionID` is the Hub's canonical UUID (resolved by the
// adapter via the CompetitionRegistry before this call).
//
// Returns the RawSportsEvent or a wrapped error if any invariant
// fails — the adapter logs + skips the offending fixture rather
// than failing the whole batch.
func (m *mapper) MapFixture(
	competitionID uuid.UUID,
	dto fixtureWrapper,
) (*event.RawSportsEvent, error) {
	scheduled, err := time.Parse(time.RFC3339, dto.Fixture.Date)
	if err != nil {
		return nil, fmt.Errorf("map fixture %d: parse date: %w", dto.Fixture.ID, err)
	}

	eventType := "match.fixture"
	if isFinished(dto.Fixture.Status.Short) {
		eventType = "match.result"
	}

	payload := map[string]any{
		"external_fixture_id": dto.Fixture.ID,
		"scheduled_at":        scheduled.UTC().Format(time.RFC3339),
		"status_short":        dto.Fixture.Status.Short,
		"status_long":         dto.Fixture.Status.Long,
		"home_team": map[string]any{
			"external_id": dto.Teams.Home.ID,
			"name":        dto.Teams.Home.Name,
		},
		"away_team": map[string]any{
			"external_id": dto.Teams.Away.ID,
			"name":        dto.Teams.Away.Name,
		},
		"league": map[string]any{
			"external_id": dto.League.ID,
			"name":        dto.League.Name,
			"season":      dto.League.Season,
		},
	}
	if dto.Goals.Home != nil && dto.Goals.Away != nil {
		payload["score"] = map[string]any{
			"home": *dto.Goals.Home,
			"away": *dto.Goals.Away,
		}
	}
	if dto.Fixture.Status.Elapsed != nil {
		payload["minute"] = *dto.Fixture.Status.Elapsed
	}

	ref := m.sourceRef(time.Now().UTC(), "/v3/fixtures")
	// External match id MUST be a string; the provider gives an int.
	externalMatchID := fmt.Sprintf("%d", dto.Fixture.ID)

	return event.NewRaw(
		uuid.New(),
		ref,
		sport.Football,
		competitionID,
		externalMatchID,
		eventType,
		scheduled.UTC(),
		payload,
		m.defaultConfidence,
	)
}

// MapStandings turns the standings call into ONE RawSportsEvent
// carrying the full league table. We flatten the provider's
// `[[group1],[group2]]` to a single slice (Sprint 2 simplification —
// cup competitions with groups will be re-modeled later).
//
// Returns nil if the response carries no league data (provider
// occasionally returns 200 with an empty `response` array).
func (m *mapper) MapStandings(
	competitionID uuid.UUID,
	dto standingsWrapper,
) (*event.RawSportsEvent, error) {
	if dto.League.ID == 0 {
		return nil, errors.New("map standings: empty league")
	}
	flat := flattenStandings(dto.League.Standings)
	if len(flat) == 0 {
		return nil, errors.New("map standings: empty table")
	}

	observed := time.Now().UTC()
	rows := make([]map[string]any, 0, len(flat))
	for _, r := range flat {
		rows = append(rows, map[string]any{
			"rank":          r.Rank,
			"points":        r.Points,
			"played":        r.All.Played,
			"win":           r.All.Win,
			"draw":          r.All.Draw,
			"lose":          r.All.Lose,
			"goals_for":     r.All.Goals.For,
			"goals_against": r.All.Goals.Against,
			"goal_diff":     r.GoalsDiff,
			"team": map[string]any{
				"external_id": r.Team.ID,
				"name":        r.Team.Name,
			},
		})
	}

	payload := map[string]any{
		"league": map[string]any{
			"external_id": dto.League.ID,
			"name":        dto.League.Name,
			"season":      dto.League.Season,
		},
		"rows":      rows,
		"row_count": len(rows),
	}

	ref := m.sourceRef(observed, "/v3/standings")
	// Standings don't have a single match id — use a synthetic
	// external id keyed on (league, season) so the orchestrator's
	// Identity stays unique per snapshot.
	externalID := fmt.Sprintf("standings:%d:%d", dto.League.ID, dto.League.Season)

	return event.NewRaw(
		uuid.New(),
		ref,
		sport.Football,
		competitionID,
		externalID,
		"competition.standings",
		observed,
		payload,
		m.defaultConfidence,
	)
}

// flattenStandings concatenates the provider's group arrays.
func flattenStandings(groups [][]standingRow) []standingRow {
	total := 0
	for _, g := range groups {
		total += len(g)
	}
	out := make([]standingRow, 0, total)
	for _, g := range groups {
		out = append(out, g...)
	}
	return out
}

// isFinished — the API-Football status short codes that mean
// "the match concluded". The provider declares a stable set; if a
// new code appears it falls through as "match.fixture" (safer
// default — the canonicalization layer can re-promote on a later
// observation).
func isFinished(shortCode string) bool {
	switch shortCode {
	case "FT", "AET", "PEN", "AWD", "WO":
		return true
	default:
		return false
	}
}
