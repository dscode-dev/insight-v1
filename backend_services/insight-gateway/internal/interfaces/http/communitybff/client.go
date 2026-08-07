// FEATURE-COMMUNITIES-V1 Stage 2 — Social boundary + proto→DTO mapping.
//
// SocialGateway is the internal seam the orchestrator depends on (fakeable in
// tests). The real adapter wraps the shared social.v1 gRPC clients. The
// inbound request context flows through verbatim, so the ONE correlation id
// (carried by the gRPC metadata interceptor) is reused across the fan-out and
// client disconnect / global timeout cancels every in-flight upstream call.
//
// Mapping proto → public DTO happens ONLY here: nothing from social.v1 leaks
// past this file.
package communitybff

import (
	"context"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
)

type SocialGateway interface {
	GetCommunity(ctx context.Context, id string) (*socialv1.Community, error)
	GetStats(ctx context.Context, id string) (*socialv1.CommunityStats, error)
	GetMembership(ctx context.Context, communityID, userID string) (*socialv1.CommunityMember, error)
	ListMembers(ctx context.Context, communityID, cursor string, limit int32, role *socialv1.CommunityRole) (*socialv1.ListCommunityMembersResponse, error)
	ListDiscussions(ctx context.Context, communityID, cursor string, limit int32) (*socialv1.ListDiscussionsResponse, error)
	Join(ctx context.Context, communityID, userID string) (*socialv1.CommunityMember, error)
	Leave(ctx context.Context, communityID, userID string) error
}

// grpcGateway adapts the shared social gRPC clients to SocialGateway.
type grpcGateway struct {
	community  socialv1.CommunityServiceClient
	discussion socialv1.DiscussionServiceClient
}

// NewGRPCGateway builds the Social adapter from the shared service clients.
func NewGRPCGateway(c socialv1.CommunityServiceClient, d socialv1.DiscussionServiceClient) SocialGateway {
	return &grpcGateway{community: c, discussion: d}
}

func (g *grpcGateway) GetCommunity(ctx context.Context, id string) (*socialv1.Community, error) {
	return g.community.Get(ctx, &socialv1.GetCommunityRequest{Id: id})
}

func (g *grpcGateway) GetStats(ctx context.Context, id string) (*socialv1.CommunityStats, error) {
	return g.community.GetStats(ctx, &socialv1.GetCommunityStatsRequest{CommunityId: id})
}

func (g *grpcGateway) GetMembership(ctx context.Context, communityID, userID string) (*socialv1.CommunityMember, error) {
	return g.community.GetMembership(ctx, &socialv1.GetCommunityMembershipRequest{
		CommunityId: communityID, UserId: userID,
	})
}

func (g *grpcGateway) ListMembers(ctx context.Context, communityID, cursor string, limit int32, role *socialv1.CommunityRole) (*socialv1.ListCommunityMembersResponse, error) {
	req := &socialv1.ListCommunityMembersRequest{CommunityId: communityID}
	if limit > 0 {
		req.Limit = &limit
	}
	if cursor != "" {
		req.Cursor = &cursor
	}
	if role != nil {
		req.Role = role
	}
	return g.community.ListMembers(ctx, req)
}

func (g *grpcGateway) ListDiscussions(ctx context.Context, communityID, cursor string, limit int32) (*socialv1.ListDiscussionsResponse, error) {
	req := &socialv1.ListDiscussionsRequest{CommunityId: communityID}
	if limit > 0 {
		req.Limit = &limit
	}
	if cursor != "" {
		req.Cursor = &cursor
	}
	return g.discussion.ListForCommunity(ctx, req)
}

func (g *grpcGateway) Join(ctx context.Context, communityID, userID string) (*socialv1.CommunityMember, error) {
	return g.community.Join(ctx, &socialv1.JoinCommunityRequest{CommunityId: communityID, UserId: userID})
}

func (g *grpcGateway) Leave(ctx context.Context, communityID, userID string) error {
	_, err := g.community.Leave(ctx, &socialv1.LeaveCommunityRequest{CommunityId: communityID, UserId: userID})
	return err
}

// ---- proto → public DTO mapping (nothing else may leak) ----

func kindToWire(k socialv1.CommunityKind) string {
	switch k {
	case socialv1.CommunityKind_COMMUNITY_KIND_COMPETITION:
		return "competition"
	case socialv1.CommunityKind_COMMUNITY_KIND_TOPIC:
		return "topic"
	default:
		return "unspecified"
	}
}

func roleToWire(r socialv1.CommunityRole) string {
	switch r {
	case socialv1.CommunityRole_COMMUNITY_ROLE_OWNER:
		return roleOwner
	case socialv1.CommunityRole_COMMUNITY_ROLE_ADMIN:
		return roleAdmin
	case socialv1.CommunityRole_COMMUNITY_ROLE_MODERATOR:
		return roleModerator
	case socialv1.CommunityRole_COMMUNITY_ROLE_MEMBER:
		return roleMember
	default:
		return roleNone
	}
}

// roleFromWire maps a client-supplied ?role= filter to the proto enum. Unknown
// / empty => nil (no filter).
func roleFromWire(s string) *socialv1.CommunityRole {
	var r socialv1.CommunityRole
	switch s {
	case roleOwner:
		r = socialv1.CommunityRole_COMMUNITY_ROLE_OWNER
	case roleAdmin:
		r = socialv1.CommunityRole_COMMUNITY_ROLE_ADMIN
	case roleModerator:
		r = socialv1.CommunityRole_COMMUNITY_ROLE_MODERATOR
	case roleMember:
		r = socialv1.CommunityRole_COMMUNITY_ROLE_MEMBER
	default:
		return nil
	}
	return &r
}

// communityCore maps the community proto to the header portion of the detail.
// Communities have no avatar/banner in the domain today → honest empty strings
// (documented, never fabricated). description = the community topic.
func communityCore(c *socialv1.Community) Detail {
	return Detail{
		ID:               c.Id,
		Slug:             c.Slug,
		Name:             c.Name,
		Description:      c.Topic,
		AvatarURL:        "",
		BannerURL:        "",
		AccentColor:      c.AccentColor,
		Kind:             kindToWire(c.Kind),
		Privacy:          "public", // only value in V1 — honest, not fabricated
		DeepLink:         communityDeepLink(c.Id),
		MemberCount:      c.MemberCount,
		OnlineCount:      c.ActiveNow,
		OwnerAssigned:    c.OwnerUserId != nil && *c.OwnerUserId != "",
		ViewerRole:       roleNone,
		MembershipStatus: statusNotMember,
	}
}

func memberProfileToDTO(m *socialv1.CommunityMemberProfile) Member {
	return Member{
		UserID:      m.UserId,
		Username:    m.Username,
		DisplayName: m.DisplayName,
		Initials:    m.Initials,
		AccentColor: m.AccentColor,
		AvatarURL:   m.AvatarUrl,
		Reputation:  m.Reputation,
		Role:        roleToWire(m.Role),
		DeepLink:    userDeepLink(m.UserId),
	}
}

func discussionToDTO(d *socialv1.Discussion) Discussion {
	out := Discussion{
		ID:            d.Id,
		CommunityID:   d.CommunityId,
		AuthorID:      d.AuthorId,
		Title:         d.Title,
		ReplyCount:    d.ReplyCount,
		ReactionCount: d.ReactionCount,
		DeepLink:      discussionDeepLink(d.Id),
	}
	if d.LastActivityTs != nil {
		out.LastActivityTs = d.LastActivityTs.AsTime().UTC().Format("2006-01-02T15:04:05Z07:00")
	}
	return out
}
