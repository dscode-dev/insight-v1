// The Odds API (the-odds-api.com v4) DTOs. Private to this package —
// never escape the adapter boundary. The mapper is the only file that
// touches both DTOs + domain types.
//
// Source: https://the-odds-api.com/liveapi/guides/v4/
package the_odds_api

import "time"

// ---- /v4/sports ----

type sportDTO struct {
	Key          string `json:"key"`   // e.g. "soccer_epl"
	Group        string `json:"group"` // e.g. "Soccer"
	Title        string `json:"title"`
	Description  string `json:"description"`
	Active       bool   `json:"active"`
	HasOutrights bool   `json:"has_outrights"`
}

// ---- /v4/sports/{sport_key}/odds ----

// oddsEventDTO is one upcoming/live match with its per-bookmaker
// market quotes. The same shape is nested under the historical
// endpoint's `data` array.
type oddsEventDTO struct {
	ID           string         `json:"id"`
	SportKey     string         `json:"sport_key"`
	SportTitle   string         `json:"sport_title"`
	CommenceTime time.Time      `json:"commence_time"`
	HomeTeam     string         `json:"home_team"`
	AwayTeam     string         `json:"away_team"`
	Bookmakers   []bookmakerDTO `json:"bookmakers"`
}

type bookmakerDTO struct {
	Key        string      `json:"key"`
	Title      string      `json:"title"`
	LastUpdate time.Time   `json:"last_update"`
	Markets    []marketDTO `json:"markets"`
}

type marketDTO struct {
	Key        string       `json:"key"` // "h2h" | "spreads" | "totals" | ...
	LastUpdate time.Time    `json:"last_update"`
	Outcomes   []outcomeDTO `json:"outcomes"`
}

type outcomeDTO struct {
	Name  string   `json:"name"`  // team name | "Draw" | "Over" | "Under"
	Price float64  `json:"price"` // decimal odds
	Point *float64 `json:"point,omitempty"`
}

// ---- /v4/historical/sports/{sport_key}/odds ----

// historicalOddsResponse wraps the same event array with the snapshot
// timestamps the historical endpoint returns. previous/next let a
// caller walk the timeline, though Sprint-scope only consumes one
// snapshot per call.
type historicalOddsResponse struct {
	Timestamp         time.Time      `json:"timestamp"`
	PreviousTimestamp *time.Time     `json:"previous_timestamp"`
	NextTimestamp     *time.Time     `json:"next_timestamp"`
	Data              []oddsEventDTO `json:"data"`
}
