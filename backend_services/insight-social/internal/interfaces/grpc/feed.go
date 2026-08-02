// Feed gRPC handler — Sprint 3 (Social Foundation). Query-time
// generation; see internal/application/feed for the product rules.
package grpc

import (
	"context"

	"github.com/google/uuid"
	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	appfeed "github.com/konoha-labs/insight-social/internal/application/feed"
	domfeed "github.com/konoha-labs/insight-social/internal/domain/feed"
)

type FeedServer struct {
	socialv1.UnimplementedFeedServiceServer
	svc *appfeed.Service
}

func NewFeedServer(svc *appfeed.Service) *FeedServer {
	return &FeedServer{svc: svc}
}

func (s *FeedServer) Global(ctx context.Context, req *socialv1.FeedRequest) (*socialv1.FeedResponse, error) {
	return s.serve(ctx, req, s.svc.Global)
}

func (s *FeedServer) Following(ctx context.Context, req *socialv1.FeedRequest) (*socialv1.FeedResponse, error) {
	return s.serve(ctx, req, s.svc.Following)
}

func (s *FeedServer) AuthorPosts(ctx context.Context, req *socialv1.AuthorPostsRequest) (*socialv1.FeedResponse, error) {
	authorID, err := parseUUID(req.GetAuthorId(), "author_id")
	if err != nil {
		return nil, err
	}
	// viewer_id is optional — empty = anonymous viewer (liked_by_me false).
	var viewerID uuid.UUID
	if req.GetViewerId() != "" {
		if viewerID, err = parseUUID(req.GetViewerId(), "viewer_id"); err != nil {
			return nil, err
		}
	}
	page, err := s.svc.AuthorPosts(ctx, authorID, viewerID, int(req.GetLimit()), req.GetCursor())
	if err != nil {
		return nil, status.Error(codes.Internal, "author posts read failed")
	}
	return feedPageToProto(page), nil
}

func (s *FeedServer) serve(
	ctx context.Context,
	req *socialv1.FeedRequest,
	call func(ctx context.Context, userID uuid.UUID, limit int, cursor string) (domfeed.Page, error),
) (*socialv1.FeedResponse, error) {
	userID, err := parseUUID(req.GetUserId(), "user_id")
	if err != nil {
		return nil, err
	}
	page, err := call(ctx, userID, int(req.GetLimit()), req.GetCursor())
	if err != nil {
		return nil, status.Error(codes.Internal, "feed read failed")
	}
	return feedPageToProto(page), nil
}

func feedPageToProto(page domfeed.Page) *socialv1.FeedResponse {
	items := make([]*socialv1.FeedItem, 0, len(page.Items))
	for _, item := range page.Items {
		items = append(items, &socialv1.FeedItem{
			Post:              postToProto(item.Post),
			AuthorName:        item.AuthorName,
			AuthorAvatar:      item.AuthorAvatar,
			FromFollowedAgent: item.FromFollowedAgent,
			Sponsored:         item.Sponsored,
			LikedByMe:         item.LikedByMe,
		})
	}
	resp := &socialv1.FeedResponse{Items: items}
	if page.NextCursor != "" {
		resp.NextCursor = &page.NextCursor
	}
	return resp
}
