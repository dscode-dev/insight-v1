// Package user is the application service for the User aggregate.
//
// Use cases ARE the public API of this package — one method per
// social.v1.UserService RPC. The service owns no state; it composes
// the domain port with cross-cutting concerns (none yet — no caching,
// no outbox).
package user

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	domuser "github.com/konoha-labs/insight-social/internal/domain/user"
	"github.com/konoha-labs/insight-social/internal/observability"
)

// AgentDirectory supplies the active agents every new user follows.
type AgentDirectory interface {
	ActiveIDs(ctx context.Context) ([]uuid.UUID, error)
}

// FollowCreator creates follow edges idempotently (re-running the
// auto-follow for an existing user is a no-op).
type FollowCreator interface {
	FollowIdempotent(ctx context.Context, actorID, targetID uuid.UUID) error
}

type Service struct {
	repo    domuser.Repository
	agents  AgentDirectory
	follows FollowCreator
}

func New(repo domuser.Repository) *Service {
	return &Service{repo: repo}
}

// WithAgentAutoFollow wires the Sprint 3 default: every new user
// automatically follows all active agents.
func (s *Service) WithAgentAutoFollow(agents AgentDirectory, follows FollowCreator) *Service {
	s.agents = agents
	s.follows = follows
	return s
}

// Create constructs a fresh User aggregate and persists it. Returns
// domuser.ErrUsernameTaken if the username is already in use (race
// condition between the unique check and the insert is left to the DB
// — pgx surfaces the unique-violation, repo translates it).
func (s *Service) Create(ctx context.Context, username, displayName, accentColor string) (*domuser.User, error) {
	u, err := domuser.New(username, displayName, accentColor)
	if err != nil {
		return nil, err
	}
	if err := s.repo.Insert(ctx, u); err != nil {
		return nil, fmt.Errorf("insert user: %w", err)
	}
	if err := s.autoFollowAgents(ctx, u.ID()); err != nil {
		// The user exists; the default graph is best-effort but loud.
		// Idempotent retry: re-running auto-follow later is safe.
		return nil, fmt.Errorf("auto-follow agents: %w", err)
	}
	return u, nil
}

// autoFollowAgents creates follow edges from the new user to every
// active agent (Sprint 3 Part 3). Idempotent: FollowIdempotent
// no-ops on existing edges, so retries and replays are safe and
// existing users are unaffected.
func (s *Service) autoFollowAgents(ctx context.Context, userID uuid.UUID) error {
	if s.agents == nil || s.follows == nil {
		return nil
	}
	agentIDs, err := s.agents.ActiveIDs(ctx)
	if err != nil {
		return err
	}
	for _, agentID := range agentIDs {
		if err := s.follows.FollowIdempotent(ctx, userID, agentID); err != nil {
			return err
		}
		observability.FollowsTotal.WithLabelValues("auto_agent").Inc()
	}
	return nil
}

func (s *Service) Get(ctx context.Context, id uuid.UUID) (*domuser.User, error) {
	return s.repo.GetByID(ctx, id)
}

func (s *Service) GetByUsername(ctx context.Context, username string) (*domuser.User, error) {
	return s.repo.GetByUsername(ctx, username)
}

func (s *Service) UpdateAccent(ctx context.Context, id uuid.UUID, accentColor string) (*domuser.User, error) {
	if err := domuser.ValidateAccentColor(accentColor); err != nil {
		return nil, err
	}
	return s.repo.UpdateAccent(ctx, id, accentColor)
}

// UpdateAvatar — Sprint C. Empty avatarURL clears the avatar.
func (s *Service) UpdateAvatar(ctx context.Context, id uuid.UUID, avatarURL string) (*domuser.User, error) {
	if err := domuser.ValidateAvatarURL(avatarURL); err != nil {
		return nil, err
	}
	return s.repo.UpdateAvatar(ctx, id, avatarURL)
}

func (s *Service) List(ctx context.Context, ids []uuid.UUID) ([]*domuser.User, error) {
	if len(ids) == 0 {
		return nil, nil
	}
	return s.repo.List(ctx, ids)
}

func (s *Service) Stats(ctx context.Context, id uuid.UUID) (domuser.Stats, error) {
	return s.repo.Stats(ctx, id)
}
