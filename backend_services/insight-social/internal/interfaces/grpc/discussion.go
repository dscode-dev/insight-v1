// Discussion gRPC handler — translate + status mapping; no logic.
package grpc

import (
	"context"
	"errors"

	"github.com/google/uuid"
	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"

	appdiscussion "github.com/konoha-labs/insight-social/internal/application/discussion"
	domdiscussion "github.com/konoha-labs/insight-social/internal/domain/discussion"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/pagination"
)

type DiscussionServer struct {
	socialv1.UnimplementedDiscussionServiceServer
	svc *appdiscussion.Service
}

func NewDiscussionServer(svc *appdiscussion.Service) *DiscussionServer {
	return &DiscussionServer{svc: svc}
}

// ---- RPC methods ----

func (s *DiscussionServer) ListForCommunity(ctx context.Context, req *socialv1.ListDiscussionsRequest) (*socialv1.ListDiscussionsResponse, error) {
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
	page, err := s.svc.ListForCommunity(ctx, communityID, limit, cursor)
	if err != nil {
		return nil, mapDiscussionErr(err)
	}
	out := make([]*socialv1.Discussion, 0, len(page.Discussions))
	for _, d := range page.Discussions {
		out = append(out, discussionToProto(d))
	}
	resp := &socialv1.ListDiscussionsResponse{Discussions: out}
	if page.NextCursor != "" {
		resp.NextCursor = &page.NextCursor
	}
	return resp, nil
}

// Get — Sprint A.1. Lookup-by-id for the gateway DiscussionThread BFF.
func (s *DiscussionServer) Get(ctx context.Context, req *socialv1.GetDiscussionRequest) (*socialv1.Discussion, error) {
	id, err := parseUUID(req.GetId(), "id")
	if err != nil {
		return nil, err
	}
	d, err := s.svc.Get(ctx, id)
	if err != nil {
		return nil, mapDiscussionErr(err)
	}
	return discussionToProto(d), nil
}

func (s *DiscussionServer) Start(ctx context.Context, req *socialv1.StartDiscussionRequest) (*socialv1.Discussion, error) {
	communityID, err := parseUUID(req.GetCommunityId(), "community_id")
	if err != nil {
		return nil, err
	}
	authorID, err := parseUUID(req.GetAuthorId(), "author_id")
	if err != nil {
		return nil, err
	}
	var matchID *uuid.UUID
	if req.MatchId != nil && req.GetMatchId() != "" {
		mid, err := uuid.Parse(req.GetMatchId())
		if err != nil {
			return nil, status.Errorf(codes.InvalidArgument, "match_id: %v", err)
		}
		matchID = &mid
	}
	d, err := s.svc.Start(ctx, communityID, authorID, req.GetTitle(), req.GetBody(), matchID)
	if err != nil {
		return nil, mapDiscussionErr(err)
	}
	return discussionToProto(d), nil
}

func (s *DiscussionServer) PostMessage(ctx context.Context, req *socialv1.PostMessageRequest) (*socialv1.DiscussionMessage, error) {
	discussionID, err := parseUUID(req.GetDiscussionId(), "discussion_id")
	if err != nil {
		return nil, err
	}
	authorID, err := parseUUID(req.GetAuthorId(), "author_id")
	if err != nil {
		return nil, err
	}
	m, err := s.svc.PostMessage(ctx, discussionID, authorID, req.GetBody())
	if err != nil {
		return nil, mapDiscussionErr(err)
	}
	return messageToProto(m), nil
}

func (s *DiscussionServer) ListMessages(ctx context.Context, req *socialv1.ListMessagesRequest) (*socialv1.ListMessagesResponse, error) {
	discussionID, err := parseUUID(req.GetDiscussionId(), "discussion_id")
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
	page, err := s.svc.ListMessages(ctx, discussionID, limit, cursor)
	if err != nil {
		return nil, mapDiscussionErr(err)
	}
	out := make([]*socialv1.DiscussionMessage, 0, len(page.Messages))
	for _, m := range page.Messages {
		out = append(out, messageToProto(m))
	}
	resp := &socialv1.ListMessagesResponse{Messages: out}
	if page.NextCursor != "" {
		resp.NextCursor = &page.NextCursor
	}
	return resp, nil
}

// ---- translators ----

func discussionToProto(d *domdiscussion.Discussion) *socialv1.Discussion {
	out := &socialv1.Discussion{
		Id:             d.ID().String(),
		CommunityId:    d.CommunityID().String(),
		AuthorId:       d.AuthorID().String(),
		Title:          d.Title(),
		Body:           d.Body(),
		ReplyCount:     d.MessageCount(),
		ReactionCount:  0, // schema has no reactions yet (see domain doc)
		CreatedAt:      timestamppb.New(d.CreatedAt()),
		LastActivityTs: timestamppb.New(d.LastActivityTs()),
	}
	if mid := d.MatchID(); mid != nil {
		s := mid.String()
		out.MatchId = &s
	}
	return out
}

func messageToProto(m *domdiscussion.Message) *socialv1.DiscussionMessage {
	return &socialv1.DiscussionMessage{
		Id:           m.ID.String(),
		DiscussionId: m.DiscussionID.String(),
		AuthorId:     m.AuthorID.String(),
		Body:         m.Body,
		CreatedAt:    timestamppb.New(m.CreatedAt),
	}
}

func mapDiscussionErr(err error) error {
	switch {
	case errors.Is(err, domdiscussion.ErrNotFound):
		return status.Error(codes.NotFound, "discussion not found")
	case errors.Is(err, domdiscussion.ErrCommunityNotFound):
		return status.Error(codes.FailedPrecondition, "community not found")
	case errors.Is(err, domdiscussion.ErrInvalidTitle),
		errors.Is(err, domdiscussion.ErrInvalidBody),
		errors.Is(err, pagination.ErrInvalidCursor):
		return status.Error(codes.InvalidArgument, err.Error())
	default:
		return status.Error(codes.Internal, "internal error")
	}
}
