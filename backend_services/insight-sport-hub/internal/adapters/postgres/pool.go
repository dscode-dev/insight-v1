// Package postgres — pgx-backed adapters for every repository port.
//
// Sprint 1 ships with 4 repository implementations + the shared
// pool factory. All adapters share the same error-mapping rules:
//
//   - pgx.ErrNoRows                              → ports.ErrNotFound
//   - pgconn.PgError code 23505 (unique violation) → ports.ErrDuplicate
//
// JSONB columns carry SourceRef + payload exactly as received —
// lineage preservation is the architectural rule, so no truncation
// or projection at the persistence layer.
package postgres

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Pool aliases *pgxpool.Pool so the repo constructors don't import
// pgx directly. Same pattern as insight-social.
type Pool = *pgxpool.Pool

// Connect returns a configured pool with the standard insight-go
// tuning (30min MaxConnLifetime, 5min MaxConnIdleTime, boot-time
// ping). The maxOverflow param mirrors Python asyncpg semantics so
// every Insight service expresses connection caps the same way.
func Connect(ctx context.Context, databaseURL string, poolSize, maxOverflow int) (Pool, error) {
	cfg, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		return nil, fmt.Errorf("postgres: parse url: %w", err)
	}
	cfg.MaxConns = int32(poolSize + maxOverflow)
	cfg.MinConns = int32(poolSize / 2)
	cfg.MaxConnLifetime = 30 * time.Minute
	cfg.MaxConnIdleTime = 5 * time.Minute

	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("postgres: pool: %w", err)
	}
	pingCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	if err := pool.Ping(pingCtx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("postgres: ping: %w", err)
	}
	return pool, nil
}
