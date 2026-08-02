// Package sentimentrepo is the pgx-backed sentiment Repository.
//
// History downsampling: when the raw row count exceeds MaxPoints we
// use Postgres' `time_bucket`-style decimation via NTILE(). The
// inner query buckets rows into N stripes and we pick the latest
// row in each stripe — preserves shape without TimescaleDB.
package sentimentrepo

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	domsentiment "github.com/konoha-labs/insight-social/internal/domain/sentiment"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres"
)

type Repository struct {
	pool postgres.Pool
}

func New(pool postgres.Pool) *Repository {
	return &Repository{pool: pool}
}

const latestSQL = `
SELECT match_id, home_pct, draw_pct, away_pct, participants, captured_at
  FROM sentiment_snapshots
 WHERE match_id = $1
 ORDER BY captured_at DESC
 LIMIT 1
`

func (r *Repository) Latest(ctx context.Context, matchID uuid.UUID) (domsentiment.Snapshot, error) {
	var s domsentiment.Snapshot
	err := r.pool.QueryRow(ctx, latestSQL, matchID).Scan(
		&s.MatchID, &s.HomePct, &s.DrawPct, &s.AwayPct,
		&s.Participants, &s.CapturedAt,
	)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return domsentiment.Snapshot{}, domsentiment.ErrNotFound
		}
		return domsentiment.Snapshot{}, fmt.Errorf("sentimentrepo latest: %w", err)
	}
	s.CapturedAt = s.CapturedAt.UTC()
	return s, nil
}

// History: downsample via NTILE($3) into MaxPoints buckets,
// take the latest captured_at per bucket. Each surviving row is
// projected into the proto's SentimentPoint shape (lean + pressure)
// at the application layer — the SQL stays denormalised.
const historySQL = `
WITH ranked AS (
    SELECT match_id, home_pct, draw_pct, away_pct, participants, captured_at,
           NTILE($3) OVER (ORDER BY captured_at ASC) AS bucket,
           ROW_NUMBER()  OVER (PARTITION BY NTILE($3) OVER (ORDER BY captured_at ASC)
                               ORDER BY captured_at DESC) AS rn_in_bucket
      FROM sentiment_snapshots
     WHERE match_id = $1 AND captured_at >= $2
)
SELECT home_pct, draw_pct, away_pct, participants, captured_at
  FROM ranked
 WHERE rn_in_bucket = 1
 ORDER BY captured_at ASC
`

func (r *Repository) History(ctx context.Context, f domsentiment.HistoryFilter) ([]domsentiment.Point, error) {
	rows, err := r.pool.Query(ctx, historySQL, f.MatchID, f.From, f.MaxPoints)
	if err != nil {
		return nil, fmt.Errorf("sentimentrepo history: %w", err)
	}
	defer rows.Close()

	out := make([]domsentiment.Point, 0, f.MaxPoints)
	for rows.Next() {
		var (
			homePct, drawPct, awayPct float64
			participants              int64
			capturedAt                time.Time
		)
		if err := rows.Scan(&homePct, &drawPct, &awayPct, &participants, &capturedAt); err != nil {
			return nil, fmt.Errorf("sentimentrepo history scan: %w", err)
		}
		_ = drawPct // not used in Point but selected for parity with Latest scan shape
		// Reuse Snapshot derivations so the formula is centralised.
		snap := domsentiment.Snapshot{
			HomePct:      homePct,
			DrawPct:      drawPct,
			AwayPct:      awayPct,
			Participants: participants,
		}
		out = append(out, domsentiment.Point{
			Ts:       capturedAt.UTC(),
			HomeLean: snap.HomeLean(),
			Pressure: snap.Pressure(),
		})
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("sentimentrepo history rows: %w", err)
	}
	return out, nil
}
