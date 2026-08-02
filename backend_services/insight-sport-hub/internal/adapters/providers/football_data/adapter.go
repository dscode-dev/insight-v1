// Adapter — ports.SourceAdapter implementation for football-data.org.
package football_data

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog/log"

	"github.com/konoha-labs/insight-sports-hub/internal/adapters/observability"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

const (
	SourceID       = "football_data"
	SourceName     = "football-data.org"
	AdapterVersion = "football_data@1.0.0"
	APIVersion     = "v4"
)

type AdapterConfig struct {
	APIKey            string
	BaseURL           string
	DefaultConfidence float64
	ConfidenceWeight  float64
}

type httpClient interface {
	Competitions(ctx context.Context) (competitionsResponse, error)
	Matches(ctx context.Context, code string) (matchesResponse, error)
	Standings(ctx context.Context, code string) (standingsResponse, error)
}

type Adapter struct {
	client            httpClient
	mapper            *mapper
	registry          ports.CompetitionRegistry
	status            observability.ProviderStatusRecorder
	defaultConfidence float64
	confidenceWeight  float64
}

func New(
	cfg AdapterConfig,
	registry ports.CompetitionRegistry,
	status observability.ProviderStatusRecorder,
) *Adapter {
	if cfg.DefaultConfidence <= 0 {
		cfg.DefaultConfidence = 0.80
	}
	if cfg.ConfidenceWeight <= 0 {
		cfg.ConfidenceWeight = 0.80
	}
	return NewWithClient(cfg,
		NewClient(Config{APIKey: cfg.APIKey, BaseURL: cfg.BaseURL}),
		registry, status,
	)
}

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

// Capabilities — football-data.org free tier covers fixtures +
// results + standings. Odds/lineups/news not offered by this
// provider.
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

func (a *Adapter) FetchHistoricalResults(
	ctx context.Context,
	req ports.HistoricalFetchRequest,
) ([]*event.RawSportsEvent, error) {

	events, err := a.FetchFixtures(
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

	results := make([]*event.RawSportsEvent, 0)

	for _, raw := range events {
		if raw.EventType() == "match.result" {
			results = append(results, raw)
		}
	}

	return results, nil
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

func (a *Adapter) FetchCompetitions(ctx context.Context) ([]ports.CompetitionDescriptor, error) {
	start := time.Now()
	resp, err := a.client.Competitions(ctx)
	a.recordStatus(start, err, "/v4/competitions")
	if err != nil {
		return nil, fmt.Errorf("football_data fetch competitions: %w", err)
	}
	out := make([]ports.CompetitionDescriptor, 0, len(resp.Competitions))
	for _, c := range resp.Competitions {
		out = append(out, ports.CompetitionDescriptor{
			// football-data.org's competition CODE (e.g. "PL", "BSA") is
			// what their other endpoints accept — we use it as the
			// external id for this source. Numeric ID is dropped.
			ExternalID:    c.Code,
			Name:          c.Name,
			CountryCode:   c.Area.Code,
			CurrentSeason: c.CurrentSeason.StartDate, // best available label
			SourceID:      SourceID,
		})
	}
	return out, nil
}

func (a *Adapter) FetchFixtures(
	ctx context.Context, req ports.FixtureFetchRequest,
) ([]*event.RawSportsEvent, error) {
	code, err := a.resolveProviderCode(ctx, req.CompetitionID)
	if err != nil {
		return nil, err
	}

	logger := log.Ctx(ctx)
	logger.Info().
		Str("provider", SourceID).
		Str("adapter_version", AdapterVersion).
		Str("endpoint", "/v4/competitions/{code}/matches").
		Str("competition", req.CompetitionID.String()).
		Str("external_code", code).
		Msg("provider_request_started")

	start := time.Now()
	resp, err := a.client.Matches(ctx, code)
	latency := time.Since(start)
	a.recordStatus(start, err, "/v4/competitions/{code}/matches")

	if err != nil {
		logger.Warn().Err(err).
			Str("provider", SourceID).
			Dur("latency", latency).
			Msg("provider_request_failed")
		return nil, fmt.Errorf("football_data matches: %w", err)
	}
	logger.Info().
		Str("provider", SourceID).
		Dur("latency", latency).
		Int("results", resp.Count).
		Msg("provider_request_finished")

	out := make([]*event.RawSportsEvent, 0, len(resp.Matches))
	for _, m := range resp.Matches {
		raw, err := a.mapper.MapMatch(req.CompetitionID, m)
		if err != nil {
			logger.Warn().Err(err).
				Int64("external_match_id", m.ID).
				Msg("football_data_match_skipped")
			continue
		}
		out = append(out, raw)
	}
	return out, nil
}

func (a *Adapter) FetchStandings(
	ctx context.Context, req ports.StandingsFetchRequest,
) ([]*event.RawSportsEvent, error) {
	code, err := a.resolveProviderCode(ctx, req.CompetitionID)
	if err != nil {
		return nil, err
	}
	start := time.Now()
	resp, err := a.client.Standings(ctx, code)
	a.recordStatus(start, err, "/v4/competitions/{code}/standings")
	if err != nil {
		return nil, fmt.Errorf("football_data standings: %w", err)
	}
	raw, err := a.mapper.MapStandings(req.CompetitionID, resp)
	if err != nil {
		log.Ctx(ctx).Warn().Err(err).
			Str("external_code", code).
			Msg("football_data_standings_skipped")
		return nil, nil
	}
	return []*event.RawSportsEvent{raw}, nil
}

func (a *Adapter) Health() ports.HealthSnapshot {
	return a.status.Snapshot(SourceID)
}

func (a *Adapter) resolveProviderCode(
	ctx context.Context, competitionID uuid.UUID,
) (string, error) {
	code, err := a.registry.GetExternalIDForSource(ctx, competitionID, SourceID)
	if err != nil {
		return "", fmt.Errorf("football_data: no provider mapping for competition %s: %w",
			competitionID, err)
	}
	return code, nil
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
