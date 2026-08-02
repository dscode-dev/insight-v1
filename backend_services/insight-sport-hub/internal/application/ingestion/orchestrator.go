// Package ingestion — IngestionOrchestrator.
//
// Wires every Sprint 1 application service into the canonical
// pipeline:
//
//	adapter  ─►  NormalizerService            (provider → RawSportsEvent)
//	             ↓
//	             ValidationService            (quarantine bad raws)
//	             ↓                                ↘ if rejected ─► persist raw + skip
//	             RawEventRepository.Insert    (persist raw)
//	             ↓
//	             CanonicalizationService      (build/merge canonical)
//	             ↓
//	             ConflictDetectionService     (status assignment)
//	             ↓
//	             ConfidenceService            (compute confidence)
//	             ↓
//	             CanonicalEventRepository.Upsert
//	             ↓
//	             LineageRepository.Link
//	             ↓
//	             PublishingService.Publish    (no-op in Sprint 1)
//
// The orchestrator is the ONLY place that knows the full pipeline.
// Adapters call Ingest with a single NormalizedInput; everything
// else cascades.
//
// Errors at any step quarantine the raw + log; transient infra
// failures bubble up so the caller can retry. The distinction is
// driven by the Decision type from validation + typed errors from
// the repos.
package ingestion

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog/log"

	appcanon "github.com/konoha-labs/insight-sports-hub/internal/application/canonicalization"
	appconfidence "github.com/konoha-labs/insight-sports-hub/internal/application/confidence"
	appconflict "github.com/konoha-labs/insight-sports-hub/internal/application/conflict"
	"github.com/konoha-labs/insight-sports-hub/internal/application/identity"
	appnorm "github.com/konoha-labs/insight-sports-hub/internal/application/normalization"
	apppub "github.com/konoha-labs/insight-sports-hub/internal/application/publishing"
	appval "github.com/konoha-labs/insight-sports-hub/internal/application/validation"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
	"github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// Result is what Ingest returns. Quarantined == true short-circuits
// the canonical path; the raw is still persisted (audit).
type Result struct {
	RawEventID       uuid.UUID
	CanonicalEventID uuid.UUID
	Quarantined      bool
	QuarantineReason appval.QuarantineReason
	Conflict         bool
	Confidence       float64
}

type Orchestrator struct {
	norm        *appnorm.Service
	val         *appval.Service
	canon       *appcanon.Service
	confl       *appconflict.Service
	conf        *appconfidence.Service
	pub         *apppub.Service
	rawRepo     ports.RawEventRepository
	canonRepo   ports.CanonicalEventRepository
	lineageRepo ports.LineageRepository
	sourceRepo  ports.SourceRepository
	metrics     ports.Metrics
	identity    *identity.Resolver // Sprint 6.2 — optional, nil = off
}

// Deps bundles the orchestrator's dependencies. main.go fills this
// at the composition root. Splitting it from the constructor keeps
// the call site readable.
type Deps struct {
	Normalizer               *appnorm.Service
	Validation               *appval.Service
	Canonicalization         *appcanon.Service
	ConflictDetection        *appconflict.Service
	Confidence               *appconfidence.Service
	Publishing               *apppub.Service
	RawEventRepository       ports.RawEventRepository
	CanonicalEventRepository ports.CanonicalEventRepository
	LineageRepository        ports.LineageRepository
	SourceRepository         ports.SourceRepository
	Metrics                  ports.Metrics
	// Sprint 6.2 — optional cross-provider identity resolver. When set,
	// every canonical event is stamped with a canonical_match_id so
	// downstream (Atlas) can unify observations of the same fixture
	// across providers. Nil preserves Sprint 6.1 behaviour exactly.
	IdentityResolver *identity.Resolver
}

func New(d Deps) *Orchestrator {
	return &Orchestrator{
		norm:        d.Normalizer,
		val:         d.Validation,
		canon:       d.Canonicalization,
		confl:       d.ConflictDetection,
		conf:        d.Confidence,
		pub:         d.Publishing,
		rawRepo:     d.RawEventRepository,
		canonRepo:   d.CanonicalEventRepository,
		lineageRepo: d.LineageRepository,
		sourceRepo:  d.SourceRepository,
		metrics:     d.Metrics,
		identity:    d.IdentityResolver,
	}
}

// Ingest is the entry point for callers that have NOT pre-built a
// RawSportsEvent (e.g. external cross-service ingestion via HTTP
// push in Sprint 3+). It runs the NormalizerService then hands off
// to processRaw which is shared with IngestRaw.
func (o *Orchestrator) Ingest(ctx context.Context, input appnorm.NormalizedInput) (Result, error) {
	raw, err := o.norm.Normalize(input)
	if err != nil {
		o.metrics.IncRejected("normalize_failed")
		return Result{Quarantined: true,
				QuarantineReason: appval.ReasonMissingSource}, // generic; see logs
			fmt.Errorf("ingest normalize: %w", err)
	}
	return o.processRaw(ctx, raw)
}

// IngestRaw is the entry point Sprint 2 provider adapters call.
// Adapters build the RawSportsEvent inside their own mapper; the raw
// is still routed through NormalizerService.NormalizeRaw (Sprint 2.1
// pass-through) so future cross-producer normalisation lands in one
// place — adapters, future internal bots, CrewAI/LangGraph producers
// all share the same architectural seam.
func (o *Orchestrator) IngestRaw(ctx context.Context, raw *event.RawSportsEvent) (Result, error) {
	if raw == nil {
		return Result{}, fmt.Errorf("ingest raw: nil event")
	}
	normalised, err := o.norm.NormalizeRaw(raw)
	if err != nil {
		o.metrics.IncRejected("normalize_raw_failed")
		return Result{}, fmt.Errorf("ingest raw normalize: %w", err)
	}
	return o.processRaw(ctx, normalised)
}

// processRaw is the post-normalization pipeline shared by both
// entry points.
func (o *Orchestrator) processRaw(ctx context.Context, raw *event.RawSportsEvent) (Result, error) {
	logger := log.Ctx(ctx)

	// 2. Validate
	decision := o.val.Validate(ctx, raw)
	if decision.Quarantined {
		logger.Warn().
			Str("raw_event_id", raw.RawEventID().String()).
			Str("reason", string(decision.Reason)).
			Str("detail", decision.Detail).
			Msg("raw_event_quarantined")
		// Persist the raw anyway (audit), then return early.
		_ = o.rawRepo.Insert(ctx, raw)
		return Result{
			RawEventID:       raw.RawEventID(),
			Quarantined:      true,
			QuarantineReason: decision.Reason,
		}, nil
	}

	// 3. Persist raw
	if err := o.rawRepo.Insert(ctx, raw); err != nil {
		if errors.Is(err, ports.ErrDuplicate) {
			o.metrics.IncRawDuplicate()
			return Result{
				RawEventID:       raw.RawEventID(),
				Quarantined:      true,
				QuarantineReason: appval.ReasonDuplicateRawEventID,
			}, nil
		}
		return Result{}, fmt.Errorf("ingest persist raw: %w", err)
	}
	o.metrics.IncRawIngested()

	// 4. Look up the canonical for this identity. Build new or merge.
	identity := identityOf(raw)
	existing, err := o.canonRepo.GetByIdentity(ctx, identity)
	switch {
	case err == nil:
		return o.mergeIntoExisting(ctx, existing, raw, identity)
	case errors.Is(err, ports.ErrNotFound):
		return o.buildNew(ctx, raw, identity)
	default:
		return Result{}, fmt.Errorf("ingest canonical lookup: %w", err)
	}
}

// buildNew handles the "first raw for this identity" path.
func (o *Orchestrator) buildNew(
	ctx context.Context,
	raw *event.RawSportsEvent,
	identity event.Identity,
) (Result, error) {
	sourcesMap, err := o.resolveSources([]*event.RawSportsEvent{raw})
	if err != nil {
		return Result{}, err
	}
	confidence := o.conf.Compute([]*event.RawSportsEvent{raw}, sourcesMap)

	canonID := uuid.New()
	canonical, err := o.canon.Build(canonID, []*event.RawSportsEvent{raw}, confidence)
	if err != nil {
		return Result{}, fmt.Errorf("ingest build canonical: %w", err)
	}
	o.stampCanonicalMatchID(ctx, canonical, raw)
	if err := o.canonRepo.Upsert(ctx, canonical); err != nil {
		return Result{}, fmt.Errorf("ingest upsert canonical: %w", err)
	}
	if err := o.lineageRepo.Link(ctx, canonical.EventID(), raw.RawEventID()); err != nil {
		return Result{}, fmt.Errorf("ingest link lineage: %w", err)
	}
	o.metrics.IncCanonicalUpserted()

	if err := o.pub.Publish(ctx, canonical); err != nil {
		// Publishing failure is non-fatal in Sprint 1 — noop publisher
		// can never fail, but the surface holds for Sprint 2.
		log.Ctx(ctx).Warn().Err(err).Msg("publish_failed_first_canonical")
	}

	_ = identity // identity is captured implicitly via canonical
	return Result{
		RawEventID:       raw.RawEventID(),
		CanonicalEventID: canonical.EventID(),
		Confidence:       canonical.Confidence(),
	}, nil
}

// mergeIntoExisting handles "we already have a canonical for this
// identity — extend it with the new raw".
func (o *Orchestrator) mergeIntoExisting(
	ctx context.Context,
	existing *event.CanonicalSportsEvent,
	raw *event.RawSportsEvent,
	identity event.Identity,
) (Result, error) {
	if existing.Status().IsTerminal() {
		// rejected/stale canonicals shouldn't receive new raws —
		// but if a late-arriving raw lands, treat it as informational:
		// log + persist the raw + return.
		log.Ctx(ctx).Info().
			Str("canonical_event_id", existing.EventID().String()).
			Str("status", string(existing.Status())).
			Msg("late_raw_for_terminal_canonical")
		return Result{
			RawEventID:       raw.RawEventID(),
			CanonicalEventID: existing.EventID(),
		}, nil
	}

	// Pull all known raws for this identity so the conflict + confidence
	// services see the full picture, not just the latest one.
	allRaws, err := o.rawRepo.ListForIdentity(ctx, identity)
	if err != nil {
		return Result{}, fmt.Errorf("ingest list raws: %w", err)
	}

	sourcesMap, err := o.resolveSources(allRaws)
	if err != nil {
		return Result{}, err
	}
	confidence := o.conf.Compute(allRaws, sourcesMap)

	if err := o.canon.MergeInto(existing, []*event.RawSportsEvent{raw}, confidence); err != nil {
		return Result{}, fmt.Errorf("ingest merge canonical: %w", err)
	}
	o.stampCanonicalMatchID(ctx, existing, raw)

	// Conflict re-evaluation across the full raw set.
	cr := o.confl.Detect(allRaws, existing)
	if cr.Conflicts {
		_ = existing.UpdateStatus(event.StatusConflicting)
	} else if existing.SourceCount() >= 2 && !existing.Status().IsTerminal() {
		_ = existing.UpdateStatus(event.StatusConfirmed)
	}

	if err := o.canonRepo.Upsert(ctx, existing); err != nil {
		return Result{}, fmt.Errorf("ingest upsert merged canonical: %w", err)
	}
	if err := o.lineageRepo.Link(ctx, existing.EventID(), raw.RawEventID()); err != nil {
		return Result{}, fmt.Errorf("ingest link lineage: %w", err)
	}
	o.metrics.IncCanonicalUpserted()

	if err := o.pub.Publish(ctx, existing); err != nil {
		log.Ctx(ctx).Warn().Err(err).Msg("publish_failed_merged_canonical")
	}

	return Result{
		RawEventID:       raw.RawEventID(),
		CanonicalEventID: existing.EventID(),
		Conflict:         cr.Conflicts,
		Confidence:       existing.Confidence(),
	}, nil
}

// resolveSources looks up the registered Source for each raw's
// SourceRef.SourceID. Unregistered refs are tolerated — the
// confidence policy handles a nil entry gracefully.
//
// One DB call per distinct SourceID. Cheap because the source
// catalogue is small (typically < 50 entries even at scale).
func (o *Orchestrator) resolveSources(
	raws []*event.RawSportsEvent,
) (map[string]*source.Source, error) {
	out := map[string]*source.Source{}
	seen := map[string]struct{}{}
	for _, r := range raws {
		sid := r.Source().SourceID
		if _, ok := seen[sid]; ok {
			continue
		}
		seen[sid] = struct{}{}
		// Lookup by NAME first (source_id is the wire-facing slug
		// — typically the registered name). Repository's GetByName
		// returns ErrNotFound for unregistered refs; we tolerate.
		src, err := o.sourceRepo.GetByName(context.Background(), sid)
		if err != nil {
			if errors.Is(err, ports.ErrNotFound) {
				continue
			}
			return nil, fmt.Errorf("resolve source %q: %w", sid, err)
		}
		out[sid] = src
	}
	return out, nil
}

func identityOf(r *event.RawSportsEvent) event.Identity {
	return event.Identity{
		Sport:         r.Sport(),
		CompetitionID: r.CompetitionID(),
		MatchID:       deriveMatchID(r),
		EventType:     r.EventType(),
	}
}

// stampCanonicalMatchID resolves the cross-provider canonical match id
// from the raw observation and writes it into the canonical payload
// (additive — the existing per-provider match_id is untouched). Best
// effort: a missing resolver, insufficient identity signals, or a
// resolver error all leave the payload unchanged rather than failing
// ingestion.
func (o *Orchestrator) stampCanonicalMatchID(
	ctx context.Context, c *event.CanonicalSportsEvent, raw *event.RawSportsEvent,
) {
	if o.identity == nil {
		return
	}
	pmi, ok := providerIdentityFromRaw(raw)
	if !ok {
		return
	}
	canonicalID, err := o.identity.Resolve(ctx, pmi)
	if err != nil {
		log.Ctx(ctx).Warn().Err(err).
			Str("provider", pmi.Provider).
			Msg("canonical_match_id_resolve_failed")
		return
	}
	payload := c.Payload()
	payload["canonical_match_id"] = canonicalID.String()
	_ = c.ReplacePayload(payload)
}

// providerIdentityFromRaw extracts the identity signals from a raw
// event's payload. Handles both the flat (the_odds_api: home_team is a
// string) and nested ({"name": ...} for api_football / football_data)
// team shapes, and either commence_time or scheduled_at for kickoff.
// Returns false when the home/away signal is absent (e.g. standings).
func providerIdentityFromRaw(raw *event.RawSportsEvent) (identity.ProviderMatchIdentity, bool) {
	p := raw.Payload()
	home := teamName(p["home_team"])
	away := teamName(p["away_team"])
	if home == "" || away == "" {
		return identity.ProviderMatchIdentity{}, false
	}
	return identity.ProviderMatchIdentity{
		Provider:      raw.Source().SourceID,
		ExternalID:    stableExternalID(raw, p),
		CompetitionID: raw.CompetitionID(),
		HomeTeam:      home,
		AwayTeam:      away,
		Kickoff:       kickoffOf(p),
	}, true
}

// teamName reads a team field that may be a plain string or a nested
// object carrying a "name".
func teamName(v any) string {
	switch t := v.(type) {
	case string:
		return t
	case map[string]any:
		if n, ok := t["name"].(string); ok {
			return n
		}
	}
	return ""
}

// stableExternalID prefers a stable per-match provider id when the raw's
// own external_match_id is snapshot-scoped (odds). Keeps the alias table
// keyed on the real match, not the snapshot.
func stableExternalID(raw *event.RawSportsEvent, p map[string]any) string {
	if ext, ok := p["external_event_id"].(string); ok && ext != "" {
		return ext
	}
	return raw.ExternalMatchID()
}

// kickoffOf parses the scheduled kickoff from whichever field the
// provider supplied. Zero time when none is parseable.
func kickoffOf(p map[string]any) time.Time {
	for _, key := range []string{"commence_time", "scheduled_at"} {
		if s, ok := p[key].(string); ok && s != "" {
			if t, err := time.Parse(time.RFC3339, s); err == nil {
				return t.UTC()
			}
		}
	}
	return time.Time{}
}

// deriveMatchID mirrors canonicalization.deriveMatchID — same
// namespace, same algorithm. Documented as a Sprint 1 placeholder.
var matchIDNamespace = uuid.MustParse("8e2e3f9c-3d23-4ad1-9c1e-2b91a1f9c6f0")

func deriveMatchID(r *event.RawSportsEvent) uuid.UUID {
	return uuid.NewSHA1(matchIDNamespace, []byte(r.Source().SourceID+"::"+r.ExternalMatchID()))
}
