// Package postgres holds the pgx connection pool factory for the
// Gateway's `insight_auth` database.
//
// During the Strangler overlap, this pool coexists with the asyncpg
// pool a legacy service maintained against the same DB. That's fine —
// every endpoint serves from exactly ONE runtime at a time, controlled
// by the Strangler route table, so no dual-write races.
package postgres

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Pool aliases *pgxpool.Pool so call sites (main.go, repo constructors)
// don't need to import pgx directly. Keeps the dependency boundary
// inside this package.
type Pool = *pgxpool.Pool

// Connect builds a pool sized for the Gateway's read+write profile.
// `databaseURL` follows the standard libpq URI form.
//
// The pool is verified at boot via `Ping`. A failure here aborts the
// process before traffic flows — preferable to surfacing the broken
// DB as 500s on every request.
func Connect(ctx context.Context, databaseURL string, poolSize, maxOverflow int) (*pgxpool.Pool, error) {
	cfg, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		return nil, fmt.Errorf("parse database url: %w", err)
	}

	// pgx names work differently than asyncpg: `MaxConns` is the total
	// ceiling. We map poolSize+maxOverflow onto a single MaxConns
	// since pgx doesn't separate base from burst.
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
