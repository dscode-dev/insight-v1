// Signal gRPC handler — translate + status mapping.
package grpc

import (
	"context"
	"errors"
	"strconv"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"

	appsignal "github.com/konoha-labs/insight-social/internal/application/signal"
	domsignal "github.com/konoha-labs/insight-social/internal/domain/signal"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/pagination"
)

type SignalServer struct {
	socialv1.UnimplementedSignalServiceServer
	svc *appsignal.Service
}

func NewSignalServer(svc *appsignal.Service) *SignalServer {
	return &SignalServer{svc: svc}
}

func (s *SignalServer) Create(ctx context.Context, req *socialv1.CreateSignalRequest) (*socialv1.Signal, error) {
	authorID, err := parseUUID(req.GetAuthorId(), "author_id")
	if err != nil {
		return nil, err
	}
	matchID, err := parseUUID(req.GetMatchId(), "match_id")
	if err != nil {
		return nil, err
	}
	sig, err := s.svc.Create(ctx, authorID, matchID,
		sourceFromProto(req.GetSource()),
		req.GetLabel(), req.GetBody(), req.GetConfidence(),
	)
	if err != nil {
		return nil, mapSignalErr(err)
	}
	return signalToProto(sig), nil
}

func (s *SignalServer) ListForMatch(ctx context.Context, req *socialv1.ListForMatchRequest) (*socialv1.ListForMatchResponse, error) {
	matchID, err := parseUUID(req.GetMatchId(), "match_id")
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
	page, err := s.svc.ListForMatch(ctx, matchID, limit, cursor)
	if err != nil {
		return nil, mapSignalErr(err)
	}
	out := make([]*socialv1.Signal, 0, len(page.Signals))
	for _, sig := range page.Signals {
		out = append(out, signalToProto(sig))
	}
	resp := &socialv1.ListForMatchResponse{Signals: out}
	if page.NextCursor != "" {
		resp.NextCursor = &page.NextCursor
	}
	return resp, nil
}

func (s *SignalServer) ListForUser(ctx context.Context, req *socialv1.ListForUserRequest) (*socialv1.ListForUserResponse, error) {
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
		return nil, mapSignalErr(err)
	}
	out := make([]*socialv1.Signal, 0, len(page.Signals))
	for _, sig := range page.Signals {
		out = append(out, signalToProto(sig))
	}
	resp := &socialv1.ListForUserResponse{Signals: out}
	if page.NextCursor != "" {
		resp.NextCursor = &page.NextCursor
	}
	return resp, nil
}

// ---- translators ----

func signalToProto(s *domsignal.Signal) *socialv1.Signal {
	return &socialv1.Signal{
		Id:         strconv.FormatInt(s.ID(), 10),
		AuthorId:   s.AuthorID().String(),
		MatchId:    s.MatchID().String(),
		Source:     sourceToProto(s.Source()),
		Label:      s.Label(),
		Body:       s.Body(),
		Confidence: s.Confidence(),
		State:      stateToProto(s.State()),
		Ts:         timestamppb.New(s.Ts()),
	}
}

func sourceToProto(s domsignal.Source) socialv1.SignalSource {
	switch s {
	case domsignal.SourceCommunity:
		return socialv1.SignalSource_SIGNAL_SOURCE_COMMUNITY
	case domsignal.SourceExpert:
		return socialv1.SignalSource_SIGNAL_SOURCE_EXPERT
	case domsignal.SourceModel:
		return socialv1.SignalSource_SIGNAL_SOURCE_MODEL
	default:
		return socialv1.SignalSource_SIGNAL_SOURCE_UNSPECIFIED
	}
}

func sourceFromProto(s socialv1.SignalSource) domsignal.Source {
	switch s {
	case socialv1.SignalSource_SIGNAL_SOURCE_COMMUNITY:
		return domsignal.SourceCommunity
	case socialv1.SignalSource_SIGNAL_SOURCE_EXPERT:
		return domsignal.SourceExpert
	case socialv1.SignalSource_SIGNAL_SOURCE_MODEL:
		return domsignal.SourceModel
	default:
		return domsignal.SourceUnspecified
	}
}

func stateToProto(s domsignal.State) socialv1.SignalState {
	switch s {
	case domsignal.StatePending:
		return socialv1.SignalState_SIGNAL_STATE_PENDING
	case domsignal.StateValidated:
		return socialv1.SignalState_SIGNAL_STATE_VALIDATED
	case domsignal.StateFlagged:
		return socialv1.SignalState_SIGNAL_STATE_FLAGGED
	case domsignal.StateInvalidated:
		return socialv1.SignalState_SIGNAL_STATE_INVALIDATED
	default:
		return socialv1.SignalState_SIGNAL_STATE_UNSPECIFIED
	}
}

func mapSignalErr(err error) error {
	switch {
	case errors.Is(err, domsignal.ErrNotFound):
		return status.Error(codes.NotFound, "signal not found")
	case errors.Is(err, domsignal.ErrAuthorNotFound):
		return status.Error(codes.FailedPrecondition, "author not found")
	case errors.Is(err, domsignal.ErrMatchNotFound):
		return status.Error(codes.FailedPrecondition, "match not found")
	case errors.Is(err, domsignal.ErrInvalidLabel),
		errors.Is(err, domsignal.ErrInvalidBody),
		errors.Is(err, domsignal.ErrInvalidConfidence),
		errors.Is(err, pagination.ErrInvalidCursor):
		return status.Error(codes.InvalidArgument, err.Error())
	case errors.Is(err, domsignal.ErrPublish):
		// Row was persisted but fan-out failed. Caller knows to
		// retry — consumers dedupe on signal_id so duplicates are
		// idempotent.
		return status.Error(codes.Unavailable, "signal published to db but stream fan-out failed; safe to retry")
	default:
		return status.Error(codes.Internal, "internal error")
	}
}
