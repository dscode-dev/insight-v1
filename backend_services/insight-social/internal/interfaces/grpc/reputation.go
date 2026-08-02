// Reputation gRPC handler — translate + status mapping.
package grpc

import (
	"context"
	"errors"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	appreputation "github.com/konoha-labs/insight-social/internal/application/reputation"
	domreputation "github.com/konoha-labs/insight-social/internal/domain/reputation"
)

type ReputationServer struct {
	socialv1.UnimplementedReputationServiceServer
	svc *appreputation.Service
}

func NewReputationServer(svc *appreputation.Service) *ReputationServer {
	return &ReputationServer{svc: svc}
}

func (s *ReputationServer) Get(ctx context.Context, req *socialv1.GetReputationRequest) (*socialv1.Reputation, error) {
	userID, err := parseUUID(req.GetUserId(), "user_id")
	if err != nil {
		return nil, err
	}
	rep, err := s.svc.Get(ctx, userID)
	if err != nil {
		return nil, mapReputationErr(err)
	}
	return reputationToProto(rep), nil
}

func (s *ReputationServer) Recompute(ctx context.Context, req *socialv1.RecomputeReputationRequest) (*socialv1.Reputation, error) {
	userID, err := parseUUID(req.GetUserId(), "user_id")
	if err != nil {
		return nil, err
	}
	rep, err := s.svc.Recompute(ctx, userID)
	if err != nil {
		return nil, mapReputationErr(err)
	}
	return reputationToProto(rep), nil
}

// ---- translators ----

func reputationToProto(r domreputation.Reputation) *socialv1.Reputation {
	return &socialv1.Reputation{
		UserId:   r.UserID.String(),
		Score:    int32(r.Score),
		Tier:     tierToProto(r.Tier), // defined in user.go
		Accuracy: r.Accuracy,
	}
}

func mapReputationErr(err error) error {
	switch {
	case errors.Is(err, domreputation.ErrUserNotFound):
		return status.Error(codes.NotFound, "user not found")
	default:
		return status.Error(codes.Internal, "internal error")
	}
}
