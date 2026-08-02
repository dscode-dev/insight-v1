// nexus-migrate — V1.2 packaging: applies the numbered SQL migrations
// (migrations/sql/NNNN_*.sql) in lexical order against DATABASE_URL.
//
// The migrations are written idempotent (IF NOT EXISTS / ON CONFLICT),
// so re-running the full set is safe; an applied-versions table
// (nexus.schema_migrations) still records progress so a deploy log
// shows exactly what ran when. Ships inside the service image and runs
// as a one-shot compose service before the app starts.
package main

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"time"

	"github.com/jackc/pgx/v5"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "nexus-migrate:", err)
		os.Exit(1)
	}
}

func run() error {
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		return fmt.Errorf("DATABASE_URL required")
	}
	dir := os.Getenv("MIGRATIONS_DIR")
	if dir == "" {
		dir = "/app/migrations/sql"
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()

	conn, err := pgx.Connect(ctx, dsn)
	if err != nil {
		return fmt.Errorf("connect: %w", err)
	}
	defer func() { _ = conn.Close(ctx) }()

	if _, err := conn.Exec(ctx, `
		CREATE SCHEMA IF NOT EXISTS nexus;
		CREATE TABLE IF NOT EXISTS nexus.schema_migrations (
			filename   TEXT PRIMARY KEY,
			applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
		);`); err != nil {
		return fmt.Errorf("bootstrap: %w", err)
	}

	files, err := filepath.Glob(filepath.Join(dir, "*.sql"))
	if err != nil {
		return err
	}
	sort.Strings(files)
	if len(files) == 0 {
		return fmt.Errorf("no migrations found in %s", dir)
	}

	for _, f := range files {
		name := filepath.Base(f)
		var done bool
		if err := conn.QueryRow(ctx,
			`SELECT EXISTS(SELECT 1 FROM nexus.schema_migrations WHERE filename=$1)`,
			name).Scan(&done); err != nil {
			return fmt.Errorf("%s: check: %w", name, err)
		}
		if done {
			fmt.Println("skip ", name)
			continue
		}
		sql, err := os.ReadFile(f)
		if err != nil {
			return fmt.Errorf("%s: read: %w", name, err)
		}
		tx, err := conn.Begin(ctx)
		if err != nil {
			return fmt.Errorf("%s: begin: %w", name, err)
		}
		if _, err := tx.Exec(ctx, string(sql)); err != nil {
			_ = tx.Rollback(ctx)
			return fmt.Errorf("%s: apply: %w", name, err)
		}
		if _, err := tx.Exec(ctx,
			`INSERT INTO nexus.schema_migrations (filename) VALUES ($1)`,
			name); err != nil {
			_ = tx.Rollback(ctx)
			return fmt.Errorf("%s: record: %w", name, err)
		}
		if err := tx.Commit(ctx); err != nil {
			return fmt.Errorf("%s: commit: %w", name, err)
		}
		fmt.Println("apply", name)
	}
	fmt.Println("nexus migrations up to date")
	return nil
}
