// Package communityrepo is the pgx-backed implementation of
// domain/community.Repository.
//
// Pagination is keyset on (created_at DESC, id DESC). The cursor
// encodes the last row of the previous page; queries apply a
// `(created_at, id) < ($cursor_ts, $cursor_id)` predicate so pages
// don't shift under concurrent inserts. This is strictly more
// correct than OFFSET pagination and the index supports it directly
// (created_at, id).
package communityrepo

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgerrcode"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	domcommunity "github.com/konoha-labs/insight-social/internal/domain/community"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres"
	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/pagination"
)

type Repository struct {
	pool postgres.Pool
}

func New(pool postgres.Pool) *Repository {
	return &Repository{pool: pool}
}

// ---- writes ----

const insertSQL = `
INSERT INTO communities (
    id, slug, name, topic, kind, competition_id,
    accent_color, member_count, active_now, created_at, owner_user_id
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
`

// Insert persists an OWNERLESS community (competition/auto-created path). The
// owner_user_id is written from the aggregate (nil => OWNER_UNASSIGNED).
func (r *Repository) Insert(ctx context.Context, c *domcommunity.Community) error {
	_, err := r.pool.Exec(ctx, insertSQL,
		c.ID(), c.Slug(), c.Name(), c.Topic(), c.Kind().String(), c.CompetitionID(),
		c.AccentColor(), c.MemberCount(), c.ActiveNow(), c.CreatedAt(), c.OwnerUserID(),
	)
	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == pgerrcode.UniqueViolation {
			return domcommunity.ErrSlugTaken
		}
		return fmt.Errorf("communityrepo insert: %w", err)
	}
	return nil
}

// InsertOwned creates the community, its OWNER membership, and sets
// owner_user_id — atomically. The three writes are the ONLY place these are
// created together, guaranteeing owner_user_id references exactly one OWNER
// membership (invariant 1). member_count starts at 1 (the owner is a member).
func (r *Repository) InsertOwned(ctx context.Context, c *domcommunity.Community) (*domcommunity.Membership, error) {
	owner := c.OwnerUserID()
	if owner == nil {
		return nil, domcommunity.ErrOwnerRequired
	}

	tx, err := r.pool.Begin(ctx)
	if err != nil {
		return nil, fmt.Errorf("communityrepo insert owned begin: %w", err)
	}
	defer tx.Rollback(ctx) //nolint:errcheck // no-op after commit

	// member_count = 1: the owner is the first member.
	if _, err := tx.Exec(ctx, insertSQL,
		c.ID(), c.Slug(), c.Name(), c.Topic(), c.Kind().String(), c.CompetitionID(),
		c.AccentColor(), int64(1), c.ActiveNow(), c.CreatedAt(), owner,
	); err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == pgerrcode.UniqueViolation {
			return nil, domcommunity.ErrSlugTaken
		}
		return nil, fmt.Errorf("communityrepo insert owned community: %w", err)
	}

	m := &domcommunity.Membership{}
	err = tx.QueryRow(ctx, insertOwnerMemberSQL, c.ID(), owner).Scan(
		&m.CommunityID, &m.UserID, &m.JoinedAt, &m.IsModerator, roleScan(&m.Role),
	)
	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == pgerrcode.ForeignKeyViolation {
			return nil, domcommunity.ErrNotFound // owner user does not exist
		}
		return nil, fmt.Errorf("communityrepo insert owner membership: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, fmt.Errorf("communityrepo insert owned commit: %w", err)
	}
	m.JoinedAt = m.JoinedAt.UTC()
	return m, nil
}

// OWNER membership: role='owner', is_moderator=TRUE (derived — owner is
// privileged). Written inside InsertOwned's transaction.
const insertOwnerMemberSQL = `
INSERT INTO community_members (community_id, user_id, is_moderator, role, joined_at)
VALUES ($1, $2, TRUE, 'owner', NOW())
RETURNING community_id, user_id, joined_at, is_moderator, role
`

// AddMember inserts a MEMBER row + increments member_count atomically. A
// re-join hits the UNIQUE(user_id, community_id) constraint → ErrAlreadyMember,
// so an existing privileged role is never overwritten (invariant 7).
const addMemberSQL = `
WITH ins AS (
    INSERT INTO community_members (community_id, user_id, is_moderator, role, joined_at)
    VALUES ($1, $2, FALSE, 'member', NOW())
    RETURNING community_id, user_id, joined_at, is_moderator, role
), bump AS (
    UPDATE communities
       SET member_count = member_count + 1
     WHERE id = $1
)
SELECT community_id, user_id, joined_at, is_moderator, role FROM ins
`

func (r *Repository) AddMember(ctx context.Context, communityID, userID uuid.UUID) (*domcommunity.Membership, error) {
	m := &domcommunity.Membership{}
	err := r.pool.QueryRow(ctx, addMemberSQL, communityID, userID).Scan(
		&m.CommunityID, &m.UserID, &m.JoinedAt, &m.IsModerator, roleScan(&m.Role),
	)
	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) {
			switch pgErr.Code {
			case pgerrcode.UniqueViolation:
				return nil, domcommunity.ErrAlreadyMember
			case pgerrcode.ForeignKeyViolation:
				return nil, domcommunity.ErrNotFound
			}
		}
		return nil, fmt.Errorf("communityrepo add member: %w", err)
	}
	m.JoinedAt = m.JoinedAt.UTC()
	return m, nil
}

// RemoveMember deletes a NON-owner join row + decrements member_count. The
// owner-leave invariant (2/3) is enforced in the same statement: the DELETE
// only matches rows whose role <> 'owner'. We then distinguish three cases:
//   - a non-owner row was deleted            → success
//   - the row exists but is the OWNER        → ErrOwnerCannotLeave
//   - no row at all                          → ErrNotMember (idempotent leave)
const removeMemberSQL = `
WITH target AS (
    SELECT role FROM community_members
     WHERE community_id = $1 AND user_id = $2
), del AS (
    DELETE FROM community_members
     WHERE community_id = $1 AND user_id = $2 AND role <> 'owner'
    RETURNING 1
), bump AS (
    UPDATE communities
       SET member_count = GREATEST(member_count - 1, 0)
     WHERE id = $1 AND EXISTS (SELECT 1 FROM del)
)
SELECT
    (SELECT count(*) FROM del)                       AS deleted,
    (SELECT role FROM target)                        AS target_role
`

func (r *Repository) RemoveMember(ctx context.Context, communityID, userID uuid.UUID) error {
	var (
		deleted    int
		targetRole *string
	)
	if err := r.pool.QueryRow(ctx, removeMemberSQL, communityID, userID).Scan(&deleted, &targetRole); err != nil {
		return fmt.Errorf("communityrepo remove member: %w", err)
	}
	if deleted > 0 {
		return nil
	}
	if targetRole != nil && domcommunity.ParseRole(*targetRole) == domcommunity.RoleOwner {
		return domcommunity.ErrOwnerCannotLeave
	}
	return domcommunity.ErrNotMember
}

// ---- reads ----

const baseSelectCols = `
id, slug, name, topic, kind, competition_id,
accent_color, member_count, active_now, created_at, owner_user_id
`

func (r *Repository) GetByID(ctx context.Context, id uuid.UUID) (*domcommunity.Community, error) {
	return scanCommunity(r.pool.QueryRow(ctx, `SELECT `+baseSelectCols+` FROM communities WHERE id = $1`, id))
}

func (r *Repository) GetBySlug(ctx context.Context, slug string) (*domcommunity.Community, error) {
	return scanCommunity(r.pool.QueryRow(ctx, `SELECT `+baseSelectCols+` FROM communities WHERE slug = $1`, slug))
}

// List supports three orderings (W2.2.1):
//
//   - SortNewest  — keyset (created_at DESC, id DESC). Full cursor support.
//   - SortHot     — (active_now DESC, member_count DESC, id DESC). Single
//     page only; cursor is rejected with InvalidCursor when
//     non-empty. Documented in the proto.
//   - SortPopular — (member_count DESC, id DESC). Same single-page rule
//     as Hot.
//
// HOT/POPULAR omit pagination intentionally for W2.2.1 — encoding their
// keysets requires either a polymorphic cursor or a separate codec
// per sort, neither of which carries its weight while the only caller
// is the gateway Hub (capped at 20 rows). Promote when a second caller
// needs multi-page hot/popular.
const listNewestSQL = `
SELECT ` + baseSelectCols + `
  FROM communities
 WHERE ($1::text IS NULL OR kind = $1)
   AND ($3::timestamptz IS NULL OR (created_at, id) < ($3, $4))
 ORDER BY created_at DESC, id DESC
 LIMIT $2
`

const listHotSQL = `
SELECT ` + baseSelectCols + `
  FROM communities
 WHERE ($1::text IS NULL OR kind = $1)
 ORDER BY active_now DESC, member_count DESC, id DESC
 LIMIT $2
`

const listPopularSQL = `
SELECT ` + baseSelectCols + `
  FROM communities
 WHERE ($1::text IS NULL OR kind = $1)
 ORDER BY member_count DESC, id DESC
 LIMIT $2
`

func (r *Repository) List(ctx context.Context, f domcommunity.ListFilter) (domcommunity.ListPage, error) {
	var kindArg any
	if f.Kind != nil && *f.Kind != domcommunity.KindUnspecified {
		kindArg = f.Kind.String()
	}

	sort := f.Sort.Resolve()

	// Reject cursors for the sorts that don't support them — better
	// than silently dropping the value, which would mask an over-
	// reaching caller (e.g. paginating "hot" then wondering why
	// page 2 == page 1).
	if sort != domcommunity.SortNewest && f.Cursor != "" {
		return domcommunity.ListPage{}, fmt.Errorf("%w: cursor not supported for sort=%s",
			pagination.ErrInvalidCursor, sort.String())
	}

	switch sort {
	case domcommunity.SortHot:
		return r.runListSingle(ctx, listHotSQL, kindArg, f.Limit)
	case domcommunity.SortPopular:
		return r.runListSingle(ctx, listPopularSQL, kindArg, f.Limit)
	default: // SortNewest
		return r.runListNewest(ctx, kindArg, f)
	}
}

// runListNewest is the paginated path. The (created_at, id) keyset
// gives total order even when timestamps collide.
func (r *Repository) runListNewest(ctx context.Context, kindArg any, f domcommunity.ListFilter) (domcommunity.ListPage, error) {
	cursorTS, cursorID, err := pagination.Decode(f.Cursor)
	if err != nil {
		return domcommunity.ListPage{}, err
	}
	var (
		tsArg any
		idArg any
	)
	if !cursorTS.IsZero() {
		tsArg = cursorTS
		idArg = cursorID
	}

	rows, err := r.pool.Query(ctx, listNewestSQL, kindArg, f.Limit, tsArg, idArg)
	if err != nil {
		return domcommunity.ListPage{}, fmt.Errorf("communityrepo list newest: %w", err)
	}
	defer rows.Close()

	out, err := drainCommunities(rows, f.Limit)
	if err != nil {
		return domcommunity.ListPage{}, err
	}

	page := domcommunity.ListPage{Communities: out}
	if len(out) == f.Limit {
		last := out[len(out)-1]
		page.NextCursor = pagination.Encode(last.CreatedAt(), last.ID())
	}
	return page, nil
}

// runListSingle is the non-paginated path used by SortHot / SortPopular.
// Always returns NextCursor = "" so the caller knows not to ask for
// page 2.
func (r *Repository) runListSingle(ctx context.Context, sql string, kindArg any, limit int) (domcommunity.ListPage, error) {
	rows, err := r.pool.Query(ctx, sql, kindArg, limit)
	if err != nil {
		return domcommunity.ListPage{}, fmt.Errorf("communityrepo list single: %w", err)
	}
	defer rows.Close()

	out, err := drainCommunities(rows, limit)
	if err != nil {
		return domcommunity.ListPage{}, err
	}
	return domcommunity.ListPage{Communities: out}, nil
}

// drainCommunities iterates pgx.Rows into a slice of communities.
// Shared between every List path to keep the row-shape logic in one
// place (any future column addition is a single edit).
func drainCommunities(rows pgx.Rows, cap int) ([]*domcommunity.Community, error) {
	out := make([]*domcommunity.Community, 0, cap)
	for rows.Next() {
		c, err := scanCommunity(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("communityrepo drain: %w", err)
	}
	return out, nil
}

// ListForUser — join communities with community_members, paged by
// recency of join. The cursor encodes (joined_at, community_id) since
// the same community can be joined at distinct times by different
// users (we still need stable ordering for THIS user's set).
const listForUserSQL = `
SELECT ` + baseSelectColsWithJoinTs + `
  FROM communities c
  JOIN community_members cm ON cm.community_id = c.id
 WHERE cm.user_id = $1
   AND ($3::timestamptz IS NULL OR (cm.joined_at, c.id) < ($3, $4))
 ORDER BY cm.joined_at DESC, c.id DESC
 LIMIT $2
`

// baseSelectColsWithJoinTs is baseSelectCols qualified with the `c.`
// alias + cm.joined_at appended for cursor encoding.
const baseSelectColsWithJoinTs = `
c.id, c.slug, c.name, c.topic, c.kind, c.competition_id,
c.accent_color, c.member_count, c.active_now, c.created_at, c.owner_user_id,
cm.joined_at
`

func (r *Repository) ListForUser(ctx context.Context, f domcommunity.ListForUserFilter) (domcommunity.ListPage, error) {
	cursorTS, cursorUUID, err := pagination.Decode(f.Cursor)
	if err != nil {
		return domcommunity.ListPage{}, err
	}
	var (
		tsArg any
		idArg any
	)
	if !cursorTS.IsZero() {
		tsArg = cursorTS
		idArg = cursorUUID
	}

	rows, err := r.pool.Query(ctx, listForUserSQL, f.UserID, f.Limit, tsArg, idArg)
	if err != nil {
		return domcommunity.ListPage{}, fmt.Errorf("communityrepo list for user: %w", err)
	}
	defer rows.Close()

	out := make([]*domcommunity.Community, 0, f.Limit)
	var lastJoinedAt time.Time
	for rows.Next() {
		c, joinedAt, err := scanCommunityWithJoinTs(rows)
		if err != nil {
			return domcommunity.ListPage{}, err
		}
		out = append(out, c)
		lastJoinedAt = joinedAt
	}
	if err := rows.Err(); err != nil {
		return domcommunity.ListPage{}, fmt.Errorf("communityrepo list for user rows: %w", err)
	}

	page := domcommunity.ListPage{Communities: out}
	if len(out) == f.Limit {
		// Cursor: pagination.Encode is keyed by (timestamp, uuid).
		// Here the timestamp is cm.joined_at and the uuid is c.id —
		// matches the SQL keyset predicate.
		page.NextCursor = pagination.Encode(lastJoinedAt, out[len(out)-1].ID())
	}
	return page, nil
}

// scanCommunityWithJoinTs is the ListForUser variant that pulls
// cm.joined_at alongside the community columns. Kept distinct from
// scanCommunity so a regression on baseSelectCols can't silently
// shift the joined_at column index.
func scanCommunityWithJoinTs(r rowScanner) (*domcommunity.Community, time.Time, error) {
	var (
		id            uuid.UUID
		slug          string
		name          string
		topic         string
		kindStr       string
		competitionID *uuid.UUID
		accentColor   string
		memberCount   int64
		activeNow     int64
		createdAt     time.Time
		ownerUserID   *uuid.UUID
		joinedAt      time.Time
	)
	err := r.Scan(&id, &slug, &name, &topic, &kindStr, &competitionID,
		&accentColor, &memberCount, &activeNow, &createdAt, &ownerUserID, &joinedAt)
	if err != nil {
		// pgx.ErrNoRows can't surface inside Next()/Scan() of a
		// successful Query — only on QueryRow. Treat any error here
		// as opaque.
		return nil, time.Time{}, fmt.Errorf("communityrepo scan join: %w", err)
	}
	c := domcommunity.Reconstitute(
		id, slug, name, topic, domcommunity.ParseKind(kindStr),
		competitionID, accentColor, memberCount, activeNow,
		createdAt.UTC(), ownerUserID,
	)
	return c, joinedAt.UTC(), nil
}

// ---- members listing ----

// listMembersSQL selects enriched members (JOIN users — no N+1) for one
// community, ordered by role priority (owner→admin→moderator→member), then
// joined_at ASC, then user_id ASC — a stable total order matching
// domcommunity.MembersCursor. The keyset predicate uses the same triple.
//
// Args:
//
//	$1 community_id
//	$2 limit (+1 fetched by caller for has-more)
//	$3 role filter (text) or NULL for all roles
//	$4 cursor role priority (int) or NULL for first page
//	$5 cursor joined_at        (used only when $4 is not NULL)
//	$6 cursor user_id          (used only when $4 is not NULL)
//
// role_priority mirrors domcommunity.Role.Priority().
const listMembersSQL = `
SELECT
    cm.user_id, u.username, u.display_name, u.initials, u.accent_color,
    COALESCE(u.avatar_url, '') AS avatar_url, u.reputation, cm.role, cm.joined_at,
    CASE cm.role
        WHEN 'owner' THEN 0 WHEN 'admin' THEN 1
        WHEN 'moderator' THEN 2 ELSE 3
    END AS role_priority
  FROM community_members cm
  JOIN users u ON u.id = cm.user_id
 WHERE cm.community_id = $1
   AND ($3::text IS NULL OR cm.role = $3)
   AND (
        $4::int IS NULL
        OR (
            CASE cm.role
                WHEN 'owner' THEN 0 WHEN 'admin' THEN 1
                WHEN 'moderator' THEN 2 ELSE 3
            END, cm.joined_at, cm.user_id
        ) > ($4, $5, $6)
   )
 ORDER BY role_priority ASC, cm.joined_at ASC, cm.user_id ASC
 LIMIT $2
`

func (r *Repository) ListMembers(ctx context.Context, f domcommunity.ListMembersFilter) (domcommunity.MembersPage, error) {
	limit := f.Limit
	if limit <= 0 {
		limit = 20
	}

	cur, err := domcommunity.DecodeMembersCursor(f.Cursor)
	if err != nil {
		return domcommunity.MembersPage{}, err
	}

	var roleArg any
	if f.RoleFilter != nil {
		roleArg = f.RoleFilter.String()
	}
	var pArg, jArg, uArg any
	if cur != nil {
		pArg, jArg, uArg = cur.P, cur.J, cur.U
	}

	// Fetch limit+1 to detect a next page without a second query.
	rows, err := r.pool.Query(ctx, listMembersSQL, f.CommunityID, limit+1, roleArg, pArg, jArg, uArg)
	if err != nil {
		return domcommunity.MembersPage{}, fmt.Errorf("communityrepo list members: %w", err)
	}
	defer rows.Close()

	out := make([]domcommunity.MemberProfile, 0, limit+1)
	for rows.Next() {
		var (
			m        domcommunity.MemberProfile
			roleStr  string
			priority int
		)
		if err := rows.Scan(
			&m.UserID, &m.Username, &m.DisplayName, &m.Initials, &m.AccentColor,
			&m.AvatarURL, &m.Reputation, &roleStr, &m.JoinedAt, &priority,
		); err != nil {
			return domcommunity.MembersPage{}, fmt.Errorf("communityrepo scan member: %w", err)
		}
		m.Role = domcommunity.ParseRole(roleStr)
		m.JoinedAt = m.JoinedAt.UTC()
		out = append(out, m)
	}
	if err := rows.Err(); err != nil {
		return domcommunity.MembersPage{}, fmt.Errorf("communityrepo members rows: %w", err)
	}

	page := domcommunity.MembersPage{Members: out}
	if len(out) > limit {
		last := out[limit-1]
		page.Members = out[:limit]
		page.NextCursor = domcommunity.EncodeMembersCursor(last.Role, last.JoinedAt, last.UserID)
	}
	return page, nil
}

// GetMembership resolves one user's membership (role) in a community.
const getMembershipSQL = `
SELECT community_id, user_id, joined_at, is_moderator, role
  FROM community_members
 WHERE community_id = $1 AND user_id = $2
`

func (r *Repository) GetMembership(ctx context.Context, communityID, userID uuid.UUID) (*domcommunity.Membership, error) {
	m := &domcommunity.Membership{}
	err := r.pool.QueryRow(ctx, getMembershipSQL, communityID, userID).Scan(
		&m.CommunityID, &m.UserID, &m.JoinedAt, &m.IsModerator, roleScan(&m.Role),
	)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, domcommunity.ErrNotMember
		}
		return nil, fmt.Errorf("communityrepo get membership: %w", err)
	}
	m.JoinedAt = m.JoinedAt.UTC()
	return m, nil
}

// GetStats computes the user-independent projection in TWO queries (no N+1):
//  1. role distribution + total members (GROUP BY role over community_members)
//  2. active_now (from the communities row) + discussion_count (COUNT over
//     the Discussions domain — the OFFICIAL community content, never Posts).
//
// The community's existence is confirmed by query 2 (ErrNotFound otherwise).
const statsRolesSQL = `
SELECT role, count(*) FROM community_members WHERE community_id = $1 GROUP BY role
`
const statsScalarsSQL = `
SELECT
    c.active_now,
    (SELECT count(*) FROM discussions d WHERE d.community_id = c.id) AS discussion_count
  FROM communities c
 WHERE c.id = $1
`

func (r *Repository) GetStats(ctx context.Context, communityID uuid.UUID) (domcommunity.Stats, error) {
	var (
		activeNow       int64
		discussionCount int64
	)
	if err := r.pool.QueryRow(ctx, statsScalarsSQL, communityID).Scan(&activeNow, &discussionCount); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return domcommunity.Stats{}, domcommunity.ErrNotFound
		}
		return domcommunity.Stats{}, fmt.Errorf("communityrepo stats scalars: %w", err)
	}

	rows, err := r.pool.Query(ctx, statsRolesSQL, communityID)
	if err != nil {
		return domcommunity.Stats{}, fmt.Errorf("communityrepo stats roles: %w", err)
	}
	defer rows.Close()

	var rc domcommunity.RoleCounts
	for rows.Next() {
		var (
			roleStr string
			n       int64
		)
		if err := rows.Scan(&roleStr, &n); err != nil {
			return domcommunity.Stats{}, fmt.Errorf("communityrepo stats scan: %w", err)
		}
		switch domcommunity.ParseRole(roleStr) {
		case domcommunity.RoleOwner:
			rc.Owner = n
		case domcommunity.RoleAdmin:
			rc.Admin = n
		case domcommunity.RoleModerator:
			rc.Moderator = n
		default:
			rc.Member = n
		}
	}
	if err := rows.Err(); err != nil {
		return domcommunity.Stats{}, fmt.Errorf("communityrepo stats rows: %w", err)
	}

	return domcommunity.Stats{
		CommunityID:     communityID,
		MemberCount:     rc.Total(),
		ActiveNow:       activeNow,
		DiscussionCount: discussionCount,
		RoleCounts:      rc,
	}, nil
}

// ---- helpers ----

// roleScan adapts a domcommunity.Role pointer to a database/sql Scanner so a
// text `role` column scans straight into the typed domain Role.
func roleScan(dst *domcommunity.Role) *roleScanner { return &roleScanner{dst: dst} }

type roleScanner struct{ dst *domcommunity.Role }

func (s *roleScanner) Scan(src any) error {
	switch v := src.(type) {
	case string:
		*s.dst = domcommunity.ParseRole(v)
	case []byte:
		*s.dst = domcommunity.ParseRole(string(v))
	case nil:
		*s.dst = domcommunity.RoleMember
	default:
		return fmt.Errorf("communityrepo: cannot scan %T into Role", src)
	}
	return nil
}

type rowScanner interface {
	Scan(dest ...any) error
}

func scanCommunity(r rowScanner) (*domcommunity.Community, error) {
	var (
		id            uuid.UUID
		slug          string
		name          string
		topic         string
		kindStr       string
		competitionID *uuid.UUID
		accentColor   string
		memberCount   int64
		activeNow     int64
		createdAt     time.Time
		ownerUserID   *uuid.UUID
	)
	err := r.Scan(&id, &slug, &name, &topic, &kindStr, &competitionID,
		&accentColor, &memberCount, &activeNow, &createdAt, &ownerUserID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, domcommunity.ErrNotFound
		}
		return nil, fmt.Errorf("communityrepo scan: %w", err)
	}
	return domcommunity.Reconstitute(
		id, slug, name, topic, domcommunity.ParseKind(kindStr),
		competitionID, accentColor, memberCount, activeNow,
		createdAt.UTC(), ownerUserID,
	), nil
}
