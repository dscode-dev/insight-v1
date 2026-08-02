// Package search is the FEATURE-SEARCH-V1 (Stage 1) domain: unified discovery
// over the entities Social actually owns.
//
// Categories are independent capabilities with their OWN query path, ranking
// and cursor — there is deliberately no "search everything" object and no giant
// cross-entity SQL ("All" aggregation belongs to the Gateway, Stage 2).
//
// Teams and Players are BLOCKED_BY_DOMAIN: no canonical entity exists (match
// team names are denormalized strings). This package refuses to represent them
// — a match result carries its team-name strings as MATCH CONTEXT only, never
// promoted to independent Team results. They activate only when a canonical
// source of truth (persistent identity, public contracts, ingestion, detail
// routes) exists.
package search

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"regexp"
	"strings"
	"time"

	"github.com/google/uuid"
)

// Category is one independent discovery capability.
type Category string

const (
	CategoryUsers        Category = "users"
	CategoryAgents       Category = "agents"
	CategoryCommunities  Category = "communities"
	CategoryCompetitions Category = "competitions"
	CategoryMatches      Category = "matches"
	CategoryPosts        Category = "posts"
)

// EnabledCategories are the capabilities with a REAL backing domain today.
// Order is the product presentation order. The client derives its visible tabs
// from this list (via the capabilities contract) — never from a hardcoded set.
var EnabledCategories = []Category{
	CategoryUsers, CategoryAgents, CategoryCommunities,
	CategoryCompetitions, CategoryMatches, CategoryPosts,
}

// BlockedCategories exist in the product vision but have NO canonical domain.
// They are reported so clients/docs stay honest, and MUST NOT be queried.
var BlockedCategories = map[string]string{
	"teams":   "BLOCKED_BY_DOMAIN: no canonical team entity (match team names are denormalized strings)",
	"players": "BLOCKED_BY_DOMAIN: no players domain exists",
}

// ---- query validation / normalization ----

const (
	MinQueryLen  = 2
	MaxQueryLen  = 120
	DefaultLimit = 20
	MaxLimit     = 50
	HistoryLimit = 20 // bounded per-user recent searches
)

var (
	ErrQueryTooShort  = errors.New("query_too_short")
	ErrQueryTooLong   = errors.New("query_too_long")
	ErrInvalidCursor  = errors.New("invalid_cursor")
	ErrCursorCategory = errors.New("cursor_category_mismatch")
)

var wsRe = regexp.MustCompile(`\s+`)

// NormalizeQuery canonicalizes a raw user query: trim, collapse internal
// whitespace, lowercase. Used both for matching and for history dedupe.
// Returns ErrQueryTooShort/ErrQueryTooLong on bounds (rune-counted).
func NormalizeQuery(raw string) (string, error) {
	q := strings.ToLower(wsRe.ReplaceAllString(strings.TrimSpace(raw), " "))
	n := len([]rune(q))
	if n < MinQueryLen {
		return "", ErrQueryTooShort
	}
	if n > MaxQueryLen {
		return "", ErrQueryTooLong
	}
	return q, nil
}

// EscapeLike escapes LIKE/ILIKE metacharacters in a user query so wildcards
// can never be injected ('%' '_' '\'). The repo composes patterns from the
// escaped text only.
func EscapeLike(q string) string {
	q = strings.ReplaceAll(q, `\`, `\\`)
	q = strings.ReplaceAll(q, `%`, `\%`)
	q = strings.ReplaceAll(q, `_`, `\_`)
	return q
}

// ClampLimit bounds a caller-supplied page size.
func ClampLimit(limit int) int {
	if limit <= 0 {
		return DefaultLimit
	}
	if limit > MaxLimit {
		return MaxLimit
	}
	return limit
}

// ---- cursors (per-category, typed, deterministic) ----
//
// A cursor encodes the FULL sort key of the last row (rank bucket + category
// tiebreakers + id), tagged with its category so a cursor can never be replayed
// against a different type (directive: no generic shared cursor). Numeric
// fields ride as strings (strconv 'g'/-1 for floats) so round-trips are exact.

type Cursor struct {
	Cat string `json:"c"`            // category tag — validated on decode
	B   int    `json:"b"`            // rank bucket (0 = best)
	S1  string `json:"s1"`           // tiebreaker 1 (category-specific)
	S2  string `json:"s2,omitempty"` // tiebreaker 2 (optional)
	ID  string `json:"id"`           // final unique tiebreaker
}

// Encode serializes a cursor (base64url of compact JSON).
func (c Cursor) Encode() string {
	b, _ := json.Marshal(c)
	return base64.RawURLEncoding.EncodeToString(b)
}

// DecodeCursor parses + validates a cursor for the given category. Empty input
// yields (nil, nil) — first page. A malformed cursor or a category mismatch is
// an explicit client error, never silently ignored.
func DecodeCursor(raw string, cat Category) (*Cursor, error) {
	if raw == "" {
		return nil, nil
	}
	b, err := base64.RawURLEncoding.DecodeString(raw)
	if err != nil || len(b) > 512 {
		return nil, ErrInvalidCursor
	}
	var c Cursor
	if err := json.Unmarshal(b, &c); err != nil {
		return nil, ErrInvalidCursor
	}
	if c.Cat != string(cat) {
		return nil, ErrCursorCategory
	}
	if c.ID == "" {
		return nil, ErrInvalidCursor
	}
	return &c, nil
}

// ---- results (real columns only) ----

type UserResult struct {
	ID            uuid.UUID
	Username      string
	DisplayName   string
	Initials      string
	AccentColor   string
	AvatarURL     *string // versioned (?v=) when stamped
	Reputation    int
	Tier          string
	Followers     int
	IsFollowing   bool // viewer → user
	FollowsViewer bool // user → viewer (mutual == both true)
}

type AgentResult struct {
	ID       uuid.UUID
	Slug     string
	Name     string
	Avatar   string
	Bio      string
	Active   bool
	Verified bool
}

type CommunityResult struct {
	ID          uuid.UUID
	Slug        string
	Name        string
	Topic       string
	Kind        string
	MemberCount int
	AccentColor string
}

type CompetitionResult struct {
	ID          uuid.UUID
	Slug        string
	Name        string
	ShortName   string
	Region      string
	AccentColor string
	Featured    bool
	Active      bool
}

// MatchResult: team names/colors are MATCH CONTEXT (denormalized strings on the
// match row) — deliberately not modeled as Team entities.
type MatchResult struct {
	MatchID         uuid.UUID
	CompetitionID   uuid.UUID
	CompetitionName string
	HomeTeamName    string
	HomeTeamShort   string
	HomeTeamColor   string
	AwayTeamName    string
	AwayTeamShort   string
	AwayTeamColor   string
	KickoffTs       time.Time
	State           string
	HomeScore       *int
	AwayScore       *int
}

type PostResult struct {
	ID           uuid.UUID
	AuthorID     uuid.UUID
	AuthorType   string
	AuthorName   string
	AuthorAvatar string
	Snippet      string // ts_headline output; matches wrapped in <b></b>
	CreatedAt    time.Time
	LikeCount    int
	CommentCount int
}

// Page carries one page of results + the opaque cursor for the next.
type Page[T any] struct {
	Items      []T
	NextCursor string // empty = no more pages
}

type HistoryEntry struct {
	Query     string
	CreatedAt time.Time
}

// Repository is the persistence port (implemented by postgres/searchrepo).
// One method per category — each with its own query path and ranking.
type Repository interface {
	SearchUsers(ctx context.Context, viewerID uuid.UUID, q string, limit int, cur *Cursor) (Page[UserResult], error)
	SearchAgents(ctx context.Context, q string, limit int, cur *Cursor) (Page[AgentResult], error)
	SearchCommunities(ctx context.Context, q string, limit int, cur *Cursor) (Page[CommunityResult], error)
	SearchCompetitions(ctx context.Context, q string, limit int, cur *Cursor) (Page[CompetitionResult], error)
	SearchMatches(ctx context.Context, q string, limit int, cur *Cursor) (Page[MatchResult], error)
	SearchPosts(ctx context.Context, q string, limit int, cur *Cursor) (Page[PostResult], error)

	RecordHistory(ctx context.Context, userID uuid.UUID, normalizedQuery string) error
	History(ctx context.Context, userID uuid.UUID, limit int) ([]HistoryEntry, error)
	ClearHistory(ctx context.Context, userID uuid.UUID) error
}
