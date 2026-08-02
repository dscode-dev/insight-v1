// Adapter — ports.SourceAdapter implementation for API-Football.
//
// Stateless: holds only the configured HTTP client, the mapper
// (also stateless), and references to shared infrastructure (the
// CompetitionRegistry for canonical↔external id resolution + the
// ProviderStatus recorder for operational telemetry).
package api_football

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog/log"

	"github.com/konoha-labs/insight-sports-hub/internal/adapters/observability"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// AdapterVersion — bump on every behavioural change to the mapper
// or client. Lands on every produced SourceRef.
const (
	SourceID       = "api_football"
	SourceName     = "API-Football (api-sports.io)"
	AdapterVersion = "api_football@1.0.0"
	APIVersion     = "v3"
)

// AdapterConfig — what main.go passes at composition time.
type AdapterConfig struct {
	APIKey            string
	BaseURL           string
	DefaultConfidence float64
	ConfidenceWeight  float64
}

// httpClient is the narrow interface the adapter depends on — keeps
// tests free of net/http wrangling. The production *Client
// satisfies it; tests inject a stub.
type httpClient interface {
	Leagues(ctx context.Context) (envelope[[]leagueWrapper], error)
	Fixtures(ctx context.Context, leagueID, season int64) (envelope[[]fixtureWrapper], error)
	Standings(ctx context.Context, leagueID, season int64) (envelope[[]standingsWrapper], error)
}

type Adapter struct {
	client            httpClient
	mapper            *mapper
	registry          ports.CompetitionRegistry
	status            observability.ProviderStatusRecorder
	defaultConfidence float64
	confidenceWeight  float64
}

// New builds a fully-wired adapter using the production HTTP client.
func New(
	cfg AdapterConfig,
	registry ports.CompetitionRegistry,
	status observability.ProviderStatusRecorder,
) *Adapter {
	if cfg.DefaultConfidence <= 0 {
		cfg.DefaultConfidence = 0.85
	}
	if cfg.ConfidenceWeight <= 0 {
		cfg.ConfidenceWeight = 0.90
	}
	return NewWithClient(cfg,
		NewClient(Config{APIKey: cfg.APIKey, BaseURL: cfg.BaseURL}),
		registry, status,
	)
}

// NewWithClient — test seam. Lets tests inject a stub httpClient.
func NewWithClient(
	cfg AdapterConfig,
	c httpClient,
	registry ports.CompetitionRegistry,
	status observability.ProviderStatusRecorder,
) *Adapter {
	return &Adapter{
		client: c,
		mapper: newMapper(
			SourceID, SourceName, source.TypeCommercialAPI,
			AdapterVersion, APIVersion, cfg.DefaultConfidence,
		),
		registry:          registry,
		status:            status,
		defaultConfidence: cfg.DefaultConfidence,
		confidenceWeight:  cfg.ConfidenceWeight,
	}
}

func (a *Adapter) Identity() ports.AdapterIdentity {
	return ports.AdapterIdentity{
		SourceID:          SourceID,
		SourceName:        SourceName,
		SourceType:        source.TypeCommercialAPI,
		AdapterVersion:    AdapterVersion,
		APIVersion:        APIVersion,
		DefaultConfidence: a.defaultConfidence,
		ConfidenceWeight:  a.confidenceWeight,
		Capabilities:      Capabilities(),
	}
}

// Capabilities — declared by the adapter at package level so the
// Scheduler can introspect a provider without instantiating it.
// Odds/Lineups/News deferred — endpoints exist on API-Football but
// Sprint 2.1 does not consume them.
func Capabilities() source.ProviderCapability {
	return source.ProviderCapability{
		SupportsFixtures:           true,
		SupportsHistoricalFixtures: true,

		SupportsResults:           true,
		SupportsHistoricalResults: true,

		SupportsStandings:           true,
		SupportsHistoricalStandings: true,

		SupportsOdds:           false,
		SupportsHistoricalOdds: false,

		SupportsPlayers:           false,
		SupportsHistoricalPlayers: false,

		SupportsLineups:           false,
		SupportsHistoricalLineups: false,

		SupportsInjuries:           false,
		SupportsHistoricalInjuries: false,

		SupportsNews: false,
	}
}

func (a *Adapter) FetchHistoricalFixtures(
	ctx context.Context,
	req ports.HistoricalFetchRequest,
) ([]*event.RawSportsEvent, error) {
	return a.FetchFixtures(
		ctx,
		ports.FixtureFetchRequest{
			CompetitionID: req.CompetitionID,
			Season:        req.Season,
			From:          req.From,
			To:            req.To,
		},
	)
}

func (a *Adapter) FetchHistoricalStandings(
	ctx context.Context,
	req ports.HistoricalFetchRequest,
) ([]*event.RawSportsEvent, error) {
	return a.FetchStandings(
		ctx,
		ports.StandingsFetchRequest{
			CompetitionID: req.CompetitionID,
			Season:        req.Season,
		},
	)
}

func (a *Adapter) FetchHistoricalResults(
	ctx context.Context,
	req ports.HistoricalFetchRequest,
) ([]*event.RawSportsEvent, error) {
	all, err := a.FetchFixtures(
		ctx,
		ports.FixtureFetchRequest{
			CompetitionID: req.CompetitionID,
			Season:        req.Season,
			From:          req.From,
			To:            req.To,
		},
	)
	if err != nil {
		return nil, err
	}

	out := make([]*event.RawSportsEvent, 0, len(all))

	for _, raw := range all {
		if raw.EventType() == "match.result" {
			out = append(out, raw)
		}
	}

	return out, nil
}

func (a *Adapter) FetchCompetitions(ctx context.Context) ([]ports.CompetitionDescriptor, error) {
	start := time.Now()
	env, err := a.client.Leagues(ctx)
	a.recordStatus(start, err, "/v3/leagues")
	if err != nil {
		return nil, fmt.Errorf("api_football fetch competitions: %w", err)
	}
	out := make([]ports.CompetitionDescriptor, 0, len(env.Response))
	for _, l := range env.Response {
		var seasonLabel string
		for _, s := range l.Seasons {
			if s.Current {
				seasonLabel = strconv.FormatInt(s.Year, 10)
				break
			}
		}
		out = append(out, ports.CompetitionDescriptor{
			ExternalID:    strconv.FormatInt(l.League.ID, 10),
			Name:          l.League.Name,
			CountryCode:   l.Country.Code,
			CurrentSeason: seasonLabel,
			SourceID:      SourceID,
		})
	}
	return out, nil
}

func (a *Adapter) FetchFixtures(
	ctx context.Context, req ports.FixtureFetchRequest,
) ([]*event.RawSportsEvent, error) {
	leagueID, err := a.resolveProviderLeagueID(ctx, req.CompetitionID)
	if err != nil {
		return nil, err
	}
	season, err := parseSeason(req.Season)
	if err != nil {
		return nil, err
	}

	logger := log.Ctx(ctx)
	logger.Info().
		Str("provider", SourceID).
		Str("adapter_version", AdapterVersion).
		Str("endpoint", "/v3/fixtures").
		Int64("external_competition_id", leagueID).
		Int64("season", season).
		Str("competition", req.CompetitionID.String()).
		Msg("provider_request_started")

	start := time.Now()
	env, err := a.client.Fixtures(ctx, leagueID, season)
	latency := time.Since(start)
	a.recordStatus(start, err, "/v3/fixtures")

	if err != nil {
		logger.Warn().Err(err).
			Str("provider", SourceID).
			Dur("latency", latency).
			Msg("provider_request_failed")
		return nil, fmt.Errorf("api_football fixtures: %w", err)
	}
	logger.Info().
		Str("provider", SourceID).
		Dur("latency", latency).
		Int("results", env.Results).
		Msg("provider_request_finished")

	out := make([]*event.RawSportsEvent, 0, len(env.Response))
	for _, f := range env.Response {
		raw, err := a.mapper.MapFixture(req.CompetitionID, f)
		if err != nil {
			logger.Warn().Err(err).
				Int64("external_fixture_id", f.Fixture.ID).
				Str("fixture_id", strconv.FormatInt(f.Fixture.ID, 10)).
				Msg("api_football_fixture_skipped")
			continue
		}
		out = append(out, raw)
	}
	return out, nil
}

func (a *Adapter) FetchStandings(
	ctx context.Context, req ports.StandingsFetchRequest,
) ([]*event.RawSportsEvent, error) {
	leagueID, err := a.resolveProviderLeagueID(ctx, req.CompetitionID)
	if err != nil {
		return nil, err
	}
	season, err := parseSeason(req.Season)
	if err != nil {
		return nil, err
	}

	start := time.Now()
	env, err := a.client.Standings(ctx, leagueID, season)
	a.recordStatus(start, err, "/v3/standings")
	if err != nil {
		return nil, fmt.Errorf("api_football standings: %w", err)
	}
	out := make([]*event.RawSportsEvent, 0, 1)
	for _, s := range env.Response {
		raw, err := a.mapper.MapStandings(req.CompetitionID, s)
		if err != nil {
			log.Ctx(ctx).Warn().Err(err).
				Int64("external_league_id", s.League.ID).
				Msg("api_football_standings_skipped")
			continue
		}
		out = append(out, raw)
	}
	return out, nil
}

func (a *Adapter) Health() ports.HealthSnapshot {
	return a.status.Snapshot(SourceID)
}

// resolveProviderLeagueID translates the Hub's canonical competition
// UUID into the provider-native id via the registry. The mapping
// is populated either at adapter bootstrap (via FetchCompetitions
// + LinkExternalID) or by ops tooling. Missing mapping → typed
// error so the orchestrator can log + skip the competition.
func (a *Adapter) resolveProviderLeagueID(
	ctx context.Context, competitionID uuid.UUID,
) (int64, error) {
	externalID, err := a.registry.GetExternalIDForSource(ctx, competitionID, SourceID)
	if err != nil {
		return 0, fmt.Errorf("api_football: no provider mapping for competition %s: %w",
			competitionID, err)
	}
	leagueID, err := strconv.ParseInt(externalID, 10, 64)
	if err != nil {
		return 0, fmt.Errorf("api_football: external id %q not numeric: %w", externalID, err)
	}
	return leagueID, nil
}

// parseSeason — provider expects 4-digit year. Empty defaults to
// the current calendar year. Accepts variants "2025/26", "2025-26"
// by taking the leading 4 chars.
func parseSeason(label string) (int64, error) {
	if label == "" {
		return int64(time.Now().UTC().Year()), nil
	}
	if len(label) >= 4 {
		return strconv.ParseInt(label[:4], 10, 64)
	}
	return strconv.ParseInt(label, 10, 64)
}

func (a *Adapter) recordStatus(start time.Time, err error, endpoint string) {
	latency := time.Since(start)
	if err != nil {
		a.status.RecordFailure(SourceID, latency,
			fmt.Errorf("%s: %w", endpoint, err))
		return
	}
	a.status.RecordSuccess(SourceID, latency)
}

var (
	_ ports.SourceAdapter              = (*Adapter)(nil)
	_ ports.HistoricalFixturesAdapter  = (*Adapter)(nil)
	_ ports.HistoricalResultsAdapter   = (*Adapter)(nil)
	_ ports.HistoricalStandingsAdapter = (*Adapter)(nil)
)
