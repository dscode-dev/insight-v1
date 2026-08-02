// Package postgres holds the pgx pool factory for the Gateway's
// `insight_social` database.
//
// Schema inherited from the legacy social service. Per Phase 3, every
// endpoint serves from exactly ONE runtime at a time, controlled by
// the Strangler route table in insight-gateway. No dual-write races.
package postgres

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Pool aliases *pgxpool.Pool so repo constructors + main don't import
// pgx directly. Dependency boundary kept inside this package.
type Pool = *pgxpool.Pool

func Connect(ctx context.Context, databaseURL string, poolSize, maxOverflow int) (Pool, error) {
	cfg, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		return nil, fmt.Errorf("parse database url: %w", err)
	}
	// pgx unifies asyncpg's pool_size + max_overflow into a single
	// MaxConns ceiling. Map total = base + burst.
	cfg.MaxConns = int32(poolSize + maxOverflow)
	cfg.MinConns = int32(poolSize / 2)
	cfg.MaxConnLifetime = 30 * time.Minute
	cfg.MaxConnIdleTime = 5 * time.Minute

	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("pgxpool.NewWithConfig: %w", err)
	}
	pingCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	if err := pool.Ping(pingCtx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("postgres ping: %w", err)
	}
	return pool, nil
}
