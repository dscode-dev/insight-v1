package postgres

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/konoha-labs/insight-gateway/internal/domain/moderation"
)

// ModerationRepo is the Postgres implementation of moderation.Repo (Store-A).
type ModerationRepo struct {
	pool *pgxpool.Pool
}

func NewModerationRepo(pool *pgxpool.Pool) *ModerationRepo {
	return &ModerationRepo{pool: pool}
}

// ---- blocks ----

func (r *ModerationRepo) Block(ctx context.Context, blocker, blocked uuid.UUID) error {
	const q = `INSERT INTO blocked_users (blocker_id, blocked_id) VALUES ($1, $2)
	           ON CONFLICT (blocker_id, blocked_id) DO NOTHING`
	_, err := r.pool.Exec(ctx, q, blocker, blocked)
	return err
}

func (r *ModerationRepo) Unblock(ctx context.Context, blocker, blocked uuid.UUID) error {
	const q = `DELETE FROM blocked_users WHERE blocker_id = $1 AND blocked_id = $2`
	_, err := r.pool.Exec(ctx, q, blocker, blocked)
	return err
}

func (r *ModerationRepo) BlockedBy(ctx context.Context, blocker uuid.UUID) ([]uuid.UUID, error) {
	const q = `SELECT blocked_id FROM blocked_users WHERE blocker_id = $1`
	rows, err := r.pool.Query(ctx, q, blocker)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []uuid.UUID
	for rows.Next() {
		var id uuid.UUID
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		out = append(out, id)
	}
	return out, rows.Err()
}

// ---- reports ----

const reportCols = `id, reporter_id, target_type, target_id, reason, description, status, created_at, updated_at`

func (r *ModerationRepo) CreateReport(ctx context.Context, rep *moderation.Report) error {
	const q = `INSERT INTO moderation_reports
	    (id, reporter_id, target_type, target_id, reason, description, status, created_at, updated_at)
	    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$8)`
	_, err := r.pool.Exec(ctx, q,
		rep.ID, rep.ReporterID, string(rep.TargetType), rep.TargetID,
		string(rep.Reason), nullStr(rep.Description), string(rep.Status), rep.CreatedAt,
	)
	return err
}

func (r *ModerationRepo) ListReports(ctx context.Context, f moderation.ReportFilter) ([]moderation.Report, int64, error) {
	var where []string
	var args []any
	add := func(cond string, val any) {
		args = append(args, val)
		where = append(where, fmt.Sprintf("%s = $%d", cond, len(args)))
	}
	if f.Status != nil {
		add("status", string(*f.Status))
	}
	if f.Reason != nil {
		add("reason", string(*f.Reason))
	}
	if f.TargetType != nil {
		add("target_type", string(*f.TargetType))
	}
	if f.TargetID != nil {
		add("target_id", *f.TargetID)
	}
	if f.ReporterID != nil {
		add("reporter_id", *f.ReporterID)
	}
	clause := ""
	if len(where) > 0 {
		clause = " WHERE " + strings.Join(where, " AND ")
	}

	var total int64
	if err := r.pool.QueryRow(ctx, `SELECT COUNT(*) FROM moderation_reports`+clause, args...).Scan(&total); err != nil {
		return nil, 0, err
	}

	limit := f.Limit
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	args = append(args, limit)
	limIdx := len(args)
	args = append(args, f.Offset)
	offIdx := len(args)
	q := `SELECT ` + reportCols + ` FROM moderation_reports` + clause +
		fmt.Sprintf(" ORDER BY created_at DESC LIMIT $%d OFFSET $%d", limIdx, offIdx)

	rows, err := r.pool.Query(ctx, q, args...)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()
	var out []moderation.Report
	for rows.Next() {
		rep, err := scanReport(rows)
		if err != nil {
			return nil, 0, err
		}
		out = append(out, *rep)
	}
	return out, total, rows.Err()
}

func (r *ModerationRepo) GetReport(ctx context.Context, id uuid.UUID) (*moderation.Report, error) {
	row := r.pool.QueryRow(ctx, `SELECT `+reportCols+` FROM moderation_reports WHERE id = $1`, id)
	rep, err := scanReport(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, moderation.ErrReportNotFound
	}
	return rep, err
}

func (r *ModerationRepo) SetReportStatus(ctx context.Context, id uuid.UUID, s moderation.Status) error {
	tag, err := r.pool.Exec(ctx,
		`UPDATE moderation_reports SET status = $1, updated_at = NOW() WHERE id = $2`, string(s), id)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return moderation.ErrReportNotFound
	}
	return nil
}

func (r *ModerationRepo) CountByStatus(ctx context.Context) (map[moderation.Status]int64, error) {
	rows, err := r.pool.Query(ctx, `SELECT status, COUNT(*) FROM moderation_reports GROUP BY status`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[moderation.Status]int64{}
	for rows.Next() {
		var s string
		var c int64
		if err := rows.Scan(&s, &c); err != nil {
			return nil, err
		}
		out[moderation.Status(s)] = c
	}
	return out, rows.Err()
}

func (r *ModerationRepo) CountByReason(ctx context.Context) ([]moderation.ReasonCount, error) {
	rows, err := r.pool.Query(ctx,
		`SELECT reason, COUNT(*) FROM moderation_reports GROUP BY reason ORDER BY COUNT(*) DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []moderation.ReasonCount
	for rows.Next() {
		var rc moderation.ReasonCount
		var reason string
		if err := rows.Scan(&reason, &rc.Count); err != nil {
			return nil, err
		}
		rc.Reason = moderation.Reason(reason)
		out = append(out, rc)
	}
	return out, rows.Err()
}

func (r *ModerationRepo) TopReportedTargets(ctx context.Context, t moderation.TargetType, limit int) ([]moderation.Aggregate, error) {
	if limit <= 0 {
		limit = 10
	}
	rows, err := r.pool.Query(ctx,
		`SELECT target_id, COUNT(*) FROM moderation_reports WHERE target_type = $1
		 GROUP BY target_id ORDER BY COUNT(*) DESC LIMIT $2`, string(t), limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanAggregates(rows)
}

func (r *ModerationRepo) TopReporters(ctx context.Context, limit int) ([]moderation.Aggregate, error) {
	if limit <= 0 {
		limit = 10
	}
	rows, err := r.pool.Query(ctx,
		`SELECT reporter_id::text, COUNT(*) FROM moderation_reports
		 GROUP BY reporter_id ORDER BY COUNT(*) DESC LIMIT $1`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanAggregates(rows)
}

// ---- actions ----

func (r *ModerationRepo) RecordAction(ctx context.Context, a *moderation.ActionRecord) error {
	const q = `INSERT INTO moderation_actions
	    (id, report_id, moderator_id, action, target_type, target_id, note, created_at)
	    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`
	_, err := r.pool.Exec(ctx, q,
		a.ID, a.ReportID, a.ModeratorID, string(a.Action),
		string(a.TargetType), a.TargetID, nullStr(a.Note), a.CreatedAt,
	)
	return err
}

func (r *ModerationRepo) ListActions(ctx context.Context, limit int) ([]moderation.ActionRecord, error) {
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	rows, err := r.pool.Query(ctx,
		`SELECT id, report_id, moderator_id, action, target_type, target_id, COALESCE(note,''), created_at
		 FROM moderation_actions ORDER BY created_at DESC LIMIT $1`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []moderation.ActionRecord
	for rows.Next() {
		var a moderation.ActionRecord
		var act, tt string
		if err := rows.Scan(&a.ID, &a.ReportID, &a.ModeratorID, &act, &tt, &a.TargetID, &a.Note, &a.CreatedAt); err != nil {
			return nil, err
		}
		a.Action = moderation.Action(act)
		a.TargetType = moderation.TargetType(tt)
		out = append(out, a)
	}
	return out, rows.Err()
}

// ---- hidden content ----

func (r *ModerationRepo) HideContent(ctx context.Context, t moderation.TargetType, id string) error {
	const q = `INSERT INTO moderation_hidden_content (target_type, target_id) VALUES ($1,$2)
	           ON CONFLICT (target_type, target_id) DO NOTHING`
	_, err := r.pool.Exec(ctx, q, string(t), id)
	return err
}

func (r *ModerationRepo) RestoreContent(ctx context.Context, t moderation.TargetType, id string) error {
	const q = `DELETE FROM moderation_hidden_content WHERE target_type = $1 AND target_id = $2`
	_, err := r.pool.Exec(ctx, q, string(t), id)
	return err
}

func (r *ModerationRepo) HiddenContent(ctx context.Context) (map[string]struct{}, error) {
	rows, err := r.pool.Query(ctx, `SELECT target_type, target_id FROM moderation_hidden_content`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[string]struct{}{}
	for rows.Next() {
		var tt, id string
		if err := rows.Scan(&tt, &id); err != nil {
			return nil, err
		}
		out[tt+":"+id] = struct{}{}
	}
	return out, rows.Err()
}

// ---- user state ----

func (r *ModerationRepo) SetUserState(ctx context.Context, userID uuid.UUID, state moderation.UserState, until *time.Time) error {
	const q = `INSERT INTO moderation_user_state (user_id, state, until, updated_at)
	    VALUES ($1,$2,$3,NOW())
	    ON CONFLICT (user_id) DO UPDATE SET state = EXCLUDED.state, until = EXCLUDED.until, updated_at = NOW()`
	_, err := r.pool.Exec(ctx, q, userID, string(state), until)
	return err
}

func (r *ModerationRepo) UserStateOf(ctx context.Context, userID uuid.UUID) (moderation.UserState, *time.Time, error) {
	row := r.pool.QueryRow(ctx, `SELECT state, until FROM moderation_user_state WHERE user_id = $1`, userID)
	var s string
	var until *time.Time
	if err := row.Scan(&s, &until); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return moderation.StateActive, nil, nil
		}
		return moderation.StateActive, nil, err
	}
	return moderation.UserState(s), until, nil
}

// NonActiveUsers returns users whose content should be globally hidden:
// banned users, plus suspended users whose suspension is still in effect.
func (r *ModerationRepo) NonActiveUsers(ctx context.Context) ([]uuid.UUID, error) {
	const q = `SELECT user_id FROM moderation_user_state
	    WHERE state = 'banned'
	       OR (state = 'suspended' AND (until IS NULL OR until > NOW()))`
	rows, err := r.pool.Query(ctx, q)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []uuid.UUID
	for rows.Next() {
		var id uuid.UUID
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		out = append(out, id)
	}
	return out, rows.Err()
}

// ---- helpers ----

type scannable interface {
	Scan(dest ...any) error
}

func scanReport(row scannable) (*moderation.Report, error) {
	var rep moderation.Report
	var tt, reason, status string
	var desc *string
	if err := row.Scan(&rep.ID, &rep.ReporterID, &tt, &rep.TargetID, &reason, &desc, &status, &rep.CreatedAt, &rep.UpdatedAt); err != nil {
		return nil, err
	}
	rep.TargetType = moderation.TargetType(tt)
	rep.Reason = moderation.Reason(reason)
	rep.Status = moderation.Status(status)
	if desc != nil {
		rep.Description = *desc
	}
	return &rep, nil
}

func scanAggregates(rows pgx.Rows) ([]moderation.Aggregate, error) {
	var out []moderation.Aggregate
	for rows.Next() {
		var a moderation.Aggregate
		if err := rows.Scan(&a.Key, &a.Count); err != nil {
			return nil, err
		}
		out = append(out, a)
	}
	return out, rows.Err()
}

func nullStr(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}
