// Narrow transport interfaces — Sprint 2.5 Part 2.
//
// Handlers depend on these slices (not the full bundle) so tests can
// fake exactly the surface a handler touches. They are pure transport:
// no business logic, no DTO shaping — that lives in the BFF handlers.
package socialclient

import (
	"context"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"google.golang.org/grpc"
	"google.golang.org/protobuf/types/known/emptypb"
)

// FeedClient — social.v1.FeedService transport slice.
type FeedClient interface {
	Global(ctx context.Context, in *socialv1.FeedRequest, opts ...grpc.CallOption) (*socialv1.FeedResponse, error)
	Following(ctx context.Context, in *socialv1.FeedRequest, opts ...grpc.CallOption) (*socialv1.FeedResponse, error)
	AuthorPosts(ctx context.Context, in *socialv1.AuthorPostsRequest, opts ...grpc.CallOption) (*socialv1.FeedResponse, error)
}

// UserClient — social.v1.UserService transport slice (BFF reads one
// user for the public profile).
type UserClient interface {
	Get(ctx context.Context, in *socialv1.GetUserRequest, opts ...grpc.CallOption) (*socialv1.User, error)
}

// AgentClient — social.v1.AgentService transport slice.
type AgentClient interface {
	List(ctx context.Context, in *socialv1.ListAgentsRequest, opts ...grpc.CallOption) (*socialv1.ListAgentsResponse, error)
	Get(ctx context.Context, in *socialv1.GetAgentRequest, opts ...grpc.CallOption) (*socialv1.AgentProfile, error)
}

// PostClient — social.v1.PostService transport slice.
type PostClient interface {
	Create(ctx context.Context, in *socialv1.CreatePostRequest, opts ...grpc.CallOption) (*socialv1.Post, error)
	Get(ctx context.Context, in *socialv1.GetPostRequest, opts ...grpc.CallOption) (*socialv1.Post, error)
	Delete(ctx context.Context, in *socialv1.DeletePostRequest, opts ...grpc.CallOption) (*emptypb.Empty, error)
	CreateComment(ctx context.Context, in *socialv1.CreateCommentRequest, opts ...grpc.CallOption) (*socialv1.Comment, error)
	ListComments(ctx context.Context, in *socialv1.ListCommentsRequest, opts ...grpc.CallOption) (*socialv1.ListCommentsResponse, error)
	Like(ctx context.Context, in *socialv1.LikePostRequest, opts ...grpc.CallOption) (*emptypb.Empty, error)
	Unlike(ctx context.Context, in *socialv1.UnlikePostRequest, opts ...grpc.CallOption) (*emptypb.Empty, error)
}

// RelationshipClient — social.v1.RelationshipService transport slice
// (follow/unfollow + mute/unmute; the BFF doesn't touch block).
type RelationshipClient interface {
	Follow(ctx context.Context, in *socialv1.FollowRequest, opts ...grpc.CallOption) (*socialv1.Relationship, error)
	Unfollow(ctx context.Context, in *socialv1.UnfollowRequest, opts ...grpc.CallOption) (*emptypb.Empty, error)
	Mute(ctx context.Context, in *socialv1.MuteRequest, opts ...grpc.CallOption) (*socialv1.Relationship, error)
	Unmute(ctx context.Context, in *socialv1.UnmuteRequest, opts ...grpc.CallOption) (*socialv1.Relationship, error)
}

// Compile-time conformance: the generated stubs satisfy the slices.
var (
	_ FeedClient         = (socialv1.FeedServiceClient)(nil)
	_ UserClient         = (socialv1.UserServiceClient)(nil)
	_ AgentClient        = (socialv1.AgentServiceClient)(nil)
	_ PostClient         = (socialv1.PostServiceClient)(nil)
	_ RelationshipClient = (socialv1.RelationshipServiceClient)(nil)
)
