// Sentiment gRPC handler — translate + status mapping; no logic.
package grpc

import (
	"context"
	"errors"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"

	appsentiment "github.com/konoha-labs/insight-social/internal/application/sentiment"
	domsentiment "github.com/konoha-labs/insight-social/internal/domain/sentiment"
)

type SentimentServer struct {
	socialv1.UnimplementedSentimentServiceServer
	svc *appsentiment.Service
}

func NewSentimentServer(svc *appsentiment.Service) *SentimentServer {
	return &SentimentServer{svc: svc}
}

func (s *SentimentServer) GetForMatch(ctx context.Context, req *socialv1.GetSentimentRequest) (*socialv1.SentimentSnapshot, error) {
	matchID, err := parseUUID(req.GetMatchId(), "match_id")
	if err != nil {
		return nil, err
	}
	snap, err := s.svc.GetForMatch(ctx, matchID)
	if err != nil {
		return nil, mapSentimentErr(err)
	}
	return snapshotToProto(snap), nil
}

func (s *SentimentServer) HistoryForMatch(ctx context.Context, req *socialv1.GetSentimentHistoryRequest) (*socialv1.GetSentimentHistoryResponse, error) {
	matchID, err := parseUUID(req.GetMatchId(), "match_id")
	if err != nil {
		return nil, err
	}
	var from = req.GetFrom().AsTime() // zero when From is nil → service applies default window
	maxPoints := 0
	if req.MaxPoints != nil {
		maxPoints = int(req.GetMaxPoints())
	}

	points, err := s.svc.HistoryForMatch(ctx, matchID, from, maxPoints)
	if err != nil {
		return nil, mapSentimentErr(err)
	}
	out := make([]*socialv1.SentimentPoint, 0, len(points))
	for _, p := range points {
		out = append(out, &socialv1.SentimentPoint{
			Ts:       timestamppb.New(p.Ts),
			HomeLean: p.HomeLean,
			Pressure: p.Pressure,
		})
	}
	return &socialv1.GetSentimentHistoryResponse{Points: out}, nil
}

// ---- translators ----

func snapshotToProto(s domsentiment.Snapshot) *socialv1.SentimentSnapshot {
	return &socialv1.SentimentSnapshot{
		MatchId:     s.MatchID.String(),
		HomeLean:    s.HomeLean(),
		Dispersion:  s.Dispersion(),
		Pressure:    s.Pressure(),
		SignalCount: s.Participants,
		ComputedAt:  timestamppb.New(s.CapturedAt),
	}
}

func mapSentimentErr(err error) error {
	switch {
	case errors.Is(err, domsentiment.ErrNotFound):
		return status.Error(codes.NotFound, "no sentiment snapshot for match")
	default:
		return status.Error(codes.Internal, "internal error")
	}
}
