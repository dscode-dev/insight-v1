// API-Football DTOs — exact wire shapes the provider returns.
//
// These types are PRIVATE to the adapter package (lower-case names
// outside this file would surface them via reflection alone). The
// adapter NEVER lets a DTO escape to the application layer — the
// mapper converts to domain types at the package boundary.
//
// Field tags are JSON only. The provider returns numbers as JSON
// numbers; the int64s here force pgx-friendly numeric types
// downstream.
package api_football

// envelope is the standard API-Football wrapper used on every
// endpoint. We unmarshal the response envelope then dispatch on
// `Get` (the endpoint name the provider echoes back).
type envelope[T any] struct {
	Get      string         `json:"get"`
	Errors   any            `json:"errors"` // sometimes [], sometimes {}
	Results  int            `json:"results"`
	Response T              `json:"response"`
	Paging   pagingMetadata `json:"paging"`
}

type pagingMetadata struct {
	Current int `json:"current"`
	Total   int `json:"total"`
}

// ---- /v3/leagues ----

type leagueWrapper struct {
	League  leagueDTO   `json:"league"`
	Country countryDTO  `json:"country"`
	Seasons []seasonDTO `json:"seasons"`
}

type leagueDTO struct {
	ID   int64  `json:"id"`
	Name string `json:"name"`
	Type string `json:"type"`
}

type countryDTO struct {
	Name string `json:"name"`
	Code string `json:"code"` // ISO 3166 alpha-2; sometimes empty
}

type seasonDTO struct {
	Year    int64 `json:"year"`
	Current bool  `json:"current"`
}

// ---- /v3/fixtures ----

type fixtureWrapper struct {
	Fixture fixtureDTO    `json:"fixture"`
	League  fixtureLeague `json:"league"`
	Teams   fixtureTeams  `json:"teams"`
	Goals   fixtureGoals  `json:"goals"`
}

type fixtureDTO struct {
	ID     int64         `json:"id"`
	Date   string        `json:"date"` // RFC3339
	Status fixtureStatus `json:"status"`
}

type fixtureStatus struct {
	Long    string `json:"long"`  // "Match Finished"
	Short   string `json:"short"` // "FT", "1H", "NS"
	Elapsed *int   `json:"elapsed,omitempty"`
}

type fixtureLeague struct {
	ID     int64  `json:"id"`
	Name   string `json:"name"`
	Season int64  `json:"season"`
}

type fixtureTeams struct {
	Home fixtureTeam `json:"home"`
	Away fixtureTeam `json:"away"`
}

type fixtureTeam struct {
	ID   int64  `json:"id"`
	Name string `json:"name"`
}

type fixtureGoals struct {
	Home *int `json:"home"`
	Away *int `json:"away"`
}

// ---- /v3/standings ----

type standingsWrapper struct {
	League standingsLeague `json:"league"`
}

type standingsLeague struct {
	ID     int64  `json:"id"`
	Name   string `json:"name"`
	Season int64  `json:"season"`
	// Standings is `[[row, row, ...]]` (provider may return multiple
	// groups in cup competitions — Sprint 2 flattens to a single
	// table by concatenation).
	Standings [][]standingRow `json:"standings"`
}

type standingRow struct {
	Rank      int           `json:"rank"`
	Team      fixtureTeam   `json:"team"`
	Points    int           `json:"points"`
	GoalsDiff int           `json:"goalsDiff"`
	Form      string        `json:"form,omitempty"`
	All       standingStats `json:"all"`
}

type standingStats struct {
	Played int `json:"played"`
	Win    int `json:"win"`
	Draw   int `json:"draw"`
	Lose   int `json:"lose"`
	Goals  struct {
		For     int `json:"for"`
		Against int `json:"against"`
	} `json:"goals"`
}
