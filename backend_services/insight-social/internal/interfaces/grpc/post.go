// Post / Comment / Like gRPC handler — Sprint 3 (Social Foundation).
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

	apppost "github.com/konoha-labs/insight-social/internal/application/post"
	dompost "github.com/konoha-labs/insight-social/internal/domain/post"
)

type PostServer struct {
	socialv1.UnimplementedPostServiceServer
	svc *apppost.Service
}

func NewPostServer(svc *apppost.Service) *PostServer {
	return &PostServer{svc: svc}
}

func (s *PostServer) Create(ctx context.Context, req *socialv1.CreatePostRequest) (*socialv1.Post, error) {
	authorID, err := parseUUID(req.GetAuthorId(), "author_id")
	if err != nil {
		return nil, err
	}
	// Optional. Rejected when unparseable rather than dropped: a post silently
	// published without the competition the author chose would be missing from
	// the only rail they expect to find it in.
	var competitionID *uuid.UUID
	if raw := req.GetCompetitionId(); raw != "" {
		parsed, perr := parseUUID(raw, "competition_id")
		if perr != nil {
			return nil, perr
		}
		competitionID = &parsed
	}
	p, err := s.svc.Create(ctx,
		authorID,
		authorTypeFromProto(req.GetAuthorType()),
		req.GetContent(),
		req.GetMetadata(),
		visibilityFromProto(req.GetVisibility()),
		competitionID,
	)
	if err != nil {
		return nil, mapPostErr(err)
	}
	return postToProto(p), nil
}

func (s *PostServer) Get(ctx context.Context, req *socialv1.GetPostRequest) (*socialv1.Post, error) {
	id, err := parseUUID(req.GetId(), "id")
	if err != nil {
		return nil, err
	}
	p, err := s.svc.Get(ctx, id)
	if err != nil {
		return nil, mapPostErr(err)
	}
	return postToProto(p), nil
}

func (s *PostServer) Delete(ctx context.Context, req *socialv1.DeletePostRequest) (*emptypb.Empty, error) {
	id, err := parseUUID(req.GetId(), "id")
	if err != nil {
		return nil, err
	}
	requester, err := parseUUID(req.GetRequesterId(), "requester_id")
	if err != nil {
		return nil, err
	}
	if err := s.svc.Delete(ctx, id, requester); err != nil {
		return nil, mapPostErr(err)
	}
	return &emptypb.Empty{}, nil
}

func (s *PostServer) CreateComment(ctx context.Context, req *socialv1.CreateCommentRequest) (*socialv1.Comment, error) {
	postID, err := parseUUID(req.GetPostId(), "post_id")
	if err != nil {
		return nil, err
	}
	authorID, err := parseUUID(req.GetAuthorId(), "author_id")
	if err != nil {
		return nil, err
	}
	var parentID *uuid.UUID
	if req.GetParentId() != "" {
		parsed, perr := parseUUID(req.GetParentId(), "parent_id")
		if perr != nil {
			return nil, perr
		}
		parentID = &parsed
	}
	c, err := s.svc.CreateComment(ctx, postID, parentID, authorID,
		authorTypeFromProto(req.GetAuthorType()), req.GetContent())
	if err != nil {
		return nil, mapPostErr(err)
	}
	return commentToProto(c), nil
}

func (s *PostServer) ListComments(ctx context.Context, req *socialv1.ListCommentsRequest) (*socialv1.ListCommentsResponse, error) {
	postID, err := parseUUID(req.GetPostId(), "post_id")
	if err != nil {
		return nil, err
	}
	page, err := s.svc.ListComments(ctx, postID, int(req.GetLimit()), req.GetCursor())
	if err != nil {
		return nil, mapPostErr(err)
	}
	out := make([]*socialv1.Comment, 0, len(page.Comments))
	for _, c := range page.Comments {
		out = append(out, commentToProto(c))
	}
	resp := &socialv1.ListCommentsResponse{Comments: out}
	if page.NextCursor != "" {
		resp.NextCursor = &page.NextCursor
	}
	return resp, nil
}

func (s *PostServer) Like(ctx context.Context, req *socialv1.LikePostRequest) (*emptypb.Empty, error) {
	postID, err := parseUUID(req.GetPostId(), "post_id")
	if err != nil {
		return nil, err
	}
	userID, err := parseUUID(req.GetUserId(), "user_id")
	if err != nil {
		return nil, err
	}
	if err := s.svc.Like(ctx, postID, userID); err != nil {
		return nil, mapPostErr(err)
	}
	return &emptypb.Empty{}, nil
}

func (s *PostServer) Unlike(ctx context.Context, req *socialv1.UnlikePostRequest) (*emptypb.Empty, error) {
	postID, err := parseUUID(req.GetPostId(), "post_id")
	if err != nil {
		return nil, err
	}
	userID, err := parseUUID(req.GetUserId(), "user_id")
	if err != nil {
		return nil, err
	}
	if err := s.svc.Unlike(ctx, postID, userID); err != nil {
		return nil, mapPostErr(err)
	}
	return &emptypb.Empty{}, nil
}

// ---- converters + error mapping ----

func mapPostErr(err error) error {
	switch {
	case errors.Is(err, dompost.ErrNotFound),
		errors.Is(err, dompost.ErrCommentNotFound):
		return status.Error(codes.NotFound, err.Error())
	case errors.Is(err, dompost.ErrEmptyContent),
		errors.Is(err, dompost.ErrContentTooLong),
		errors.Is(err, dompost.ErrInvalidAuthor),
		errors.Is(err, dompost.ErrInvalidVisible),
		errors.Is(err, dompost.ErrMaxDepthExceeded):
		return status.Error(codes.InvalidArgument, err.Error())
	case errors.Is(err, dompost.ErrNotAuthor):
		return status.Error(codes.PermissionDenied, err.Error())
	case errors.Is(err, dompost.ErrAgentInactive):
		return status.Error(codes.FailedPrecondition, err.Error())
	default:
		return status.Error(codes.Internal, "post operation failed")
	}
}

func postToProto(p *dompost.Post) *socialv1.Post {
	out := &socialv1.Post{
		Id:           p.ID.String(),
		AuthorId:     p.AuthorID.String(),
		AuthorType:   authorTypeToProto(p.AuthorType),
		Content:      p.Content,
		Metadata:     p.Metadata,
		Visibility:   visibilityToProto(p.Visibility),
		CreatedAt:    timestamppb.New(p.CreatedAt),
		LikeCount:    p.LikeCount,
		CommentCount: p.CommentCount,
	}
	if p.CompetitionID != nil {
		id := p.CompetitionID.String()
		out.CompetitionId = &id
		// Only sent alongside the id — a slug or name without one would let a
		// client render a chip that filters to nothing.
		if p.CompetitionSlug != "" {
			slug := p.CompetitionSlug
			out.CompetitionSlug = &slug
		}
		if p.CompetitionName != "" {
			name := p.CompetitionName
			out.CompetitionName = &name
		}
	}
	return out
}

func commentToProto(c *dompost.Comment) *socialv1.Comment {
	out := &socialv1.Comment{
		Id:         c.ID.String(),
		PostId:     c.PostID.String(),
		AuthorId:   c.AuthorID.String(),
		AuthorType: authorTypeToProto(c.AuthorType),
		Content:    c.Content,
		Depth:      int32(c.Depth),
		CreatedAt:  timestamppb.New(c.CreatedAt),
	}
	if c.ParentID != nil {
		out.ParentId = c.ParentID.String()
	}
	return out
}

func authorTypeFromProto(t socialv1.AuthorType) dompost.AuthorType {
	switch t {
	case socialv1.AuthorType_AUTHOR_TYPE_USER:
		return dompost.AuthorUser
	case socialv1.AuthorType_AUTHOR_TYPE_AGENT:
		return dompost.AuthorAgent
	case socialv1.AuthorType_AUTHOR_TYPE_ADMIN:
		return dompost.AuthorAdmin
	default:
		return dompost.AuthorType("")
	}
}

func authorTypeToProto(t dompost.AuthorType) socialv1.AuthorType {
	switch t {
	case dompost.AuthorUser:
		return socialv1.AuthorType_AUTHOR_TYPE_USER
	case dompost.AuthorAgent:
		return socialv1.AuthorType_AUTHOR_TYPE_AGENT
	case dompost.AuthorAdmin:
		return socialv1.AuthorType_AUTHOR_TYPE_ADMIN
	default:
		return socialv1.AuthorType_AUTHOR_TYPE_UNSPECIFIED
	}
}

func visibilityFromProto(v socialv1.PostVisibility) dompost.Visibility {
	switch v {
	case socialv1.PostVisibility_POST_VISIBILITY_PUBLIC:
		return dompost.VisibilityPublic
	case socialv1.PostVisibility_POST_VISIBILITY_COMPETITION:
		return dompost.VisibilityCompetition
	case socialv1.PostVisibility_POST_VISIBILITY_PRIVATE:
		return dompost.VisibilityPrivate
	default:
		return dompost.Visibility("")
	}
}

func visibilityToProto(v dompost.Visibility) socialv1.PostVisibility {
	switch v {
	case dompost.VisibilityPublic:
		return socialv1.PostVisibility_POST_VISIBILITY_PUBLIC
	case dompost.VisibilityCompetition:
		return socialv1.PostVisibility_POST_VISIBILITY_COMPETITION
	case dompost.VisibilityPrivate:
		return socialv1.PostVisibility_POST_VISIBILITY_PRIVATE
	default:
		return socialv1.PostVisibility_POST_VISIBILITY_UNSPECIFIED
	}
}
