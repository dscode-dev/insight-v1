// FEATURE-COMMUNITIES-V1 Stage 2 — Community Detail orchestrator.
//
// The detail is an AGGREGATE built by fanning out to Social in parallel:
//   - GetCommunity   (CRITICAL — its failure is the request's error, e.g. 404)
//   - GetStats       (non-critical — failure => partial, counters degrade)
//   - GetMembership  (non-critical, per-viewer — NotFound is the normal
//                     "not_member" state, NOT a failure)
//
// All three share the inbound context: the ONE correlation id is reused and a
// client disconnect / global timeout cancels every in-flight call. The join is
// a WaitGroup (no orphan goroutines). Partial is HONEST: a degraded section is
// named in failed_sections and never silently presented as complete.
package communitybff

import (
	"context"
	"sync"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

type Aggregator struct {
	social  SocialGateway
	metrics *Metrics
}

func NewAggregator(social SocialGateway, m *Metrics) *Aggregator {
	return &Aggregator{social: social, metrics: m}
}

// Detail composes the aggregate for communityID as seen by viewerID.
// A nil error with d.Partial=true means the core loaded but a section degraded.
// A non-nil error means the CORE community failed (mapped to HTTP by the
// handler — NotFound => 404).
func (a *Aggregator) Detail(ctx context.Context, communityID, viewerID string, statsBody []byte, cacheStats func([]byte)) (Detail, error) {
	var (
		wg        sync.WaitGroup
		comm      *socialv1.Community
		commErr   error
		stats     *socialv1.CommunityStats
		statsErr  error
		viewer    *socialv1.CommunityMember
		viewerErr error
	)

	wg.Add(1)
	go func() { defer wg.Done(); comm, commErr = a.social.GetCommunity(ctx, communityID) }()

	// Stats: skip the upstream call entirely on a cache hit.
	if statsBody == nil {
		wg.Add(1)
		go func() { defer wg.Done(); stats, statsErr = a.social.GetStats(ctx, communityID) }()
	}

	if viewerID != "" {
		wg.Add(1)
		go func() { defer wg.Done(); viewer, viewerErr = a.social.GetMembership(ctx, communityID, viewerID) }()
	}
	wg.Wait()

	// Critical: community core.
	if commErr != nil {
		return Detail{}, commErr
	}
	d := communityCore(comm)

	// Stats section (cache hit, live, or degraded).
	switch {
	case statsBody != nil:
		if rc, mc, dc, ok := decodeCachedStats(statsBody); ok {
			d.RoleCounts, d.MemberCount, d.DiscussionCount = rc, mc, dc
		}
	case statsErr != nil:
		d.Partial = true
		d.FailedSections = append(d.FailedSections, "stats")
		// counters degrade to what the community core already carries
		// (member_count/online_count); role_counts/discussion_count stay zero.
	case stats != nil:
		d.MemberCount = stats.MemberCount
		d.DiscussionCount = stats.DiscussionCount
		if stats.RoleCounts != nil {
			d.RoleCounts = RoleCounts{
				Owner: stats.RoleCounts.Owner, Admin: stats.RoleCounts.Admin,
				Moderator: stats.RoleCounts.Moderator, Member: stats.RoleCounts.Member,
			}
		}
		if cacheStats != nil {
			cacheStats(encodeCacheStats(d.RoleCounts, d.MemberCount, d.DiscussionCount))
		}
	}

	// Viewer section.
	if viewerID != "" {
		switch {
		case viewerErr != nil && isNotFound(viewerErr):
			// Normal: not a member. Not partial.
			d.ViewerRole = roleNone
			d.MembershipStatus = statusNotMember
		case viewerErr != nil:
			// Could not verify membership — best-effort not_member + partial.
			d.Partial = true
			d.FailedSections = append(d.FailedSections, "membership")
			d.ViewerRole = roleNone
			d.MembershipStatus = statusNotMember
		case viewer != nil:
			d.ViewerRole = roleToWire(viewer.Role)
			d.MembershipStatus = statusMember
		}
	}

	isMember := d.MembershipStatus == statusMember
	d.Capabilities = capabilitiesFor(d.ViewerRole, isMember, d.Privacy == "public")

	if d.Partial {
		a.metrics.partialInc()
	}
	return d, nil
}

func isNotFound(err error) bool {
	if s, ok := status.FromError(err); ok {
		return s.Code() == codes.NotFound
	}
	return false
}
