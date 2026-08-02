// AgentProfile gRPC handler — Sprint 3 (Social Foundation).
package grpc

import (
	"context"
	"errors"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"

	appagent "github.com/konoha-labs/insight-social/internal/application/agent"
	domagent "github.com/konoha-labs/insight-social/internal/domain/agent"
)

type AgentServer struct {
	socialv1.UnimplementedAgentServiceServer
	svc *appagent.Service
}

func NewAgentServer(svc *appagent.Service) *AgentServer {
	return &AgentServer{svc: svc}
}

func (s *AgentServer) List(ctx context.Context, req *socialv1.ListAgentsRequest) (*socialv1.ListAgentsResponse, error) {
	agents, err := s.svc.List(ctx, req.GetActiveOnly())
	if err != nil {
		return nil, status.Error(codes.Internal, "agent list failed")
	}
	out := make([]*socialv1.AgentProfile, 0, len(agents))
	for _, a := range agents {
		out = append(out, agentToProto(a))
	}
	return &socialv1.ListAgentsResponse{Agents: out}, nil
}

func (s *AgentServer) Get(ctx context.Context, req *socialv1.GetAgentRequest) (*socialv1.AgentProfile, error) {
	var (
		profile *domagent.Profile
		err     error
	)
	switch {
	case req.GetId() != "":
		id, perr := parseUUID(req.GetId(), "id")
		if perr != nil {
			return nil, perr
		}
		profile, err = s.svc.Get(ctx, id)
	case req.GetSlug() != "":
		profile, err = s.svc.GetBySlug(ctx, req.GetSlug())
	default:
		return nil, status.Error(codes.InvalidArgument, "id or slug required")
	}
	if err != nil {
		if errors.Is(err, domagent.ErrNotFound) {
			return nil, status.Error(codes.NotFound, "agent not found")
		}
		return nil, status.Error(codes.Internal, "agent get failed")
	}
	return agentToProto(profile), nil
}

func agentToProto(a *domagent.Profile) *socialv1.AgentProfile {
	return &socialv1.AgentProfile{
		Id:        a.ID.String(),
		Slug:      a.Slug,
		Name:      a.Name,
		Avatar:    a.Avatar,
		Bio:       a.Bio,
		Active:    a.Active,
		Verified:  a.Verified,
		CreatedAt: timestamppb.New(a.CreatedAt),
	}
}
