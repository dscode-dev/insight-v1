// Community gRPC handler. Same shape as user.go — translate, call
// app service, map error to status. No business logic.
package grpc

import (
	"context"
	"errors"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/emptypb"
	"google.golang.org/protobuf/types/known/timestamppb"

	appcommunity "github.com/konoha-labs/insight-social/internal/application/community"
	domcommunity "github.com/konoha-labs/insight-social/internal/domain/community"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/pagination"
)

type CommunityServer struct {
	socialv1.UnimplementedCommunityServiceServer
	svc *appcommunity.Service
}

func NewCommunityServer(svc *appcommunity.Service) *CommunityServer {
	return &CommunityServer{svc: svc}
}

// ---- RPC methods ----

func (s *CommunityServer) List(ctx context.Context, req *socialv1.ListCommunitiesRequest) (*socialv1.ListCommunitiesResponse, error) {
	var kindFilter *domcommunity.Kind
	if req.Kind != nil {
		k := kindFromProto(req.GetKind())
		kindFilter = &k
	}
	limit := 0
	if req.Limit != nil {
		limit = int(req.GetLimit())
	}
	cursor := ""
	if req.Cursor != nil {
		cursor = req.GetCursor()
	}

	page, err := s.svc.List(ctx, kindFilter, sortFromProto(req.GetSort()), limit, cursor)
	if err != nil {
		return nil, mapCommunityErr(err)
	}
	out := make([]*socialv1.Community, 0, len(page.Communities))
	for _, c := range page.Communities {
		out = append(out, communityToProto(c))
	}
	resp := &socialv1.ListCommunitiesResponse{Communities: out}
	if page.NextCursor != "" {
		resp.NextCursor = &page.NextCursor
	}
	return resp, nil
}

// ListForUser — W2.2.1. user_id required; limit + cursor optional.
func (s *CommunityServer) ListForUser(ctx context.Context, req *socialv1.ListCommunitiesForUserRequest) (*socialv1.ListCommunitiesForUserResponse, error) {
	userID, err := parseUUID(req.GetUserId(), "user_id")
	if err != nil {
		return nil, err
	}
	limit := 0
	if req.Limit != nil {
		limit = int(req.GetLimit())
	}
	cursor := ""
	if req.Cursor != nil {
		cursor = req.GetCursor()
	}
	page, err := s.svc.ListForUser(ctx, userID, limit, cursor)
	if err != nil {
		return nil, mapCommunityErr(err)
	}
	out := make([]*socialv1.Community, 0, len(page.Communities))
	for _, c := range page.Communities {
		out = append(out, communityToProto(c))
	}
	resp := &socialv1.ListCommunitiesForUserResponse{Communities: out}
	if page.NextCursor != "" {
		resp.NextCursor = &page.NextCursor
	}
	return resp, nil
}

func (s *CommunityServer) Get(ctx context.Context, req *socialv1.GetCommunityRequest) (*socialv1.Community, error) {
	id, err := parseUUID(req.GetId(), "id")
	if err != nil {
		return nil, err
	}
	c, err := s.svc.Get(ctx, id)
	if err != nil {
		return nil, mapCommunityErr(err)
	}
	return communityToProto(c), nil
}

func (s *CommunityServer) CreateTopic(ctx context.Context, req *socialv1.CreateTopicCommunityRequest) (*socialv1.Community, error) {
	if req.GetSlug() == "" {
		return nil, status.Error(codes.InvalidArgument, "slug required")
	}
	if req.GetName() == "" {
		return nil, status.Error(codes.InvalidArgument, "name required")
	}
	if req.GetTopic() == "" {
		return nil, status.Error(codes.InvalidArgument, "topic required")
	}
	accent := ""
	if req.AccentColor != nil {
		accent = req.GetAccentColor()
	}
	ownerID, err := parseUUID(req.GetOwnerUserId(), "owner_user_id")
	if err != nil {
		return nil, err
	}

	c, err := s.svc.CreateTopic(ctx, req.GetSlug(), req.GetName(), req.GetTopic(), accent, ownerID)
	if err != nil {
		return nil, mapCommunityErr(err)
	}
	return communityToProto(c), nil
}

// ListMembers — FEATURE-COMMUNITIES-V1. Enriched, keyset-paginated. The
// optional role filter projects a single tier from the same query.
func (s *CommunityServer) ListMembers(ctx context.Context, req *socialv1.ListCommunityMembersRequest) (*socialv1.ListCommunityMembersResponse, error) {
	communityID, err := parseUUID(req.GetCommunityId(), "community_id")
	if err != nil {
		return nil, err
	}
	limit := 0
	if req.Limit != nil {
		limit = int(req.GetLimit())
	}
	cursor := ""
	if req.Cursor != nil {
		cursor = req.GetCursor()
	}
	var roleFilter *domcommunity.Role
	if req.Role != nil && req.GetRole() != socialv1.CommunityRole_COMMUNITY_ROLE_UNSPECIFIED {
		rf := roleFromProto(req.GetRole())
		roleFilter = &rf
	}

	page, err := s.svc.ListMembers(ctx, communityID, roleFilter, limit, cursor)
	if err != nil {
		return nil, mapCommunityErr(err)
	}
	out := make([]*socialv1.CommunityMemberProfile, 0, len(page.Members))
	for i := range page.Members {
		out = append(out, memberProfileToProto(page.Members[i]))
	}
	resp := &socialv1.ListCommunityMembersResponse{Members: out}
	if page.NextCursor != "" {
		resp.NextCursor = &page.NextCursor
	}
	return resp, nil
}

// GetMembership — viewer's role/presence for the Gateway aggregate.
func (s *CommunityServer) GetMembership(ctx context.Context, req *socialv1.GetCommunityMembershipRequest) (*socialv1.CommunityMember, error) {
	communityID, err := parseUUID(req.GetCommunityId(), "community_id")
	if err != nil {
		return nil, err
	}
	userID, err := parseUUID(req.GetUserId(), "user_id")
	if err != nil {
		return nil, err
	}
	m, err := s.svc.GetMembership(ctx, communityID, userID)
	if err != nil {
		return nil, mapCommunityErr(err)
	}
	return membershipToProto(m), nil
}

// GetStats — user-independent numeric projection (counters + role_counts).
func (s *CommunityServer) GetStats(ctx context.Context, req *socialv1.GetCommunityStatsRequest) (*socialv1.CommunityStats, error) {
	communityID, err := parseUUID(req.GetCommunityId(), "community_id")
	if err != nil {
		return nil, err
	}
	st, err := s.svc.GetStats(ctx, communityID)
	if err != nil {
		return nil, mapCommunityErr(err)
	}
	return &socialv1.CommunityStats{
		CommunityId:     st.CommunityID.String(),
		MemberCount:     st.MemberCount,
		ActiveNow:       st.ActiveNow,
		DiscussionCount: st.DiscussionCount,
		RoleCounts: &socialv1.RoleCounts{
			Owner:     st.RoleCounts.Owner,
			Admin:     st.RoleCounts.Admin,
			Moderator: st.RoleCounts.Moderator,
			Member:    st.RoleCounts.Member,
		},
	}, nil
}

func (s *CommunityServer) Join(ctx context.Context, req *socialv1.JoinCommunityRequest) (*socialv1.CommunityMember, error) {
	communityID, err := parseUUID(req.GetCommunityId(), "community_id")
	if err != nil {
		return nil, err
	}
	userID, err := parseUUID(req.GetUserId(), "user_id")
	if err != nil {
		return nil, err
	}
	m, err := s.svc.Join(ctx, communityID, userID)
	if err != nil {
		return nil, mapCommunityErr(err)
	}
	return membershipToProto(m), nil
}

func (s *CommunityServer) Leave(ctx context.Context, req *socialv1.LeaveCommunityRequest) (*emptypb.Empty, error) {
	communityID, err := parseUUID(req.GetCommunityId(), "community_id")
	if err != nil {
		return nil, err
	}
	userID, err := parseUUID(req.GetUserId(), "user_id")
	if err != nil {
		return nil, err
	}
	if err := s.svc.Leave(ctx, communityID, userID); err != nil {
		return nil, mapCommunityErr(err)
	}
	return &emptypb.Empty{}, nil
}

// ---- translators ----

func communityToProto(c *domcommunity.Community) *socialv1.Community {
	out := &socialv1.Community{
		Id:          c.ID().String(),
		Slug:        c.Slug(),
		Name:        c.Name(),
		Topic:       c.Topic(),
		Kind:        kindToProto(c.Kind()),
		AccentColor: c.AccentColor(),
		MemberCount: c.MemberCount(),
		ActiveNow:   c.ActiveNow(),
		CreatedAt:   timestamppb.New(c.CreatedAt()),
	}
	if cid := c.CompetitionID(); cid != nil {
		s := cid.String()
		out.CompetitionId = &s
	}
	if oid := c.OwnerUserID(); oid != nil {
		s := oid.String()
		out.OwnerUserId = &s
	}
	return out
}

func membershipToProto(m *domcommunity.Membership) *socialv1.CommunityMember {
	return &socialv1.CommunityMember{
		UserId:      m.UserID.String(),
		CommunityId: m.CommunityID.String(),
		JoinedAt:    timestamppb.New(m.JoinedAt),
		// is_moderator is derived from role for wire compat.
		IsModerator: m.Role.LegacyIsModerator(),
		Role:        roleToProto(m.Role),
	}
}

func memberProfileToProto(m domcommunity.MemberProfile) *socialv1.CommunityMemberProfile {
	return &socialv1.CommunityMemberProfile{
		UserId:      m.UserID.String(),
		Username:    m.Username,
		DisplayName: m.DisplayName,
		Initials:    m.Initials,
		AccentColor: m.AccentColor,
		AvatarUrl:   m.AvatarURL,
		Reputation:  m.Reputation,
		Role:        roleToProto(m.Role),
		JoinedAt:    timestamppb.New(m.JoinedAt),
	}
}

func roleToProto(r domcommunity.Role) socialv1.CommunityRole {
	switch r {
	case domcommunity.RoleOwner:
		return socialv1.CommunityRole_COMMUNITY_ROLE_OWNER
	case domcommunity.RoleAdmin:
		return socialv1.CommunityRole_COMMUNITY_ROLE_ADMIN
	case domcommunity.RoleModerator:
		return socialv1.CommunityRole_COMMUNITY_ROLE_MODERATOR
	case domcommunity.RoleMember:
		return socialv1.CommunityRole_COMMUNITY_ROLE_MEMBER
	default:
		return socialv1.CommunityRole_COMMUNITY_ROLE_UNSPECIFIED
	}
}

func roleFromProto(r socialv1.CommunityRole) domcommunity.Role {
	switch r {
	case socialv1.CommunityRole_COMMUNITY_ROLE_OWNER:
		return domcommunity.RoleOwner
	case socialv1.CommunityRole_COMMUNITY_ROLE_ADMIN:
		return domcommunity.RoleAdmin
	case socialv1.CommunityRole_COMMUNITY_ROLE_MODERATOR:
		return domcommunity.RoleModerator
	case socialv1.CommunityRole_COMMUNITY_ROLE_MEMBER:
		return domcommunity.RoleMember
	default:
		return domcommunity.RoleUnspecified
	}
}

func kindToProto(k domcommunity.Kind) socialv1.CommunityKind {
	switch k {
	case domcommunity.KindCompetition:
		return socialv1.CommunityKind_COMMUNITY_KIND_COMPETITION
	case domcommunity.KindTopic:
		return socialv1.CommunityKind_COMMUNITY_KIND_TOPIC
	default:
		return socialv1.CommunityKind_COMMUNITY_KIND_UNSPECIFIED
	}
}

func kindFromProto(k socialv1.CommunityKind) domcommunity.Kind {
	switch k {
	case socialv1.CommunityKind_COMMUNITY_KIND_COMPETITION:
		return domcommunity.KindCompetition
	case socialv1.CommunityKind_COMMUNITY_KIND_TOPIC:
		return domcommunity.KindTopic
	default:
		return domcommunity.KindUnspecified
	}
}

// sortFromProto maps the wire enum to the domain Sort. Unspecified is
// passed through as SortUnspecified so the domain default (resolved
// to Newest by Sort.Resolve) lives in one place.
func sortFromProto(s socialv1.CommunityListSort) domcommunity.Sort {
	switch s {
	case socialv1.CommunityListSort_COMMUNITY_LIST_SORT_NEWEST:
		return domcommunity.SortNewest
	case socialv1.CommunityListSort_COMMUNITY_LIST_SORT_HOT:
		return domcommunity.SortHot
	case socialv1.CommunityListSort_COMMUNITY_LIST_SORT_POPULAR:
		return domcommunity.SortPopular
	default:
		return domcommunity.SortUnspecified
	}
}

func mapCommunityErr(err error) error {
	switch {
	case errors.Is(err, domcommunity.ErrNotFound):
		return status.Error(codes.NotFound, "community not found")
	case errors.Is(err, domcommunity.ErrSlugTaken):
		return status.Error(codes.AlreadyExists, "slug already taken")
	case errors.Is(err, domcommunity.ErrAlreadyMember):
		return status.Error(codes.AlreadyExists, "user already a member")
	case errors.Is(err, domcommunity.ErrNotMember):
		return status.Error(codes.NotFound, "user is not a member")
	case errors.Is(err, domcommunity.ErrOwnerCannotLeave),
		errors.Is(err, domcommunity.ErrOwnerImmutable),
		errors.Is(err, domcommunity.ErrCannotAssignOwner),
		errors.Is(err, domcommunity.ErrRoleChangeDenied):
		return status.Error(codes.FailedPrecondition, err.Error())
	case errors.Is(err, domcommunity.ErrTransferUnsupported):
		return status.Error(codes.Unimplemented, err.Error())
	case errors.Is(err, domcommunity.ErrOwnerExists):
		return status.Error(codes.AlreadyExists, err.Error())
	case errors.Is(err, domcommunity.ErrInvalidSlug),
		errors.Is(err, domcommunity.ErrInvalidName),
		errors.Is(err, domcommunity.ErrInvalidTopic),
		errors.Is(err, domcommunity.ErrInvalidAccentColor),
		errors.Is(err, domcommunity.ErrOwnerRequired),
		errors.Is(err, domcommunity.ErrInvalidMembersCursor),
		errors.Is(err, pagination.ErrInvalidCursor):
		return status.Error(codes.InvalidArgument, err.Error())
	default:
		return status.Error(codes.Internal, "internal error")
	}
}
