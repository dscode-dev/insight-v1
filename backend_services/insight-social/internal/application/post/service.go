// Package post is the application service for posts, comments and
// likes — Sprint 3 (Social Foundation). Text-only V1.
package post

import (
	"context"
	"strconv"

	"github.com/google/uuid"

	dompost "github.com/konoha-labs/insight-social/internal/domain/post"
	"github.com/konoha-labs/insight-social/internal/observability"
)

const (
	defaultListLimit = 50
	maxListLimit     = 200
)

// AgentGuard answers whether an agent may currently publish. Injected so the
// publication choke point (Create with author_type=agent) enforces
// agent_profiles.active — every publication path (Nexus, workers) funnels here.
type AgentGuard interface {
	IsActive(ctx context.Context, agentID uuid.UUID) (bool, error)
}

type Service struct {
	repo   dompost.Repository
	agents AgentGuard // optional; nil ⇒ no agent-state enforcement (dev/test)
}

func New(repo dompost.Repository) *Service {
	return &Service{repo: repo}
}

// WithAgentGuard wires agent operational-state enforcement (CONSOLE-SOCIAL-B).
func (s *Service) WithAgentGuard(g AgentGuard) *Service {
	s.agents = g
	return s
}

func (s *Service) Create(
	ctx context.Context,
	authorID uuid.UUID,
	authorType dompost.AuthorType,
	content string,
	metadata map[string]string,
	visibility dompost.Visibility,
	competitionID *uuid.UUID,
) (*dompost.Post, error) {
	// Publication enforcement (CONSOLE-SOCIAL-B): a deactivated agent may not
	// publish. This is the single authoritative choke point every agent
	// publication path (Nexus, workers) passes through. Fail-closed.
	if authorType == dompost.AuthorAgent && s.agents != nil {
		active, aerr := s.agents.IsActive(ctx, authorID)
		if aerr != nil {
			return nil, aerr
		}
		if !active {
			observability.AgentPublishBlockedTotal.Inc()
			return nil, dompost.ErrAgentInactive
		}
	}
	p, err := dompost.NewPost(authorID, authorType, content, metadata, visibility, competitionID)
	if err != nil {
		return nil, err
	}
	if err := s.repo.InsertPost(ctx, p); err != nil {
		return nil, err
	}
	observability.PostsTotal.WithLabelValues(string(p.AuthorType)).Inc()
	if p.AuthorType == dompost.AuthorAgent {
		observability.AgentPostsTotal.Inc()
	}
	return p, nil
}

func (s *Service) Get(ctx context.Context, id uuid.UUID) (*dompost.Post, error) {
	return s.repo.GetPost(ctx, id)
}

func (s *Service) Delete(ctx context.Context, id, requesterID uuid.UUID) error {
	return s.repo.SoftDeletePost(ctx, id, requesterID)
}

// CreateComment enforces the depth rule: post → comment → reply,
// maximum depth 2, no nested trees.
func (s *Service) CreateComment(
	ctx context.Context,
	postID uuid.UUID,
	parentID *uuid.UUID,
	authorID uuid.UUID,
	authorType dompost.AuthorType,
	content string,
) (*dompost.Comment, error) {
	if _, err := s.repo.GetPost(ctx, postID); err != nil {
		return nil, err
	}
	parentDepth := 0
	if parentID != nil {
		parent, err := s.repo.GetComment(ctx, *parentID)
		if err != nil {
			return nil, err
		}
		if parent.PostID != postID {
			return nil, dompost.ErrCommentNotFound
		}
		parentDepth = parent.Depth
	}
	c, err := dompost.NewComment(
		postID, parentID, parentDepth, authorID, authorType, content,
	)
	if err != nil {
		return nil, err
	}
	if err := s.repo.InsertComment(ctx, c); err != nil {
		return nil, err
	}
	observability.CommentsTotal.WithLabelValues(strconv.Itoa(c.Depth)).Inc()
	return c, nil
}

func (s *Service) ListComments(
	ctx context.Context, postID uuid.UUID, limit int, cursor string,
) (dompost.CommentPage, error) {
	if limit <= 0 {
		limit = defaultListLimit
	}
	if limit > maxListLimit {
		limit = maxListLimit
	}
	return s.repo.ListComments(ctx, postID, limit, cursor)
}

func (s *Service) Like(ctx context.Context, postID, userID uuid.UUID) error {
	if err := s.repo.Like(ctx, postID, userID); err != nil {
		return err
	}
	observability.ReactionsTotal.WithLabelValues("like").Inc()
	return nil
}

func (s *Service) Unlike(ctx context.Context, postID, userID uuid.UUID) error {
	if err := s.repo.Unlike(ctx, postID, userID); err != nil {
		return err
	}
	observability.ReactionsTotal.WithLabelValues("unlike").Inc()
	return nil
}

// Share records a repost or an external share.
//
// The two rules that are not the repository's job: a channel belongs only to
// an external share, and an unknown target must not reach SQL. Both produce a
// domain error the API maps to a 400 naming the field.
func (s *Service) Share(
	ctx context.Context, postID, userID uuid.UUID, target, channel string,
) (created bool, count int64, err error) {
	if !dompost.ValidShareTarget(target) {
		return false, 0, dompost.ErrInvalidShareTarget
	}
	if target == dompost.ShareFeed && channel != "" {
		return false, 0, dompost.ErrChannelOnRepost
	}
	return s.repo.Share(ctx, postID, userID, target, channel)
}

// Unshare removes the caller's repost. Idempotent: removing one that is not
// there succeeds, because the button is a toggle and the user's intent is
// satisfied either way.
func (s *Service) Unshare(ctx context.Context, postID, userID uuid.UUID) error {
	return s.repo.Unshare(ctx, postID, userID)
}
