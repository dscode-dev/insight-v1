// Mapper — DTO → RawSportsEvent translation for football-data.org.
// Pure (no I/O); same shape as the api_football mapper but operating
// over the football-data.org wire types.
package football_data

import (
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/sport"
)

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
	t source.SourceType,
	adapterVersion, apiVersion string,
	defaultConfidence float64,
) *mapper {
	return &mapper{
		sourceID: sourceID, sourceName: sourceName,
		sourceType:     t,
		adapterVersion: adapterVersion, apiVersion: apiVersion,
		defaultConfidence: defaultConfidence,
	}
}

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

func (m *mapper) MapMatch(
	competitionID uuid.UUID,
	dto matchDTO,
) (*event.RawSportsEvent, error) {
	if dto.UTCDate.IsZero() {
		return nil, fmt.Errorf("map match %d: missing utcDate", dto.ID)
	}
	eventType := "match.fixture"
	if isFinished(dto.Status) {
		eventType = "match.result"
	}

	payload := map[string]any{
		"external_fixture_id": dto.ID,
		"scheduled_at":        dto.UTCDate.UTC().Format(time.RFC3339),
		"status":              dto.Status,
		"matchday":            dto.Matchday,
		"stage":               dto.Stage,
		"home_team": map[string]any{
			"external_id": dto.HomeTeam.ID,
			"name":        dto.HomeTeam.Name,
			"short_name":  dto.HomeTeam.ShortName,
			"tla":         dto.HomeTeam.TLA,
		},
		"away_team": map[string]any{
			"external_id": dto.AwayTeam.ID,
			"name":        dto.AwayTeam.Name,
			"short_name":  dto.AwayTeam.ShortName,
			"tla":         dto.AwayTeam.TLA,
		},
		"season": map[string]any{
			"external_id": dto.Season.ID,
			"start_date":  dto.Season.StartDate,
			"end_date":    dto.Season.EndDate,
		},
	}
	if dto.Score.FullTime.Home != nil && dto.Score.FullTime.Away != nil {
		payload["score"] = map[string]any{
			"home":     *dto.Score.FullTime.Home,
			"away":     *dto.Score.FullTime.Away,
			"winner":   dto.Score.Winner,
			"duration": dto.Score.Duration,
		}
	}

	ref := m.sourceRef(time.Now().UTC(), "/v4/competitions/{id}/matches")
	externalMatchID := fmt.Sprintf("%d", dto.ID)

	return event.NewRaw(
		uuid.New(),
		ref,
		sport.Football,
		competitionID,
		externalMatchID,
		eventType,
		dto.UTCDate.UTC(),
		payload,
		m.defaultConfidence,
	)
}

func (m *mapper) MapStandings(
	competitionID uuid.UUID,
	dto standingsResponse,
) (*event.RawSportsEvent, error) {
	if dto.Competition.ID == 0 {
		return nil, errors.New("map standings: empty competition")
	}
	// football-data.org returns a "TOTAL" group + optional HOME/AWAY
	// projections. Sprint 2 keeps only TOTAL — the Hub's
	// canonical.standings is the consolidated table.
	var totalRows []standingRowDTO
	for _, g := range dto.Standings {
		if g.Type == "TOTAL" {
			totalRows = g.Table
			break
		}
	}
	if len(totalRows) == 0 {
		return nil, errors.New("map standings: no TOTAL group")
	}

	observed := time.Now().UTC()
	rows := make([]map[string]any, 0, len(totalRows))
	for _, r := range totalRows {
		rows = append(rows, map[string]any{
			"rank":          r.Position,
			"points":        r.Points,
			"played":        r.PlayedGames,
			"win":           r.Won,
			"draw":          r.Draw,
			"lose":          r.Lost,
			"goals_for":     r.GoalsFor,
			"goals_against": r.GoalsAgainst,
			"goal_diff":     r.GoalDifference,
			"team": map[string]any{
				"external_id": r.Team.ID,
				"name":        r.Team.Name,
				"short_name":  r.Team.ShortName,
				"tla":         r.Team.TLA,
			},
		})
	}

	payload := map[string]any{
		"competition": map[string]any{
			"external_id": dto.Competition.ID,
			"name":        dto.Competition.Name,
			"code":        dto.Competition.Code,
		},
		"season": map[string]any{
			"external_id": dto.Season.ID,
		},
		"rows":      rows,
		"row_count": len(rows),
	}

	ref := m.sourceRef(observed, "/v4/competitions/{id}/standings")
	externalID := fmt.Sprintf("standings:%d:%d", dto.Competition.ID, dto.Season.ID)

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

// isFinished — football-data.org status values that mean concluded.
// Spec: SCHEDULED, TIMED, IN_PLAY, PAUSED, FINISHED, SUSPENDED,
// POSTPONED, CANCELLED, AWARDED.
func isFinished(status string) bool {
	switch status {
	case "FINISHED", "AWARDED":
		return true
	default:
		return false
	}
}
