// football-data.org v4 DTOs. Private to this package — never escape
// the adapter boundary. The mapper is the only file in this package
// that touches both DTOs + domain types.
//
// Source: https://www.football-data.org/documentation/api
package football_data

import "time"

// ---- /v4/competitions ----

type competitionsResponse struct {
	Count        int              `json:"count"`
	Competitions []competitionDTO `json:"competitions"`
}

type competitionDTO struct {
	ID            int64     `json:"id"`
	Name          string    `json:"name"`
	Code          string    `json:"code"`
	Type          string    `json:"type"` // LEAGUE | CUP
	Area          areaDTO   `json:"area"`
	CurrentSeason seasonDTO `json:"currentSeason"`
}

type areaDTO struct {
	ID   int64  `json:"id"`
	Name string `json:"name"`
	Code string `json:"code"` // ISO 3166 alpha-3 (note: alpha-3, not alpha-2)
}

type seasonDTO struct {
	ID              int64  `json:"id"`
	StartDate       string `json:"startDate"`
	EndDate         string `json:"endDate"`
	CurrentMatchday int    `json:"currentMatchday"`
}

// ---- /v4/competitions/{id}/matches ----

type matchesResponse struct {
	Count       int                 `json:"count"`
	Filters     map[string]any      `json:"filters"`
	Competition matchCompetitionDTO `json:"competition"`
	Matches     []matchDTO          `json:"matches"`
}

type matchCompetitionDTO struct {
	ID   int64  `json:"id"`
	Name string `json:"name"`
	Code string `json:"code"`
	Type string `json:"type"`
}

type matchDTO struct {
	ID       int64        `json:"id"`
	UTCDate  time.Time    `json:"utcDate"`
	Status   string       `json:"status"` // SCHEDULED | LIVE | IN_PLAY | PAUSED | FINISHED | ...
	Matchday int          `json:"matchday"`
	Stage    string       `json:"stage"`
	HomeTeam matchTeamDTO `json:"homeTeam"`
	AwayTeam matchTeamDTO `json:"awayTeam"`
	Score    scoreDTO     `json:"score"`
	Season   matchSeason  `json:"season"`
}

type matchTeamDTO struct {
	ID        int64  `json:"id"`
	Name      string `json:"name"`
	ShortName string `json:"shortName"`
	TLA       string `json:"tla"`
}

type matchSeason struct {
	ID              int64  `json:"id"`
	StartDate       string `json:"startDate"`
	EndDate         string `json:"endDate"`
	CurrentMatchday int    `json:"currentMatchday"`
}

type scoreDTO struct {
	Winner   string       `json:"winner"`   // HOME_TEAM | AWAY_TEAM | DRAW | null
	Duration string       `json:"duration"` // REGULAR | EXTRA_TIME | PENALTY_SHOOTOUT
	FullTime scoreTimeDTO `json:"fullTime"`
	HalfTime scoreTimeDTO `json:"halfTime"`
}

type scoreTimeDTO struct {
	Home *int `json:"home"`
	Away *int `json:"away"`
}

// ---- /v4/competitions/{id}/standings ----

type standingsResponse struct {
	Competition matchCompetitionDTO `json:"competition"`
	Season      matchSeason         `json:"season"`
	Standings   []standingsGroupDTO `json:"standings"`
}

type standingsGroupDTO struct {
	Stage string           `json:"stage"`
	Type  string           `json:"type"` // TOTAL | HOME | AWAY
	Group string           `json:"group"`
	Table []standingRowDTO `json:"table"`
}

type standingRowDTO struct {
	Position       int          `json:"position"`
	Team           matchTeamDTO `json:"team"`
	PlayedGames    int          `json:"playedGames"`
	Form           string       `json:"form"`
	Won            int          `json:"won"`
	Draw           int          `json:"draw"`
	Lost           int          `json:"lost"`
	Points         int          `json:"points"`
	GoalsFor       int          `json:"goalsFor"`
	GoalsAgainst   int          `json:"goalsAgainst"`
	GoalDifference int          `json:"goalDifference"`
}
