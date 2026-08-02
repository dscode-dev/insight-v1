// Adapter — ports.SourceAdapter + ports.OddsAdapter +
// ports.HistoricalOddsAdapter implementation for The Odds API.
//
// Stateless: holds only the configured HTTP client, the stateless
// mapper, and references to shared infrastructure (CompetitionRegistry
// for canonical↔sport_key resolution + the ProviderStatus recorder).
//
// Capability surface: odds + historical_odds ONLY. Fixtures/results/
// standings are NOT served — the planner's capability filter means the
// scheduler never issues those jobs, but the SourceAdapter interface
// still requires the methods, so they return empty results.
package the_odds_api

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog/log"

	"github.com/konoha-labs/insight-sports-hub/internal/adapters/observability"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// ResponseCache is the optional odds-response cache seam (Sprint 6.1).
// Defined locally so the adapter never imports Redis or the cache
// adapter package (architectural boundary). Fetch returns cached bytes
// for key, or invokes loader on a miss and caches the result;
// concurrent calls for the same key are collapsed to a single loader
// invocation (request collapsing) by the implementation.
type ResponseCache interface {
	Fetch(ctx context.Context, key string, loader func(context.Context) ([]byte, error)) ([]byte, error)
}

// RequestRecorder is the optional budget-accounting seam (Sprint 6.1).
// The adapter calls it ONCE per real upstream API request (cache
// misses + direct fetches) so the budget manager's long-window
// counters reflect actual quota spend, not cache hits. Defined locally
// to keep the adapter free of the budget package.
type RequestRecorder interface {
	RecordRequest(ctx context.Context, providerID string)
}

// ScheduleObserver is the optional kickoff-feed seam (Sprint 6.1). The
// adapter reports each fixture's commence_time as it maps odds events,
// feeding the scheduler's kickoff tracker so dynamic polling windows
// have proximity data — without any extra provider call. Defined
// locally to keep the adapter free of the scheduling package.
type ScheduleObserver interface {
	ObserveKickoff(ctx context.Context, competitionID uuid.UUID, matchKey string, kickoff time.Time)
}

// Option configures optional Sprint 6.1 collaborators on the adapter.
type Option func(*Adapter)

// WithCache installs the odds-response cache.
func WithCache(c ResponseCache) Option { return func(a *Adapter) { a.cache = c } }

// WithRequestRecorder installs the budget request recorder.
func WithRequestRecorder(r RequestRecorder) Option { return func(a *Adapter) { a.recorder = r } }

// WithScheduleObserver installs the kickoff feed.
func WithScheduleObserver(o ScheduleObserver) Option {
	return func(a *Adapter) { a.scheduleObserver = o }
}

const (
	SourceID       = "the_odds_api"
	SourceName     = "The Odds API (the-odds-api.com)"
	AdapterVersion = "the_odds_api@1.0.0"
	APIVersion     = "v4"
)

type AdapterConfig struct {
	APIKey            string
	BaseURL           string
	DefaultConfidence float64
	ConfidenceWeight  float64
}

// httpClient is the narrow seam the adapter depends on — keeps tests
// free of net/http wrangling. The production *Client satisfies it.
type httpClient interface {
	Sports(ctx context.Context) ([]sportDTO, error)
	Odds(ctx context.Context, sportKey string, markets, regions []string) ([]oddsEventDTO, error)
	HistoricalOdds(ctx context.Context, sportKey string, date time.Time, markets, regions []string) (historicalOddsResponse, error)
}

type Adapter struct {
	client            httpClient
	mapper            *mapper
	registry          ports.CompetitionRegistry
	status            observability.ProviderStatusRecorder
	defaultConfidence float64
	confidenceWeight  float64

	// Sprint 6.1 optional collaborators. Nil = feature off.
	cache            ResponseCache
	recorder         RequestRecorder
	scheduleObserver ScheduleObserver
}

func New(
	cfg AdapterConfig,
	registry ports.CompetitionRegistry,
	status observability.ProviderStatusRecorder,
	opts ...Option,
) *Adapter {
	if cfg.DefaultConfidence <= 0 {
		cfg.DefaultConfidence = 0.80
	}
	if cfg.ConfidenceWeight <= 0 {
		cfg.ConfidenceWeight = 0.85
	}
	return NewWithClient(cfg,
		NewClient(Config{APIKey: cfg.APIKey, BaseURL: cfg.BaseURL}),
		registry, status, opts...,
	)
}

// NewWithClient — test seam. Lets tests inject a stub httpClient.
func NewWithClient(
	cfg AdapterConfig,
	c httpClient,
	registry ports.CompetitionRegistry,
	status observability.ProviderStatusRecorder,
	opts ...Option,
) *Adapter {
	if cfg.DefaultConfidence <= 0 {
		cfg.DefaultConfidence = 0.80
	}
	if cfg.ConfidenceWeight <= 0 {
		cfg.ConfidenceWeight = 0.85
	}
	a := &Adapter{
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
	for _, o := range opts {
		o(a)
	}
	return a
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

// Capabilities — odds + historical odds ONLY. The Odds API does not
// serve fixtures/results/standings in a form this adapter consumes.
func Capabilities() source.ProviderCapability {
	return source.ProviderCapability{
		SupportsOdds:           true,
		SupportsHistoricalOdds: true,
	}
}

// FetchCompetitions lists the provider's sport_keys as reference data
// for the registry. NOT an event source.
func (a *Adapter) FetchCompetitions(ctx context.Context) ([]ports.CompetitionDescriptor, error) {
	start := time.Now()
	sports, err := a.client.Sports(ctx)
	a.recordStatus(start, err, "/v4/sports")
	if err != nil {
		return nil, fmt.Errorf("the_odds_api fetch competitions: %w", err)
	}
	out := make([]ports.CompetitionDescriptor, 0, len(sports))
	for _, s := range sports {
		if !s.Active {
			continue
		}
		out = append(out, ports.CompetitionDescriptor{
			ExternalID: s.Key,
			Name:       s.Title,
			SourceID:   SourceID,
		})
	}
	return out, nil
}

// FetchOdds returns the current bookmaker quotes for the requested
// competition as match.odds raw events.
//
// When a cache is installed, the upstream call is served through it:
// a hit avoids the API request entirely (quota saved), and concurrent
// fetches for the same (sport_key, markets, regions) collapse to one
// upstream call. The budget recorder + status recorder fire ONLY on a
// real upstream request (inside the loader), never on a cache hit.
func (a *Adapter) FetchOdds(
	ctx context.Context, req ports.OddsFetchRequest,
) ([]*event.RawSportsEvent, error) {
	sportKey, err := a.resolveSportKey(ctx, req.CompetitionID)
	if err != nil {
		return nil, err
	}
	const endpoint = "/v4/sports/{sport_key}/odds"

	events, err := a.fetchOddsCached(ctx, sportKey, req.Markets, req.Regions, endpoint)
	if err != nil {
		return nil, fmt.Errorf("the_odds_api odds: %w", err)
	}
	return a.mapEvents(ctx, req.CompetitionID, sportKey, endpoint, events, time.Now().UTC()), nil
}

// fetchOddsCached wraps the upstream Odds call with the optional cache.
func (a *Adapter) fetchOddsCached(
	ctx context.Context, sportKey string, markets, regions []string, endpoint string,
) ([]oddsEventDTO, error) {
	loader := func(ctx context.Context) ([]byte, error) {
		events, err := a.fetchOddsDirect(ctx, sportKey, markets, regions, endpoint)
		if err != nil {
			return nil, err
		}
		return json.Marshal(events)
	}

	if a.cache == nil {
		// No cache: loader returns marshaled events; decode once.
		raw, err := loader(ctx)
		if err != nil {
			return nil, err
		}
		return decodeEvents(raw)
	}

	raw, err := a.cache.Fetch(ctx, cacheKey(sportKey, markets, regions), loader)
	if err != nil {
		return nil, err
	}
	return decodeEvents(raw)
}

// fetchOddsDirect performs the real upstream request + records status
// and budget spend. This is the ONLY place an odds API request is
// counted.
func (a *Adapter) fetchOddsDirect(
	ctx context.Context, sportKey string, markets, regions []string, endpoint string,
) ([]oddsEventDTO, error) {
	start := time.Now()
	events, err := a.client.Odds(ctx, sportKey, markets, regions)
	a.recordStatus(start, err, endpoint)
	if err == nil && a.recorder != nil {
		a.recorder.RecordRequest(ctx, SourceID)
	}
	return events, err
}

func decodeEvents(raw []byte) ([]oddsEventDTO, error) {
	var events []oddsEventDTO
	if len(raw) == 0 {
		return nil, nil
	}
	if err := json.Unmarshal(raw, &events); err != nil {
		return nil, fmt.Errorf("the_odds_api: decode cached odds: %w", err)
	}
	return events, nil
}

// cacheKey is the request-granularity cache key. Markets/regions are
// normalised (sorted) so equivalent requests share a cache entry. The
// per-fixture quotes ride inside the cached response and are deduped
// downstream by the snapshot-unique external_match_id + change gate.
func cacheKey(sportKey string, markets, regions []string) string {
	return "odds:" + sportKey + "|m=" + normaliseList(markets) + "|r=" + normaliseList(regions)
}

func normaliseList(vals []string) string {
	cp := make([]string, 0, len(vals))
	for _, v := range vals {
		if s := strings.TrimSpace(v); s != "" {
			cp = append(cp, s)
		}
	}
	sort.Strings(cp)
	return strings.Join(cp, ",")
}

// FetchHistoricalOdds returns a single historical snapshot at req.To
// (falling back to req.From, then now). A full timeline backfill loop
// over [From,To] is a future sprint — the contract + plumbing are in
// place here.
func (a *Adapter) FetchHistoricalOdds(
	ctx context.Context, req ports.HistoricalOddsFetchRequest,
) ([]*event.RawSportsEvent, error) {
	sportKey, err := a.resolveSportKey(ctx, req.CompetitionID)
	if err != nil {
		return nil, err
	}
	const endpoint = "/v4/historical/sports/{sport_key}/odds"

	snapshotAt := req.To
	if snapshotAt.IsZero() {
		snapshotAt = req.From
	}
	if snapshotAt.IsZero() {
		snapshotAt = time.Now().UTC()
	}

	start := time.Now()
	resp, err := a.client.HistoricalOdds(ctx, sportKey, snapshotAt, req.Markets, req.Regions)
	a.recordStatus(start, err, endpoint)
	if err == nil && a.recorder != nil {
		a.recorder.RecordRequest(ctx, SourceID)
	}
	if err != nil {
		return nil, fmt.Errorf("the_odds_api historical odds: %w", err)
	}
	// The snapshot timestamp is authoritative for captured_at when a
	// market lacks its own last_update.
	return a.mapEvents(ctx, req.CompetitionID, sportKey, endpoint, resp.Data, resp.Timestamp), nil
}

func (a *Adapter) mapEvents(
	ctx context.Context,
	competitionID uuid.UUID,
	sportKey, endpoint string,
	events []oddsEventDTO,
	fallbackCapture time.Time,
) []*event.RawSportsEvent {
	logger := log.Ctx(ctx)
	out := make([]*event.RawSportsEvent, 0, len(events))
	for _, e := range events {
		// Feed the kickoff tracker (dynamic polling) as a side effect —
		// no extra provider call.
		if a.scheduleObserver != nil && !e.CommenceTime.IsZero() {
			a.scheduleObserver.ObserveKickoff(ctx, competitionID, e.ID, e.CommenceTime)
		}
		raws, errs := a.mapper.MapOddsEvent(competitionID, sportKey, endpoint, e, fallbackCapture)
		for _, err := range errs {
			logger.Warn().Err(err).
				Str("provider", SourceID).
				Str("external_event_id", e.ID).
				Msg("the_odds_api_quote_skipped")
		}
		out = append(out, raws...)
	}
	return out
}

// FetchFixtures — not served by this provider. Capability filter keeps
// the scheduler from ever calling it; returns empty defensively.
func (a *Adapter) FetchFixtures(
	_ context.Context, _ ports.FixtureFetchRequest,
) ([]*event.RawSportsEvent, error) {
	return nil, nil
}

// FetchStandings — not served by this provider. See FetchFixtures.
func (a *Adapter) FetchStandings(
	_ context.Context, _ ports.StandingsFetchRequest,
) ([]*event.RawSportsEvent, error) {
	return nil, nil
}

func (a *Adapter) Health() ports.HealthSnapshot {
	return a.status.Snapshot(SourceID)
}

// resolveSportKey translates the Hub's canonical competition UUID into
// The Odds API sport_key via the shared CompetitionRegistry — the same
// mechanism API-Football + football-data use. Missing mapping → typed
// error so the runner logs + fails the job without crashing.
func (a *Adapter) resolveSportKey(
	ctx context.Context, competitionID uuid.UUID,
) (string, error) {
	sportKey, err := a.registry.GetExternalIDForSource(ctx, competitionID, SourceID)
	if err != nil {
		return "", fmt.Errorf("the_odds_api: no sport_key mapping for competition %s: %w",
			competitionID, err)
	}
	if sportKey == "" {
		return "", fmt.Errorf("the_odds_api: empty sport_key mapping for competition %s", competitionID)
	}
	return sportKey, nil
}

func (a *Adapter) recordStatus(start time.Time, err error, endpoint string) {
	latency := time.Since(start)
	if err != nil {
		a.status.RecordFailure(SourceID, latency, fmt.Errorf("%s: %w", endpoint, err))
		return
	}
	a.status.RecordSuccess(SourceID, latency)
}

var (
	_ ports.SourceAdapter         = (*Adapter)(nil)
	_ ports.OddsAdapter           = (*Adapter)(nil)
	_ ports.HistoricalOddsAdapter = (*Adapter)(nil)
)
