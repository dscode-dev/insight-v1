// Sprint B — Reaction gRPC handler. Translate + status mapping; no
// business logic.
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

	appreaction "github.com/konoha-labs/insight-social/internal/application/reaction"
	domreaction "github.com/konoha-labs/insight-social/internal/domain/reaction"
)

type ReactionServer struct {
	socialv1.UnimplementedReactionServiceServer
	svc *appreaction.Service
}

func NewReactionServer(svc *appreaction.Service) *ReactionServer {
	return &ReactionServer{svc: svc}
}

func (s *ReactionServer) React(ctx context.Context, req *socialv1.ReactRequest) (*socialv1.Reaction, error) {
	userID, err := parseUUID(req.GetUserId(), "user_id")
	if err != nil {
		return nil, err
	}
	discID, err := parseUUID(req.GetDiscussionId(), "discussion_id")
	if err != nil {
		return nil, err
	}
	r, err := s.svc.React(ctx, userID, discID, reactionKindFromProto(req.GetKind()))
	if err != nil {
		return nil, mapReactionErr(err)
	}
	return reactionToProto(r), nil
}

func (s *ReactionServer) Unreact(ctx context.Context, req *socialv1.UnreactRequest) (*emptypb.Empty, error) {
	userID, err := parseUUID(req.GetUserId(), "user_id")
	if err != nil {
		return nil, err
	}
	discID, err := parseUUID(req.GetDiscussionId(), "discussion_id")
	if err != nil {
		return nil, err
	}
	if err := s.svc.Unreact(ctx, userID, discID, reactionKindFromProto(req.GetKind())); err != nil {
		return nil, mapReactionErr(err)
	}
	return &emptypb.Empty{}, nil
}

func (s *ReactionServer) StateForDiscussion(ctx context.Context, req *socialv1.GetDiscussionReactionStateRequest) (*socialv1.DiscussionReactionState, error) {
	discID, err := parseUUID(req.GetDiscussionId(), "discussion_id")
	if err != nil {
		return nil, err
	}
	viewerID := uuid.Nil
	if req.UserId != nil && *req.UserId != "" {
		viewerID, err = uuid.Parse(*req.UserId)
		if err != nil {
			return nil, status.Errorf(codes.InvalidArgument, "user_id: %v", err)
		}
	}
	st, err := s.svc.StateForDiscussion(ctx, discID, viewerID)
	if err != nil {
		return nil, mapReactionErr(err)
	}
	return discussionStateToProto(st), nil
}

func (s *ReactionServer) BatchStateForDiscussions(ctx context.Context, req *socialv1.BatchGetDiscussionReactionStateRequest) (*socialv1.BatchGetDiscussionReactionStateResponse, error) {
	raw := req.GetDiscussionIds()
	ids := make([]uuid.UUID, 0, len(raw))
	for i, r := range raw {
		id, err := uuid.Parse(r)
		if err != nil {
			return nil, status.Errorf(codes.InvalidArgument, "discussion_ids[%d]: %v", i, err)
		}
		ids = append(ids, id)
	}
	viewerID := uuid.Nil
	if req.UserId != nil && *req.UserId != "" {
		var err error
		viewerID, err = uuid.Parse(*req.UserId)
		if err != nil {
			return nil, status.Errorf(codes.InvalidArgument, "user_id: %v", err)
		}
	}
	states, err := s.svc.BatchStateForDiscussions(ctx, ids, viewerID)
	if err != nil {
		return nil, mapReactionErr(err)
	}
	out := make([]*socialv1.DiscussionReactionState, 0, len(states))
	for _, st := range states {
		out = append(out, discussionStateToProto(st))
	}
	return &socialv1.BatchGetDiscussionReactionStateResponse{States: out}, nil
}

// ---- translators ----

func reactionToProto(r *domreaction.Reaction) *socialv1.Reaction {
	return &socialv1.Reaction{
		UserId:       r.UserID.String(),
		DiscussionId: r.DiscussionID.String(),
		Kind:         reactionKindToProto(r.Kind),
		CreatedAt:    timestamppb.New(r.CreatedAt),
	}
}

func discussionStateToProto(s domreaction.DiscussionState) *socialv1.DiscussionReactionState {
	return &socialv1.DiscussionReactionState{
		DiscussionId: s.DiscussionID.String(),
		LikeCount:    s.LikeCount,
		LikedByUser:  s.LikedByUser,
	}
}

func reactionKindToProto(k domreaction.Kind) socialv1.ReactionKind {
	switch k {
	case domreaction.KindLike:
		return socialv1.ReactionKind_REACTION_KIND_LIKE
	default:
		return socialv1.ReactionKind_REACTION_KIND_UNSPECIFIED
	}
}

func reactionKindFromProto(k socialv1.ReactionKind) domreaction.Kind {
	switch k {
	case socialv1.ReactionKind_REACTION_KIND_LIKE:
		return domreaction.KindLike
	default:
		return domreaction.KindUnspecified
	}
}

func mapReactionErr(err error) error {
	switch {
	case errors.Is(err, domreaction.ErrDiscussionNotFound):
		return status.Error(codes.NotFound, "discussion not found")
	case errors.Is(err, domreaction.ErrUserNotFound):
		return status.Error(codes.FailedPrecondition, "user not found")
	default:
		return status.Error(codes.Internal, "internal error")
	}
}
