// FEATURE-COMMUNITIES-V1 Stage 2 — orchestrator behaviour proofs: capabilities
// as the single authorization projection, honest partial semantics on the
// detail aggregate (never a members array), deep-link construction, stats cache
// codec, and per-user rate limiting.
package communitybff

import (
	"context"
	"errors"
	"testing"
	"time"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"github.com/prometheus/client_golang/prometheus"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// ---- fake Social boundary ----

type fakeSocial struct {
	community    *socialv1.Community
	communityErr error
	stats        *socialv1.CommunityStats
	statsErr     error
	member       *socialv1.CommunityMember
	memberErr    error
}

func (f *fakeSocial) GetCommunity(context.Context, string) (*socialv1.Community, error) {
	return f.community, f.communityErr
}
func (f *fakeSocial) GetStats(context.Context, string) (*socialv1.CommunityStats, error) {
	return f.stats, f.statsErr
}
func (f *fakeSocial) GetMembership(context.Context, string, string) (*socialv1.CommunityMember, error) {
	return f.member, f.memberErr
}
func (f *fakeSocial) ListMembers(context.Context, string, string, int32, *socialv1.CommunityRole) (*socialv1.ListCommunityMembersResponse, error) {
	return &socialv1.ListCommunityMembersResponse{}, nil
}
func (f *fakeSocial) ListDiscussions(context.Context, string, string, int32) (*socialv1.ListDiscussionsResponse, error) {
	return &socialv1.ListDiscussionsResponse{}, nil
}
func (f *fakeSocial) Join(context.Context, string, string) (*socialv1.CommunityMember, error) {
	return f.member, f.memberErr
}
func (f *fakeSocial) Leave(context.Context, string, string) error { return f.memberErr }

func testAgg(f SocialGateway) *Aggregator {
	return NewAggregator(f, NewMetrics(prometheus.NewRegistry()))
}

func baseCommunity() *socialv1.Community {
	owner := "11111111-1111-1111-1111-111111111111"
	return &socialv1.Community{
		Id: "c1", Slug: "tatica-fc", Name: "Tática FC", Topic: "4-3-3",
		Kind: socialv1.CommunityKind_COMMUNITY_KIND_TOPIC, AccentColor: "#5BA8FF",
		MemberCount: 10, ActiveNow: 3, OwnerUserId: &owner,
	}
}

// ---- capabilities matrix ----

func TestCapabilities_NotMemberCanOnlyJoin(t *testing.T) {
	c := capabilitiesFor(roleNone, false, true)
	if !c.CanJoin || c.CanLeave || c.CanCreateDiscussion || c.CanManageMembers {
		t.Fatalf("non-member may only join: %+v", c)
	}
	// A private community (not V1, but the gate must hold) blocks join.
	if capabilitiesFor(roleNone, false, false).CanJoin {
		t.Fatal("non-public community must not advertise can_join")
	}
}

func TestCapabilities_MemberParticipatesNotManages(t *testing.T) {
	c := capabilitiesFor(roleMember, true, true)
	if !c.CanCreateDiscussion || !c.CanLeave {
		t.Fatal("member can create discussions and leave")
	}
	if c.CanManageMembers || c.CanViewAdminPanel || c.CanDeleteDiscussion {
		t.Fatalf("member must not have privileged caps: %+v", c)
	}
}

func TestCapabilities_ModeratorDeletesButNotAdmin(t *testing.T) {
	c := capabilitiesFor(roleModerator, true, true)
	if !c.CanDeleteDiscussion {
		t.Fatal("moderator can delete discussions")
	}
	if c.CanManageMembers || c.CanManageSettings || c.CanViewAdminPanel {
		t.Fatal("moderator is not an admin")
	}
}

func TestCapabilities_AdminManages(t *testing.T) {
	c := capabilitiesFor(roleAdmin, true, true)
	if !(c.CanManageMembers && c.CanInviteMembers && c.CanManageSettings && c.CanViewAdminPanel && c.CanDeleteDiscussion && c.CanLeave) {
		t.Fatalf("admin lacks a capability: %+v", c)
	}
}

func TestCapabilities_OwnerCannotLeave(t *testing.T) {
	c := capabilitiesFor(roleOwner, true, true)
	if c.CanLeave {
		t.Fatal("owner MUST NOT be offered leave (ownership transfer is V1-absent)")
	}
	if !(c.CanManageMembers && c.CanViewAdminPanel) {
		t.Fatal("owner should have full management capabilities")
	}
}

// ---- detail aggregate: partial semantics ----

func TestDetail_StatsFailureIsPartialNotError(t *testing.T) {
	f := &fakeSocial{
		community: baseCommunity(),
		statsErr:  errors.New("stats down"),
		memberErr: status.Error(codes.NotFound, "not a member"),
	}
	d, err := testAgg(f).Detail(context.Background(), "c1", "u1", nil, nil)
	if err != nil {
		t.Fatalf("core loaded → no hard error, got %v", err)
	}
	if !d.Partial || len(d.FailedSections) == 0 || d.FailedSections[0] != "stats" {
		t.Fatalf("stats failure must be an honest partial: %+v", d)
	}
	// Counters degrade to the community core (member_count from the community).
	if d.MemberCount != 10 {
		t.Fatalf("member_count should degrade to community core, got %d", d.MemberCount)
	}
	// Not a member → normal state (this section is NOT partial).
	if d.MembershipStatus != statusNotMember {
		t.Fatalf("expected not_member, got %s", d.MembershipStatus)
	}
	// Never a members array on the detail.
	// (Compile-time: Detail has no Members field — enforced by the type.)
}

func TestDetail_CoreFailureIsError(t *testing.T) {
	f := &fakeSocial{communityErr: status.Error(codes.NotFound, "no community")}
	_, err := testAgg(f).Detail(context.Background(), "c1", "u1", nil, nil)
	if !isNotFound(err) {
		t.Fatalf("core community failure must surface as the request error, got %v", err)
	}
}

func TestDetail_ViewerRoleDrivesCapabilities(t *testing.T) {
	f := &fakeSocial{
		community: baseCommunity(),
		stats: &socialv1.CommunityStats{
			MemberCount: 10, DiscussionCount: 4,
			RoleCounts: &socialv1.RoleCounts{Owner: 1, Admin: 1, Moderator: 2, Member: 6},
		},
		member: &socialv1.CommunityMember{Role: socialv1.CommunityRole_COMMUNITY_ROLE_OWNER},
	}
	d, err := testAgg(f).Detail(context.Background(), "c1", "u1", nil, func([]byte) {})
	if err != nil {
		t.Fatal(err)
	}
	if d.ViewerRole != roleOwner || d.MembershipStatus != statusMember {
		t.Fatalf("owner viewer expected: %+v", d)
	}
	if d.Capabilities.CanLeave {
		t.Fatal("owner detail must not offer leave")
	}
	if d.RoleCounts.Member != 6 || d.DiscussionCount != 4 {
		t.Fatalf("role_counts/discussion_count from stats: %+v", d)
	}
	if d.Partial {
		t.Fatal("fully-loaded detail must not be partial")
	}
}

// ---- deep links (server-built) ----

func TestDeepLinks_ServerBuilt(t *testing.T) {
	if communityDeepLink("c1") != "/hub/community/c1" {
		t.Fatal("community deep link")
	}
	if userDeepLink("u1") != "/users/u1" {
		t.Fatal("user deep link")
	}
	if discussionDeepLink("d1") != "/discussion/d1" {
		t.Fatal("discussion deep link")
	}
}

// ---- members role filter mapping ----

func TestRoleFromWire_ProjectionOrNil(t *testing.T) {
	if roleFromWire("admin") == nil || *roleFromWire("admin") != socialv1.CommunityRole_COMMUNITY_ROLE_ADMIN {
		t.Fatal("admin projection")
	}
	if roleFromWire("") != nil || roleFromWire("bogus") != nil {
		t.Fatal("empty/unknown role => no filter (all members), not an error")
	}
}

// ---- stats cache codec + isolation ----

func TestStatsCache_CodecAndTTL(t *testing.T) {
	c := NewStatsCache(time.Minute, 10)
	now := time.Now()
	c.now = func() time.Time { return now }

	body := encodeCacheStats(RoleCounts{Owner: 1, Member: 5}, 6, 3)
	c.Set("c1", body)
	got, hit := c.Get("c1")
	if !hit {
		t.Fatal("expected cache hit")
	}
	rc, mc, dc, ok := decodeCachedStats(got)
	if !ok || rc.Owner != 1 || rc.Member != 5 || mc != 6 || dc != 3 {
		t.Fatalf("codec round-trip wrong: %+v %d %d", rc, mc, dc)
	}
	if _, hit := c.Get("c2"); hit {
		t.Fatal("different community must miss (per-community key)")
	}
	now = now.Add(2 * time.Minute)
	if _, hit := c.Get("c1"); hit {
		t.Fatal("expired entry must miss")
	}
}

// ---- rate limiter ----

func TestRateLimiter_PerUserWindow(t *testing.T) {
	l := newRateLimiter(2, time.Minute)
	now := time.Now()
	l.now = func() time.Time { return now }
	if !l.allow("u1") || !l.allow("u1") {
		t.Fatal("first 2 within budget pass")
	}
	if l.allow("u1") {
		t.Fatal("3rd in window limited")
	}
	if !l.allow("u2") {
		t.Fatal("limits are per-user")
	}
	now = now.Add(2 * time.Minute)
	if !l.allow("u1") {
		t.Fatal("window reset allows again")
	}
}
