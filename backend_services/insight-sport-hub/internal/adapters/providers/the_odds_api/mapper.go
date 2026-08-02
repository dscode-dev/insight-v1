// Mapper — pure DTO → RawSportsEvent translation. No I/O.
//
// Event type emitted:
//
//	match.odds — ONE per (match, bookmaker, market) snapshot.
//
// History-preservation rule (this is the crux of the odds pipeline):
// odds change continuously and EVERY snapshot must survive as its own
// canonical event. The Hub collapses raws that share an Identity
// (sport, competition, match_id, event_type) into one canonical, so to
// keep every snapshot distinct the raw's external_match_id encodes the
// capture instant (+ bookmaker + market). That makes the derived
// match_id unique per snapshot, so the canonicalization layer never
// overwrites an earlier price.
//
// The STABLE per-match identifier downstream consumers group a
// timeline by lives in the payload under "match_id" (a deterministic
// UUIDv5 over the provider's event id) — NOT the canonical envelope's
// snapshot-scoped match_id. Re-fetching an unchanged snapshot yields
// the same external_match_id, so identical re-reads dedup instead of
// inflating the history with duplicates.
package the_odds_api

import (
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/sport"
)

// matchIDNamespace — stable namespace for the payload's per-match
// UUIDv5. Distinct from the Hub's internal canonicalization namespace
// because this id is a grouping key for the odds timeline, not a
// canonical match identity.
var matchIDNamespace = uuid.MustParse("0a7c8d11-4f2b-5d6e-9a3c-2f1b7e8d9c01")

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

// MapOddsEvent fans one provider event out into one RawSportsEvent per
// (bookmaker, market) quote. `competitionID` is the Hub's canonical
// UUID (resolved by the adapter via the CompetitionRegistry).
//
// `fallbackCapture` is used when a market/bookmaker carries no
// last_update (defensive — the provider normally sets it).
//
// Per-quote construction failures are skipped (returned in the error
// slice for logging) so one malformed market never bins the batch.
func (m *mapper) MapOddsEvent(
	competitionID uuid.UUID,
	sportKey, endpoint string,
	dto oddsEventDTO,
	fallbackCapture time.Time,
) ([]*event.RawSportsEvent, []error) {
	if fallbackCapture.IsZero() {
		fallbackCapture = time.Now().UTC()
	}
	stableMatchID := uuid.NewSHA1(
		matchIDNamespace, []byte(m.sourceID+"::match::"+dto.ID),
	)

	raws := make([]*event.RawSportsEvent, 0, len(dto.Bookmakers))
	var errs []error

	for _, bk := range dto.Bookmakers {
		for _, mk := range bk.Markets {
			capturedAt := mk.LastUpdate
			if capturedAt.IsZero() {
				capturedAt = bk.LastUpdate
			}
			if capturedAt.IsZero() {
				capturedAt = fallbackCapture
			}
			capturedAt = capturedAt.UTC()

			payload := m.oddsPayload(competitionID, stableMatchID, sportKey, dto, bk, mk, capturedAt)

			// external_match_id is snapshot-unique → preserves history.
			externalMatchID := fmt.Sprintf(
				"odds:%s:%s:%s:%d",
				dto.ID, bk.Key, mk.Key, capturedAt.Unix(),
			)

			raw, err := event.NewRaw(
				uuid.New(),
				m.sourceRef(capturedAt, endpoint),
				sport.Football,
				competitionID,
				externalMatchID,
				"match.odds",
				capturedAt,
				payload,
				m.defaultConfidence,
			)
			if err != nil {
				errs = append(errs, fmt.Errorf(
					"map odds %s/%s/%s: %w", dto.ID, bk.Key, mk.Key, err))
				continue
			}
			raws = append(raws, raw)
		}
	}
	return raws, errs
}

// oddsPayload builds the normalized canonical odds payload. The
// h2h home/draw/away prices are surfaced as top-level numeric fields
// (the foundational shape Atlas's feature builder reads); the full
// outcome list is always preserved for non-h2h markets + audit.
func (m *mapper) oddsPayload(
	competitionID, stableMatchID uuid.UUID,
	sportKey string,
	dto oddsEventDTO,
	bk bookmakerDTO,
	mk marketDTO,
	capturedAt time.Time,
) map[string]any {
	outcomes := make([]map[string]any, 0, len(mk.Outcomes))
	for _, o := range mk.Outcomes {
		entry := map[string]any{"name": o.Name, "price": o.Price}
		if o.Point != nil {
			entry["point"] = *o.Point
		}
		outcomes = append(outcomes, entry)
	}

	payload := map[string]any{
		"provider":          m.sourceID,
		"competition_id":    competitionID.String(),
		"match_id":          stableMatchID.String(),
		"market":            mk.Key,
		"bookmaker":         bk.Key,
		"bookmaker_name":    bk.Title,
		"captured_at":       capturedAt.Format(time.RFC3339),
		"sport_key":         sportKey,
		"home_team":         dto.HomeTeam,
		"away_team":         dto.AwayTeam,
		"commence_time":     dto.CommenceTime.UTC().Format(time.RFC3339),
		"external_event_id": dto.ID,
		"outcomes":          outcomes,
	}

	// h2h moneyline → home/draw/away by matching outcome names.
	if strings.EqualFold(mk.Key, "h2h") {
		for _, o := range mk.Outcomes {
			switch {
			case strings.EqualFold(o.Name, dto.HomeTeam):
				payload["home"] = o.Price
			case strings.EqualFold(o.Name, dto.AwayTeam):
				payload["away"] = o.Price
			case strings.EqualFold(o.Name, "Draw"):
				payload["draw"] = o.Price
			}
		}
	}
	return payload
}
