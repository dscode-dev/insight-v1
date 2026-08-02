// Postgres Sprint 4 repositories: personas, publication candidates,
// tickets and the anti-spam publication log.
package postgres

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/konoha-labs/insight-nexus/internal/application/antispam"
	"github.com/konoha-labs/insight-nexus/internal/domain/persona"
	"github.com/konoha-labs/insight-nexus/internal/domain/publication"
	"github.com/konoha-labs/insight-nexus/internal/ports"
)

// ---- PersonaRepo ------------------------------------------------------------

type PersonaRepo struct{ pool *pgxpool.Pool }

func NewPersonaRepo(pool *pgxpool.Pool) *PersonaRepo { return &PersonaRepo{pool: pool} }

func (r *PersonaRepo) Get(ctx context.Context, slug string) (persona.AgentPersona, error) {
	row := r.pool.QueryRow(ctx, `
		SELECT slug, social_author_id, style, tone, expertise, restrictions,
		       posting_behavior, updated_at
		FROM nexus.personas WHERE slug = $1`, slug)
	return scanPersona(row)
}

func (r *PersonaRepo) List(ctx context.Context) ([]persona.AgentPersona, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT slug, social_author_id, style, tone, expertise, restrictions,
		       posting_behavior, updated_at
		FROM nexus.personas ORDER BY slug`)
	if err != nil {
		return nil, fmt.Errorf("personas list: %w", err)
	}
	defer rows.Close()
	var out []persona.AgentPersona
	for rows.Next() {
		p, err := scanPersona(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, rows.Err()
}

func (r *PersonaRepo) Upsert(ctx context.Context, p persona.AgentPersona) error {
	if err := p.Validate(); err != nil {
		return err
	}
	restrictions, err := json.Marshal(p.Restrictions)
	if err != nil {
		return err
	}
	_, err = r.pool.Exec(ctx, `
		INSERT INTO nexus.personas
			(slug, social_author_id, style, tone, expertise, restrictions,
			 posting_behavior, updated_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,now())
		ON CONFLICT (slug) DO UPDATE SET
			social_author_id = EXCLUDED.social_author_id,
			style = EXCLUDED.style, tone = EXCLUDED.tone,
			expertise = EXCLUDED.expertise,
			restrictions = EXCLUDED.restrictions,
			posting_behavior = EXCLUDED.posting_behavior,
			updated_at = now()`,
		p.Slug, p.SocialAuthorID, p.Style, p.Tone, p.Expertise,
		restrictions, p.PostingBehavior,
	)
	if err != nil {
		return fmt.Errorf("personas upsert: %w", err)
	}
	return nil
}

func scanPersona(row pgx.Row) (persona.AgentPersona, error) {
	var p persona.AgentPersona
	var restrictions []byte
	err := row.Scan(&p.Slug, &p.SocialAuthorID, &p.Style, &p.Tone,
		&p.Expertise, &restrictions, &p.PostingBehavior, &p.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return p, ports.ErrNotFound
	}
	if err != nil {
		return p, fmt.Errorf("personas scan: %w", err)
	}
	if len(restrictions) > 0 {
		_ = json.Unmarshal(restrictions, &p.Restrictions)
	}
	return p, nil
}

// ---- CandidateRepo -----------------------------------------------------------

type CandidateRepo struct{ pool *pgxpool.Pool }

func NewCandidateRepo(pool *pgxpool.Pool) *CandidateRepo {
	return &CandidateRepo{pool: pool}
}

func (r *CandidateRepo) Save(ctx context.Context, c publication.Candidate) error {
	if err := c.Validate(); err != nil {
		return err
	}
	trendIDs, _ := json.Marshal(c.TrendIDs)
	chain, _ := json.Marshal(c.FallbackChain)
	highlights, _ := json.Marshal(c.Highlights)
	tags, _ := json.Marshal(c.Tags)
	chartHints, _ := json.Marshal(c.ChartHints)
	var clusterID, decisionID any
	if c.ClusterID != uuid.Nil {
		clusterID = c.ClusterID
	}
	if c.DecisionID != uuid.Nil {
		decisionID = c.DecisionID
	}
	_, err := r.pool.Exec(ctx, `
		INSERT INTO nexus.publication_candidates
			(id, draft_id, agent_id, agent_name, trend_ids, cluster_id,
			 decision_id, publication_reason, prompt_version, provider, model,
			 fallback_used, fallback_chain, draft_version, title, summary,
			 highlights, tags, chart_hints, match_id, status, status_reason,
			 social_post_id, created_at, published_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,
		        $18,$19,$20,$21,$22,$23,$24,$25)
		ON CONFLICT (id) DO UPDATE SET
			status = EXCLUDED.status,
			status_reason = EXCLUDED.status_reason,
			social_post_id = EXCLUDED.social_post_id,
			published_at = EXCLUDED.published_at`,
		c.ID, c.DraftID, c.AgentID, c.AgentName, trendIDs, clusterID,
		decisionID, c.PublicationReason, c.PromptVersion, c.Provider, c.Model,
		c.FallbackUsed, chain, c.DraftVersion, c.Title, c.Summary,
		highlights, tags, chartHints, c.MatchID, string(c.Status),
		c.StatusReason, c.SocialPostID, c.CreatedAt, c.PublishedAt,
	)
	if err != nil {
		return fmt.Errorf("candidates save: %w", err)
	}
	return nil
}

const candidateCols = `
	id, draft_id, agent_id, agent_name, trend_ids,
	COALESCE(cluster_id, '00000000-0000-0000-0000-000000000000'::uuid),
	COALESCE(decision_id, '00000000-0000-0000-0000-000000000000'::uuid),
	publication_reason, prompt_version, provider, model, fallback_used,
	fallback_chain, draft_version, title, summary, highlights, tags,
	chart_hints, match_id, status, status_reason, social_post_id,
	created_at, published_at`

func (r *CandidateRepo) List(
	ctx context.Context, status publication.CandidateStatus, limit int,
) ([]publication.Candidate, error) {
	query := `SELECT ` + candidateCols + ` FROM nexus.publication_candidates`
	args := []any{}
	if status != "" {
		query += ` WHERE status = $1 ORDER BY created_at DESC LIMIT $2`
		args = append(args, string(status), limit)
	} else {
		query += ` ORDER BY created_at DESC LIMIT $1`
		args = append(args, limit)
	}
	rows, err := r.pool.Query(ctx, query, args...)
	if err != nil {
		return nil, fmt.Errorf("candidates list: %w", err)
	}
	defer rows.Close()
	return scanCandidates(rows)
}

func (r *CandidateRepo) History(ctx context.Context, limit int) ([]publication.Candidate, error) {
	return r.List(ctx, publication.CandidatePublished, limit)
}

func (r *CandidateRepo) AgentCounts(ctx context.Context) (map[string]map[string]int, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT agent_name, status, COUNT(*)
		FROM nexus.publication_candidates
		GROUP BY agent_name, status`)
	if err != nil {
		return nil, fmt.Errorf("candidates agent_counts: %w", err)
	}
	defer rows.Close()
	out := map[string]map[string]int{}
	for rows.Next() {
		var agent, status string
		var n int
		if err := rows.Scan(&agent, &status, &n); err != nil {
			return nil, err
		}
		if out[agent] == nil {
			out[agent] = map[string]int{}
		}
		out[agent][status] = n
	}
	return out, rows.Err()
}

func scanCandidates(rows pgx.Rows) ([]publication.Candidate, error) {
	var out []publication.Candidate
	for rows.Next() {
		var c publication.Candidate
		var trendIDs, chain, highlights, tags, chartHints []byte
		var status string
		if err := rows.Scan(&c.ID, &c.DraftID, &c.AgentID, &c.AgentName,
			&trendIDs, &c.ClusterID, &c.DecisionID, &c.PublicationReason,
			&c.PromptVersion, &c.Provider, &c.Model, &c.FallbackUsed,
			&chain, &c.DraftVersion, &c.Title, &c.Summary, &highlights,
			&tags, &chartHints, &c.MatchID, &status, &c.StatusReason,
			&c.SocialPostID, &c.CreatedAt, &c.PublishedAt); err != nil {
			return nil, err
		}
		c.Status = publication.CandidateStatus(status)
		_ = json.Unmarshal(trendIDs, &c.TrendIDs)
		_ = json.Unmarshal(chain, &c.FallbackChain)
		_ = json.Unmarshal(highlights, &c.Highlights)
		_ = json.Unmarshal(tags, &c.Tags)
		_ = json.Unmarshal(chartHints, &c.ChartHints)
		out = append(out, c)
	}
	return out, rows.Err()
}

// ---- TicketRepo --------------------------------------------------------------------

type TicketRepo struct{ pool *pgxpool.Pool }

func NewTicketRepo(pool *pgxpool.Pool) *TicketRepo { return &TicketRepo{pool: pool} }

func (r *TicketRepo) Save(ctx context.Context, t publication.Ticket) error {
	trendIDs, _ := json.Marshal(t.TrendIDs)
	contextJSON, _ := json.Marshal(t.Context)
	evidence, _ := json.Marshal(t.Evidence)
	var clusterID any
	if t.ClusterID != uuid.Nil {
		clusterID = t.ClusterID
	}
	_, err := r.pool.Exec(ctx, `
		INSERT INTO nexus.publication_tickets
			(id, agent_id, agent_name, trend_ids, cluster_id, context,
			 publication_reason, suggested_title, suggested_summary, evidence,
			 priority, match_id, status, reviewed_by, reviewed_at,
			 published_by, published_at, created_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
		ON CONFLICT (id) DO UPDATE SET
			status = EXCLUDED.status,
			reviewed_by = EXCLUDED.reviewed_by,
			reviewed_at = EXCLUDED.reviewed_at,
			published_by = EXCLUDED.published_by,
			published_at = EXCLUDED.published_at`,
		t.ID, t.AgentID, t.AgentName, trendIDs, clusterID, contextJSON,
		t.PublicationReason, t.SuggestedTitle, t.SuggestedSummary, evidence,
		t.Priority, t.MatchID, string(t.Status), t.ReviewedBy, t.ReviewedAt,
		t.PublishedBy, t.PublishedAt, t.CreatedAt,
	)
	if err != nil {
		return fmt.Errorf("tickets save: %w", err)
	}
	return nil
}

const ticketCols = `
	id, agent_id, agent_name, trend_ids,
	COALESCE(cluster_id, '00000000-0000-0000-0000-000000000000'::uuid),
	context, publication_reason, suggested_title, suggested_summary,
	evidence, priority, match_id, status, reviewed_by, reviewed_at,
	published_by, published_at, created_at`

func (r *TicketRepo) Get(ctx context.Context, id uuid.UUID) (publication.Ticket, error) {
	row := r.pool.QueryRow(ctx,
		`SELECT `+ticketCols+` FROM nexus.publication_tickets WHERE id = $1`, id)
	t, err := scanTicket(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return t, ports.ErrNotFound
	}
	return t, err
}

func (r *TicketRepo) List(
	ctx context.Context, status publication.TicketStatus, limit int,
) ([]publication.Ticket, error) {
	query := `SELECT ` + ticketCols + ` FROM nexus.publication_tickets`
	args := []any{}
	if status != "" {
		query += ` WHERE status = $1 ORDER BY created_at DESC LIMIT $2`
		args = append(args, string(status), limit)
	} else {
		query += ` ORDER BY created_at DESC LIMIT $1`
		args = append(args, limit)
	}
	rows, err := r.pool.Query(ctx, query, args...)
	if err != nil {
		return nil, fmt.Errorf("tickets list: %w", err)
	}
	defer rows.Close()
	var out []publication.Ticket
	for rows.Next() {
		t, err := scanTicket(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, t)
	}
	return out, rows.Err()
}

func scanTicket(row pgx.Row) (publication.Ticket, error) {
	var t publication.Ticket
	var trendIDs, contextJSON, evidence []byte
	var status string
	err := row.Scan(&t.ID, &t.AgentID, &t.AgentName, &trendIDs, &t.ClusterID,
		&contextJSON, &t.PublicationReason, &t.SuggestedTitle,
		&t.SuggestedSummary, &evidence, &t.Priority, &t.MatchID, &status,
		&t.ReviewedBy, &t.ReviewedAt, &t.PublishedBy, &t.PublishedAt,
		&t.CreatedAt)
	if err != nil {
		return t, err
	}
	t.Status = publication.TicketStatus(status)
	_ = json.Unmarshal(trendIDs, &t.TrendIDs)
	_ = json.Unmarshal(contextJSON, &t.Context)
	_ = json.Unmarshal(evidence, &t.Evidence)
	return t, nil
}

// ---- antispam.Log ---------------------------------------------------------------------

type SpamLog struct{ pool *pgxpool.Pool }

func NewSpamLog(pool *pgxpool.Pool) *SpamLog { return &SpamLog{pool: pool} }

func (l *SpamLog) Record(ctx context.Context, e antispam.Entry) error {
	var clusterID any
	if e.ClusterID != uuid.Nil {
		clusterID = e.ClusterID
	}
	_, err := l.pool.Exec(ctx, `
		INSERT INTO nexus.publication_log
			(agent_id, cluster_id, trend_id, match_id, published_at)
		VALUES ($1,$2,$3,$4,$5)`,
		e.AgentID, clusterID, e.TrendID, e.MatchID, e.PublishedAt,
	)
	if err != nil {
		return fmt.Errorf("publication_log record: %w", err)
	}
	return nil
}

func (l *SpamLog) lastWhere(ctx context.Context, where string, args ...any) (time.Time, error) {
	var t *time.Time
	err := l.pool.QueryRow(ctx,
		`SELECT MAX(published_at) FROM nexus.publication_log WHERE `+where,
		args...).Scan(&t)
	if err != nil {
		return time.Time{}, fmt.Errorf("publication_log last: %w", err)
	}
	if t == nil {
		return time.Time{}, nil
	}
	return t.UTC(), nil
}

func (l *SpamLog) LastByAgent(ctx context.Context, agentID uuid.UUID) (time.Time, error) {
	return l.lastWhere(ctx, `agent_id = $1`, agentID)
}

func (l *SpamLog) LastByCluster(ctx context.Context, clusterID uuid.UUID) (time.Time, error) {
	return l.lastWhere(ctx, `cluster_id = $1`, clusterID)
}

func (l *SpamLog) LastByTrend(ctx context.Context, trendID string) (time.Time, error) {
	return l.lastWhere(ctx, `trend_id = $1`, trendID)
}

func (l *SpamLog) LastByAgentMatch(ctx context.Context, agentID uuid.UUID, matchID string) (time.Time, error) {
	return l.lastWhere(ctx, `agent_id = $1 AND match_id = $2`, agentID, matchID)
}

func (l *SpamLog) CountByAgentSince(ctx context.Context, agentID uuid.UUID, since time.Time) (int, error) {
	var n int
	err := l.pool.QueryRow(ctx, `
		SELECT COUNT(*) FROM nexus.publication_log
		WHERE agent_id = $1 AND published_at > $2`,
		agentID, since).Scan(&n)
	if err != nil {
		return 0, fmt.Errorf("publication_log count: %w", err)
	}
	return n, nil
}

var (
	_ ports.PersonaRepository   = (*PersonaRepo)(nil)
	_ ports.CandidateRepository = (*CandidateRepo)(nil)
	_ ports.TicketRepository    = (*TicketRepo)(nil)
	_ antispam.Log              = (*SpamLog)(nil)
)

// ---- AuditRepo (Sprint 4.5 — immutable console audit) ------------------------

type AuditRepo struct{ pool *pgxpool.Pool }

func NewAuditRepo(pool *pgxpool.Pool) *AuditRepo { return &AuditRepo{pool: pool} }

func (r *AuditRepo) Record(ctx context.Context, e publication.AuditEvent) error {
	before, _ := json.Marshal(e.Before)
	after, _ := json.Marshal(e.After)
	_, err := r.pool.Exec(ctx, `
		INSERT INTO nexus.console_audit
			(id, actor, action, entity_type, entity_id, before, after, reason, created_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)`,
		e.ID, e.Actor, e.Action, e.EntityType, e.EntityID, before, after,
		e.Reason, e.CreatedAt,
	)
	if err != nil {
		return fmt.Errorf("console_audit record: %w", err)
	}
	return nil
}

func (r *AuditRepo) List(ctx context.Context, f ports.AuditFilter) ([]publication.AuditEvent, error) {
	query := `SELECT id, actor, action, entity_type, entity_id, before, after, reason, created_at
		FROM nexus.console_audit WHERE 1=1`
	args := []any{}
	n := 0
	add := func(cond, val string) {
		if val != "" {
			n++
			query += fmt.Sprintf(" AND %s = $%d", cond, n)
			args = append(args, val)
		}
	}
	add("actor", f.Actor)
	add("action", f.Action)
	add("entity_type", f.EntityType)
	add("entity_id", f.EntityID)
	limit := f.Limit
	if limit <= 0 || limit > 500 {
		limit = 100
	}
	n++
	query += fmt.Sprintf(" ORDER BY created_at DESC LIMIT $%d", n)
	args = append(args, limit)

	rows, err := r.pool.Query(ctx, query, args...)
	if err != nil {
		return nil, fmt.Errorf("console_audit list: %w", err)
	}
	defer rows.Close()
	var out []publication.AuditEvent
	for rows.Next() {
		var e publication.AuditEvent
		var before, after []byte
		if err := rows.Scan(&e.ID, &e.Actor, &e.Action, &e.EntityType,
			&e.EntityID, &before, &after, &e.Reason, &e.CreatedAt); err != nil {
			return nil, err
		}
		_ = json.Unmarshal(before, &e.Before)
		_ = json.Unmarshal(after, &e.After)
		out = append(out, e)
	}
	return out, rows.Err()
}

var _ ports.AuditRepository = (*AuditRepo)(nil)
