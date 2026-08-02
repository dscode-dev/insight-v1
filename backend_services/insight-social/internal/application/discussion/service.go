// Package discussion is the application service for the Discussion
// aggregate.
//
// Use cases:
//   - ListForCommunity  (paged)
//   - Start             (new discussion from author within community)
//   - PostMessage       (reply on existing discussion)
//   - ListMessages      (paged messages on a discussion)
package discussion

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	domdiscussion "github.com/konoha-labs/insight-social/internal/domain/discussion"
)

const (
	defaultListLimit = 20
	maxListLimit     = 100
)

type Service struct {
	repo domdiscussion.Repository
}

func New(repo domdiscussion.Repository) *Service {
	return &Service{repo: repo}
}

func (s *Service) Get(ctx context.Context, id uuid.UUID) (*domdiscussion.Discussion, error) {
	return s.repo.GetByID(ctx, id)
}

func (s *Service) ListForCommunity(ctx context.Context, communityID uuid.UUID, limit int, cursor string) (domdiscussion.ListPage, error) {
	return s.repo.ListForCommunity(ctx, domdiscussion.ListFilter{
		CommunityID: communityID,
		Limit:       clampLimit(limit),
		Cursor:      cursor,
	})
}

func (s *Service) Start(ctx context.Context, communityID, authorID uuid.UUID, title, body string, matchID *uuid.UUID) (*domdiscussion.Discussion, error) {
	d, err := domdiscussion.Start(communityID, authorID, title, body, matchID)
	if err != nil {
		return nil, err
	}
	if err := s.repo.Insert(ctx, d); err != nil {
		return nil, fmt.Errorf("insert discussion: %w", err)
	}
	return d, nil
}

func (s *Service) PostMessage(ctx context.Context, discussionID, authorID uuid.UUID, body string) (*domdiscussion.Message, error) {
	m, err := domdiscussion.NewMessage(discussionID, authorID, body)
	if err != nil {
		return nil, err
	}
	if err := s.repo.InsertMessage(ctx, m); err != nil {
		return nil, fmt.Errorf("insert message: %w", err)
	}
	return m, nil
}

func (s *Service) ListMessages(ctx context.Context, discussionID uuid.UUID, limit int, cursor string) (domdiscussion.MessageListPage, error) {
	return s.repo.ListMessages(ctx, domdiscussion.MessageListFilter{
		DiscussionID: discussionID,
		Limit:        clampLimit(limit),
		Cursor:       cursor,
	})
}

func clampLimit(limit int) int {
	if limit <= 0 {
		return defaultListLimit
	}
	if limit > maxListLimit {
		return maxListLimit
	}
	return limit
}
