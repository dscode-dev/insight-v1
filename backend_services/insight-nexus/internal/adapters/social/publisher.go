// Social publication adapter — Sprint 4 Part 13.
//
// The ONLY publication target. Uses Social's public gRPC API
// (social.v1.PostService) — never Social storage. Posts are created
// with author_type=agent and the seeded Social agent ids carried by
// the persona.
package social

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/keepalive"

	"github.com/konoha-labs/insight-nexus/internal/ports"
)

type Publisher struct {
	conn  *grpc.ClientConn
	posts socialv1.PostServiceClient
}

// New dials the Social gRPC endpoint. The caller owns Close().
func New(ctx context.Context, target string) (*Publisher, error) {
	if target == "" {
		return nil, errors.New("social: target required")
	}
	conn, err := grpc.DialContext(ctx, target, //nolint:staticcheck // pinned grpc line
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithDefaultServiceConfig(`{"loadBalancingPolicy":"round_robin"}`),
		grpc.WithKeepaliveParams(keepalive.ClientParameters{
			Time:                30 * time.Second,
			Timeout:             10 * time.Second,
			PermitWithoutStream: true,
		}),
	)
	if err != nil {
		return nil, fmt.Errorf("social: dial %s: %w", target, err)
	}
	return &Publisher{conn: conn, posts: socialv1.NewPostServiceClient(conn)}, nil
}

func (p *Publisher) Close() error {
	if p == nil || p.conn == nil {
		return nil
	}
	return p.conn.Close()
}

func (p *Publisher) PublishAgentPost(
	ctx context.Context, req ports.AgentPostRequest,
) (string, error) {
	visibility := socialv1.PostVisibility_POST_VISIBILITY_PUBLIC
	switch strings.ToLower(req.Visibility) {
	case "competition":
		visibility = socialv1.PostVisibility_POST_VISIBILITY_COMPETITION
	case "private":
		visibility = socialv1.PostVisibility_POST_VISIBILITY_PRIVATE
	}
	post, err := p.posts.Create(ctx, &socialv1.CreatePostRequest{
		AuthorId:   req.SocialAuthorID.String(),
		AuthorType: socialv1.AuthorType_AUTHOR_TYPE_AGENT,
		Content:    req.Content,
		Metadata:   req.Metadata,
		Visibility: visibility,
	})
	if err != nil {
		return "", fmt.Errorf("social: create post: %w", err)
	}
	return post.GetId(), nil
}

var _ ports.SocialPublisher = (*Publisher)(nil)
