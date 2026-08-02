// Planner — Sprint 3.
//
// Pure decision logic: given the current state of the world
// (registered providers, enabled competitions, configured poll
// policies, last-execution map) produces the SyncJobs that are due
// right now. Stateless from the outside — the only mutable state is
// the internal "next due at" map; tests drive it via a fake clock.
//
// Architectural rule (Sprint 2.1):
//
//	Capability checks belong EXCLUSIVELY to the Planner. Adapters
//	expose `Identity().Capabilities`; nothing downstream branches on
//	provider slug. Adding a new sync_type is a domain change, NOT a
//	planner change.
//
// What the Planner does NOT do:
//   - call adapters (Runner's job)
//   - enforce rate limits (RateLimiter's job)
//   - persist jobs (Sprint 3 queue is ephemeral)
package scheduler

import (
	"context"
	"sync"
	"time"

	"github.com/google/uuid"

	syncdom "github.com/konoha-labs/insight-sports-hub/internal/domain/sync"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

// Lane is the natural scheduling unit a SchedulingAdvisor reasons
// about: one (provider, sync_type, competition) tuple.
type Lane struct {
	ProviderID    string
	SyncType      syncdom.SyncType
	CompetitionID uuid.UUID
}

// Advice is a SchedulingAdvisor's verdict for a lane on this tick.
type Advice struct {
	// Interval overrides the policy's static interval. When Skip is
	// true it is the re-check backoff (how long before the lane is
	// reconsidered). 0 means "use the base interval".
	Interval time.Duration
	// Skip suppresses emitting a job this tick (e.g. budget pressure).
	Skip bool
	// Reason is a short machine tag for logs/metrics ("budget_*").
	Reason string
}

// SchedulingAdvisor is the optional Sprint 6.1 hook that makes polling
// dynamic: kickoff-proximity windows, budget pressure, and operational
// mode all converge here. The Planner consults it (when set) to adjust
// each lane's effective interval and to skip low-priority lanes under
// budget pressure. A nil advisor preserves the static Sprint-3
// behaviour exactly.
type SchedulingAdvisor interface {
	Advise(ctx context.Context, lane Lane, base time.Duration, now time.Time) Advice
}

// Planner produces SyncJobs that are due at `now`.
type Planner struct {
	adapters     map[string]ports.SourceAdapter
	competitions ports.CompetitionRegistry
	// policies keyed by SourceID. Each entry is the full set of
	// PollPolicy rows for that provider — one per supported
	// sync_type. Adapters never see this map.
	policies map[string][]syncdom.PollPolicy
	clock    ports.Clock

	advisor SchedulingAdvisor

	mu      sync.Mutex
	nextDue map[planKey]time.Time
}

// SetAdvisor installs the dynamic scheduling advisor. Optional — the
// composition root calls this for providers that need budget/kickoff-
// aware polling (the_odds_api). Safe to leave unset.
func (p *Planner) SetAdvisor(a SchedulingAdvisor) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.advisor = a
}

// planKey is the natural key per scheduled lane:
// (provider, sync_type, competition). One job is in flight per key
// at a time — the next is only enqueued after the previous one's
// effective interval has elapsed.
type planKey struct {
	sourceID      string
	syncType      syncdom.SyncType
	competitionID uuid.UUID
}

// NewPlanner builds a planner. policies is keyed by SourceID.
func NewPlanner(
	adapters map[string]ports.SourceAdapter,
	competitions ports.CompetitionRegistry,
	policies map[string][]syncdom.PollPolicy,
	clock ports.Clock,
) *Planner {
	return &Planner{
		adapters:     adapters,
		competitions: competitions,
		policies:     policies,
		clock:        clock,
		nextDue:      map[planKey]time.Time{},
	}
}

// Plan returns the SyncJobs that are due at the current clock tick.
// A given (provider, sync_type, competition) emits AT MOST one job
// per call — even if the planner is invoked back-to-back, the next
// emission only happens after the policy's interval has elapsed.
//
// Errors loading the competition registry surface; per-job
// construction errors are logged via the supplied logger
// (defensively skipped, never propagated) because partial planning
// is preferable to dropping a full tick.
func (p *Planner) Plan(ctx context.Context) ([]syncdom.SyncJob, error) {
	competitions, err := p.competitions.List(ctx)
	if err != nil {
		return nil, err
	}

	p.mu.Lock()
	defer p.mu.Unlock()

	now := p.clock.Now()
	jobs := make([]syncdom.SyncJob, 0)

	for _, comp := range competitions {
		// Sprint 3 rule: disabled competitions generate zero jobs.
		if !comp.Enabled {
			continue
		}
		for sourceID, adapter := range p.adapters {
			caps := adapter.Identity().Capabilities
			policies := p.policies[sourceID]

			for _, policy := range policies {
				if !policy.Enabled {
					continue
				}
				// Capability filter — adapter can't serve this class,
				// so the planner emits no job for it. Sprint 3 spec:
				// "Do not generate jobs that the provider cannot
				// execute."
				if !caps.Supports(string(policy.SyncType)) {
					continue
				}

				key := planKey{
					sourceID:      sourceID,
					syncType:      policy.SyncType,
					competitionID: comp.ID,
				}
				next, ok := p.nextDue[key]
				if ok && now.Before(next) {
					continue
				}

				// Static baseline cadence.
				interval := policy.EffectiveInterval(false)

				// Sprint 6.1 — let the dynamic advisor adjust the lane:
				// kickoff-proximity window, budget pressure, mode. Skip
				// suppresses the job this tick but advances nextDue by
				// the advised backoff so the loop doesn't spin.
				if p.advisor != nil {
					adv := p.advisor.Advise(ctx,
						Lane{ProviderID: sourceID, SyncType: policy.SyncType, CompetitionID: comp.ID},
						interval, now)
					if adv.Interval > 0 {
						interval = adv.Interval
					}
					if adv.Skip {
						p.nextDue[key] = now.Add(interval)
						continue
					}
				}

				job, err := syncdom.NewSyncJob(
					syncdom.NewJobID(),
					sourceID,
					comp.ID,
					policy.SyncType,
					syncdom.PriorityNormal,
					now,
					nil,
				)
				if err != nil {
					// Construction failure means a policy/sync_type
					// mismatch slipped past the capability filter —
					// skip the lane without crashing the tick.
					continue
				}
				jobs = append(jobs, job)
				p.nextDue[key] = now.Add(interval)
			}
		}
	}
	return jobs, nil
}

// NextDueAt — exposed for tests + the /v1/scheduler/status endpoint.
// Returns the zero time when the lane has never run.
func (p *Planner) NextDueAt(sourceID string, st syncdom.SyncType, competitionID uuid.UUID) time.Time {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.nextDue[planKey{sourceID, st, competitionID}]
}
