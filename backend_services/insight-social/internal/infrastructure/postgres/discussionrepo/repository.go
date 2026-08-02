// Package discussionrepo is the pgx-backed Discussion repository.
//
// Two paginated reads: discussions for a community (DESC by
// last_activity_ts so hot threads bubble up) and messages on a
// discussion (ASC by created_at so chronology reads naturally).
//
// Cross-aggregate FK: discussions.community_id REFERENCES communities.
// When the community is missing, pgx surfaces a foreign_key_violation
// — we translate that to discussion.ErrCommunityNotFound rather than
// a generic Internal so the handler can return PreconditionFailed.
package discussionrepo

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgerrcode"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	domdiscussion "github.com/konoha-labs/insight-social/internal/domain/discussion"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/pagination"
)

type Repository struct {
	pool postgres.Pool
}

func New(pool postgres.Pool) *Repository {
	return &Repository{pool: pool}
}

// ---- discussions ----

const insertDiscussionSQL = `
INSERT INTO discussions (
    id, community_id, author_id, title, body, match_id,
    message_count, participant_count, last_activity_ts, created_at
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
`

func (r *Repository) Insert(ctx context.Context, d *domdiscussion.Discussion) error {
	_, err := r.pool.Exec(ctx, insertDiscussionSQL,
		d.ID(), d.CommunityID(), d.AuthorID(), d.Title(), d.Body(), d.MatchID(),
		d.MessageCount(), d.ParticipantCount(), d.LastActivityTs(), d.CreatedAt(),
	)
	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == pgerrcode.ForeignKeyViolation {
			return domdiscussion.ErrCommunityNotFound
		}
		return fmt.Errorf("discussionrepo insert: %w", err)
	}
	return nil
}

const discussionCols = `
id, community_id, author_id, title, body, match_id,
message_count, participant_count, last_activity_ts, created_at
`

func (r *Repository) GetByID(ctx context.Context, id uuid.UUID) (*domdiscussion.Discussion, error) {
	return scanDiscussion(r.pool.QueryRow(ctx,
		`SELECT `+discussionCols+` FROM discussions WHERE id = $1`, id))
}

// ListForCommunity: keyset on (last_activity_ts DESC, id DESC) — hot
// threads first, stable under concurrent activity.
const listDiscussionsSQL = `
SELECT ` + discussionCols + `
  FROM discussions
 WHERE community_id = $1
   AND ($3::timestamptz IS NULL OR (last_activity_ts, id) < ($3, $4))
 ORDER BY last_activity_ts DESC, id DESC
 LIMIT $2
`

func (r *Repository) ListForCommunity(ctx context.Context, f domdiscussion.ListFilter) (domdiscussion.ListPage, error) {
	cursorTS, cursorID, err := pagination.Decode(f.Cursor)
	if err != nil {
		return domdiscussion.ListPage{}, err
	}
	var tsArg, idArg any
	if !cursorTS.IsZero() {
		tsArg = cursorTS
		idArg = cursorID
	}

	rows, err := r.pool.Query(ctx, listDiscussionsSQL, f.CommunityID, f.Limit, tsArg, idArg)
	if err != nil {
		return domdiscussion.ListPage{}, fmt.Errorf("discussionrepo list: %w", err)
	}
	defer rows.Close()

	out := make([]*domdiscussion.Discussion, 0, f.Limit)
	for rows.Next() {
		d, err := scanDiscussion(rows)
		if err != nil {
			return domdiscussion.ListPage{}, err
		}
		out = append(out, d)
	}
	if err := rows.Err(); err != nil {
		return domdiscussion.ListPage{}, fmt.Errorf("discussionrepo list rows: %w", err)
	}

	page := domdiscussion.ListPage{Discussions: out}
	if len(out) == f.Limit {
		last := out[len(out)-1]
		page.NextCursor = pagination.Encode(last.LastActivityTs(), last.ID())
	}
	return page, nil
}

// ---- messages ----
//
// InsertMessage does THREE things atomically (single round-trip via
// CTE):
//  1. INSERT row in discussion_messages
//  2. UPDATE discussions.message_count += 1, last_activity_ts = NOW()
//  3. UPDATE discussions.participant_count = (count distinct authors)
//     — recomputed not incremented because the same author posting
//     twice shouldn't double-count.
const insertMessageSQL = `
WITH msg AS (
    INSERT INTO discussion_messages (discussion_id, author_id, body, created_at)
    VALUES ($1, $2, $3, NOW())
    RETURNING id, discussion_id, author_id, body, created_at
), bumped AS (
    UPDATE discussions
       SET message_count   = message_count + 1,
           last_activity_ts = NOW(),
           participant_count = (
               SELECT COUNT(DISTINCT author_id)
                 FROM discussion_messages
                WHERE discussion_id = $1 AND author_id IS NOT NULL
           ) + 1   -- +1 for the discussion's original author
     WHERE id = $1
)
SELECT id, discussion_id, author_id, body, created_at FROM msg
`

func (r *Repository) InsertMessage(ctx context.Context, m *domdiscussion.Message) error {
	var (
		retID, retDiscID, retAuthorID uuid.UUID
		retBody                       string
		retCreatedAt                  time.Time
	)
	err := r.pool.QueryRow(ctx, insertMessageSQL,
		m.DiscussionID, m.AuthorID, m.Body,
	).Scan(&retID, &retDiscID, &retAuthorID, &retBody, &retCreatedAt)
	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == pgerrcode.ForeignKeyViolation {
			return domdiscussion.ErrNotFound
		}
		return fmt.Errorf("discussionrepo insert message: %w", err)
	}
	// Stamp the persisted id + created_at back onto the caller's
	// instance so they don't read stale values from the application
	// service's return.
	m.ID = retID
	m.CreatedAt = retCreatedAt.UTC()
	return nil
}

const messageCols = `id, discussion_id, author_id, body, created_at`

// ListMessages: chronological (ASC). Keyset still on (created_at, id)
// for stability under concurrent posts; comparator flipped to `>`.
const listMessagesSQL = `
SELECT ` + messageCols + `
  FROM discussion_messages
 WHERE discussion_id = $1
   AND ($3::timestamptz IS NULL OR (created_at, id) > ($3, $4::bigint))
 ORDER BY created_at ASC, id ASC
 LIMIT $2
`

// Messages use a BIGSERIAL id (not UUID), so the cursor codec — which
// stores a UUID — doesn't fit cleanly. We use a separate inline
// "<created_at>|<bigint id>" encoder for message pages.
func (r *Repository) ListMessages(ctx context.Context, f domdiscussion.MessageListFilter) (domdiscussion.MessageListPage, error) {
	cursorTS, cursorID, err := decodeMessageCursor(f.Cursor)
	if err != nil {
		return domdiscussion.MessageListPage{}, err
	}
	var tsArg, idArg any
	if !cursorTS.IsZero() {
		tsArg = cursorTS
		idArg = cursorID
	}

	rows, err := r.pool.Query(ctx, listMessagesSQL, f.DiscussionID, f.Limit, tsArg, idArg)
	if err != nil {
		return domdiscussion.MessageListPage{}, fmt.Errorf("discussionrepo list messages: %w", err)
	}
	defer rows.Close()

	out := make([]*domdiscussion.Message, 0, f.Limit)
	var lastInternalID int64
	for rows.Next() {
		var (
			pkID      int64
			discID    uuid.UUID
			authorID  *uuid.UUID
			body      string
			createdAt time.Time
		)
		// We don't have a uuid PK on discussion_messages; the app-
		// surfaced "id" is the bigserial cast to string. Hydrate
		// Message with a synthesised UUID v5 over (discussion_id,
		// pkID) so callers always see a uuid; the internal id only
		// matters for cursor + the repo's own joins.
		if err := rows.Scan(&pkID, &discID, &authorID, &body, &createdAt); err != nil {
			return domdiscussion.MessageListPage{}, fmt.Errorf("discussionrepo scan message: %w", err)
		}
		lastInternalID = pkID
		var aID uuid.UUID
		if authorID != nil {
			aID = *authorID
		}
		out = append(out, &domdiscussion.Message{
			ID:           uuid.NewSHA1(discID, []byte(fmt.Sprintf("%d", pkID))),
			DiscussionID: discID,
			AuthorID:     aID,
			Body:         body,
			CreatedAt:    createdAt.UTC(),
		})
	}
	if err := rows.Err(); err != nil {
		return domdiscussion.MessageListPage{}, fmt.Errorf("discussionrepo list messages rows: %w", err)
	}

	page := domdiscussion.MessageListPage{Messages: out}
	if len(out) == f.Limit {
		page.NextCursor = encodeMessageCursor(out[len(out)-1].CreatedAt, lastInternalID)
	}
	return page, nil
}

// ---- helpers ----

type rowScanner interface {
	Scan(dest ...any) error
}

func scanDiscussion(r rowScanner) (*domdiscussion.Discussion, error) {
	var (
		id, communityID, authorID uuid.UUID
		title, body               string
		matchID                   *uuid.UUID
		messageCount              int64
		participantCount          int64
		lastActivityTs            time.Time
		createdAt                 time.Time
	)
	err := r.Scan(&id, &communityID, &authorID, &title, &body, &matchID,
		&messageCount, &participantCount, &lastActivityTs, &createdAt)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, domdiscussion.ErrNotFound
		}
		return nil, fmt.Errorf("discussionrepo scan: %w", err)
	}
	return domdiscussion.ReconstituteDiscussion(
		id, communityID, authorID, title, body, matchID,
		messageCount, participantCount,
		lastActivityTs.UTC(), createdAt.UTC(),
	), nil
}
