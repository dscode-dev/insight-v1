// Package source — SourceRegistryService.
//
// CRUD over Source aggregates. Thin — invariants live in the
// domain layer; this service only orchestrates persistence + emits
// metrics on registration.
package source

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"

	domsource "github.com/konoha-labs/insight-sports-hub/internal/domain/source"
	"github.com/konoha-labs/insight-sports-hub/internal/ports"
)

type Service struct {
	repo    ports.SourceRepository
	metrics ports.Metrics
}

func New(repo ports.SourceRepository, metrics ports.Metrics) *Service {
	return &Service{repo: repo, metrics: metrics}
}

// Register persists a new Source. Caller passes pre-constructed
// aggregate (the domain constructor already validated). Returns
// ports.ErrDuplicate when the (id) or (name) collides.
func (s *Service) Register(ctx context.Context, src *domsource.Source) error {
	if err := s.repo.Insert(ctx, src); err != nil {
		return fmt.Errorf("source registry: insert: %w", err)
	}
	s.refreshEnabledGauge(ctx)
	return nil
}

// List returns every registered source, enabled or not. The gauge
// refresh is opportunistic — calling this from an admin endpoint is
// a fine moment to re-emit the counter.
func (s *Service) List(ctx context.Context) ([]*domsource.Source, error) {
	out, err := s.repo.List(ctx)
	if err != nil {
		return nil, fmt.Errorf("source registry: list: %w", err)
	}
	return out, nil
}

func (s *Service) Get(ctx context.Context, id uuid.UUID) (*domsource.Source, error) {
	src, err := s.repo.GetByID(ctx, id)
	if err != nil {
		if errors.Is(err, ports.ErrNotFound) {
			return nil, err
		}
		return nil, fmt.Errorf("source registry: get: %w", err)
	}
	return src, nil
}

// SetEnabled flips a source on/off, then re-emits the gauge so
// observability reflects the new count immediately rather than at
// the next scrape.
func (s *Service) SetEnabled(ctx context.Context, id uuid.UUID, enabled bool) error {
	src, err := s.repo.GetByID(ctx, id)
	if err != nil {
		return err
	}
	if enabled {
		src.Enable()
	} else {
		src.Disable()
	}
	if err := s.repo.Update(ctx, src); err != nil {
		return fmt.Errorf("source registry: update: %w", err)
	}
	s.refreshEnabledGauge(ctx)
	return nil
}

// refreshEnabledGauge swallows errors — observability is not
// load-bearing for the service's correctness; a stale gauge is
// preferable to a failed registration.
func (s *Service) refreshEnabledGauge(ctx context.Context) {
	all, err := s.repo.List(ctx)
	if err != nil {
		return
	}
	enabled := 0
	for _, src := range all {
		if src.Enabled() {
			enabled++
		}
	}
	s.metrics.SetRegisteredSources(enabled)
}
