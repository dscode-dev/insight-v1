// Relationship gRPC handler — translate + status mapping.
package grpc

import (
	"context"
	"errors"

	"github.com/google/uuid"
	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/emptypb"
	"google.golang.org/protobuf/types/known/timestamppb"

	apprelationship "github.com/konoha-labs/insight-social/internal/application/relationship"
	domrelationship "github.com/konoha-labs/insight-social/internal/domain/relationship"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/pagination"
)

type RelationshipServer struct {
	socialv1.UnimplementedRelationshipServiceServer
	svc *apprelationship.Service
}

func NewRelationshipServer(svc *apprelationship.Service) *RelationshipServer {
	return &RelationshipServer{svc: svc}
}

func (s *RelationshipServer) Follow(ctx context.Context, req *socialv1.FollowRequest) (*socialv1.Relationship, error) {
	actor, target, err := parsePair(req.GetSourceUserId(), req.GetTargetUserId())
	if err != nil {
		return nil, err
	}
	rel, err := s.svc.Follow(ctx, actor, target)
	if err != nil {
		return nil, mapRelationshipErr(err)
	}
	return relationshipToProto(rel), nil
}

func (s *RelationshipServer) Unfollow(ctx context.Context, req *socialv1.UnfollowRequest) (*emptypb.Empty, error) {
	actor, target, err := parsePair(req.GetSourceUserId(), req.GetTargetUserId())
	if err != nil {
		return nil, err
	}
	if err := s.svc.Unfollow(ctx, actor, target); err != nil {
		return nil, mapRelationshipErr(err)
	}
	return &emptypb.Empty{}, nil
}

func (s *RelationshipServer) Block(ctx context.Context, req *socialv1.BlockRequest) (*socialv1.Relationship, error) {
	actor, target, err := parsePair(req.GetSourceUserId(), req.GetTargetUserId())
	if err != nil {
		return nil, err
	}
	rel, err := s.svc.Block(ctx, actor, target)
	if err != nil {
		return nil, mapRelationshipErr(err)
	}
	return relationshipToProto(rel), nil
}

// Mute — Sprint 3: the target stays followed but never feeds.
func (s *RelationshipServer) Mute(ctx context.Context, req *socialv1.MuteRequest) (*socialv1.Relationship, error) {
	actor, target, err := parsePair(req.GetSourceUserId(), req.GetTargetUserId())
	if err != nil {
		return nil, err
	}
	rel, err := s.svc.Mute(ctx, actor, target)
	if err != nil {
		return nil, mapRelationshipErr(err)
	}
	return relationshipToProto(rel), nil
}

func (s *RelationshipServer) Unmute(ctx context.Context, req *socialv1.UnmuteRequest) (*socialv1.Relationship, error) {
	actor, target, err := parsePair(req.GetSourceUserId(), req.GetTargetUserId())
	if err != nil {
		return nil, err
	}
	rel, err := s.svc.Unmute(ctx, actor, target)
	if err != nil {
		return nil, mapRelationshipErr(err)
	}
	return relationshipToProto(rel), nil
}

func (s *RelationshipServer) ListFollowers(ctx context.Context, req *socialv1.ListRelationshipsRequest) (*socialv1.ListRelationshipsResponse, error) {
	return s.listImpl(ctx, req, s.svc.ListFollowers)
}

func (s *RelationshipServer) ListFollowing(ctx context.Context, req *socialv1.ListRelationshipsRequest) (*socialv1.ListRelationshipsResponse, error) {
	return s.listImpl(ctx, req, s.svc.ListFollowing)
}

// listImpl is the shared body for the two list RPCs — they differ
// only in which app-service method to call (followers vs following).
func (s *RelationshipServer) listImpl(
	ctx context.Context,
	req *socialv1.ListRelationshipsRequest,
	call func(ctx context.Context, userID uuid.UUID, limit int, cursor string) (domrelationship.ListPage, error),
) (*socialv1.ListRelationshipsResponse, error) {
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
	page, err := call(ctx, userID, limit, cursor)
	if err != nil {
		return nil, mapRelationshipErr(err)
	}
	out := make([]*socialv1.Relationship, 0, len(page.Relationships))
	for _, r := range page.Relationships {
		out = append(out, relationshipToProto(r))
	}
	resp := &socialv1.ListRelationshipsResponse{Relationships: out}
	if page.NextCursor != "" {
		resp.NextCursor = &page.NextCursor
	}
	return resp, nil
}

// ---- translators ----

func relationshipToProto(r *domrelationship.Relationship) *socialv1.Relationship {
	out := &socialv1.Relationship{
		SourceUserId: r.ActorID.String(),
		TargetUserId: r.TargetID.String(),
		Kind:         relKindToProto(r.Kind),
		CreatedAt:    timestamppb.New(r.CreatedAt),
		Muted:        r.Muted,
	}
	if r.MutedAt != nil {
		out.MutedAt = timestamppb.New(*r.MutedAt)
	}
	return out
}

func relKindToProto(k domrelationship.Kind) socialv1.RelationshipKind {
	switch k {
	case domrelationship.KindFollow:
		return socialv1.RelationshipKind_RELATIONSHIP_KIND_FOLLOW
	case domrelationship.KindBlock:
		return socialv1.RelationshipKind_RELATIONSHIP_KIND_BLOCK
	default:
		return socialv1.RelationshipKind_RELATIONSHIP_KIND_UNSPECIFIED
	}
}

func mapRelationshipErr(err error) error {
	switch {
	case errors.Is(err, domrelationship.ErrNotFound):
		return status.Error(codes.NotFound, "relationship not found")
	case errors.Is(err, domrelationship.ErrAlreadyExists):
		return status.Error(codes.AlreadyExists, "relationship already exists")
	case errors.Is(err, domrelationship.ErrSelfTarget):
		return status.Error(codes.InvalidArgument, "actor cannot target self")
	case errors.Is(err, domrelationship.ErrUserNotFound):
		return status.Error(codes.FailedPrecondition, "user not found")
	case errors.Is(err, pagination.ErrInvalidCursor):
		return status.Error(codes.InvalidArgument, err.Error())
	default:
		return status.Error(codes.Internal, "internal error")
	}
}
