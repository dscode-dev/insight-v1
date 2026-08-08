// Package post holds the Post + Comment aggregates and the Like value
// — Sprint 3 (Social Foundation). Text-only V1: no media, no
// hashtags, no reaction catalog (like is the only reaction).
//
// Invariants enforced here:
//   - content: 1..4000 chars after trim (posts), 1..2000 (comments)
//   - author_type: user | agent | admin
//   - visibility: public | competition | private
//   - comment depth: post → comment (1) → reply (2); replies to
//     replies are rejected (no nested trees)
package post

import (
	"context"
	"errors"
	"strings"
	"time"

	"github.com/google/uuid"
)

var (
	ErrNotFound         = errors.New("post_not_found")
	ErrCommentNotFound  = errors.New("comment_not_found")
	ErrEmptyContent     = errors.New("empty_content")
	ErrContentTooLong   = errors.New("content_too_long")
	ErrInvalidAuthor    = errors.New("invalid_author_type")
	ErrInvalidVisible   = errors.New("invalid_visibility")
	ErrNotAuthor        = errors.New("not_the_author")
	ErrMaxDepthExceeded = errors.New("max_comment_depth_exceeded")
	ErrAgentInactive    = errors.New("agent_inactive") // CONSOLE-SOCIAL-B: deactivated agent may not publish
	// A competition-scoped post that names no competition cannot appear in any
	// rail — it would be published and then invisible in every filtered view.
	ErrCompetitionRequired = errors.New("competition_required")
	// The id does not match a registered competition. Competitions exist only
	// once registered in the console; an unknown id is a rejection, not a value
	// to store and reconcile later.
	ErrCompetitionUnknown = errors.New("competition_unknown")
)

const (
	MaxPostContent    = 4000
	MaxCommentContent = 2000
	MaxCommentDepth   = 2
)

type AuthorType string

const (
	AuthorUser  AuthorType = "user"
	AuthorAgent AuthorType = "agent"
	AuthorAdmin AuthorType = "admin"
)

func (a AuthorType) Valid() bool {
	return a == AuthorUser || a == AuthorAgent || a == AuthorAdmin
}

type Visibility string

const (
	VisibilityPublic      Visibility = "public"
	VisibilityCompetition Visibility = "competition"
	VisibilityPrivate     Visibility = "private"
)

func (v Visibility) Valid() bool {
	return v == VisibilityPublic || v == VisibilityCompetition || v == VisibilityPrivate
}

type Post struct {
	ID           uuid.UUID
	AuthorID     uuid.UUID
	AuthorType   AuthorType
	Content      string
	Metadata     map[string]string
	Visibility   Visibility
	CreatedAt    time.Time
	LikeCount    int64
	CommentCount int64

	// The competition this post belongs to, when it belongs to one.
	//
	// The public feed is partitioned by competition — the app's rail under the
	// header picks one and the feed narrows to it. nil means the post is
	// platform-wide and shows whatever the viewer has selected.
	//
	// A UUID rather than the slug: the slug is editable from the console, and
	// a post keyed on it would detach from its competition the moment an
	// operator renamed one.
	CompetitionID *uuid.UUID

	// Filled on read for rendering the competition chip without a second call.
	// Never accepted on write — Social derives them from CompetitionID.
	CompetitionSlug string
	CompetitionName string
}

// NewPost validates and constructs a fresh Post.
func NewPost(
	authorID uuid.UUID,
	authorType AuthorType,
	content string,
	metadata map[string]string,
	visibility Visibility,
	competitionID *uuid.UUID,
) (*Post, error) {
	content = strings.TrimSpace(content)
	if content == "" {
		return nil, ErrEmptyContent
	}
	if len(content) > MaxPostContent {
		return nil, ErrContentTooLong
	}
	if !authorType.Valid() {
		return nil, ErrInvalidAuthor
	}
	if visibility == "" {
		visibility = VisibilityPublic
	}
	if !visibility.Valid() {
		return nil, ErrInvalidVisible
	}
	if metadata == nil {
		metadata = map[string]string{}
	}
	// Refused here as well as in the database. The CHECK constraint
	// (posts_competition_scope_check) is what makes the rule true, but a
	// constraint violation surfaces as a driver error the caller has to parse;
	// this returns the reason as a domain error the API can map to a 400.
	if visibility == VisibilityCompetition && competitionID == nil {
		return nil, ErrCompetitionRequired
	}
	if competitionID != nil && *competitionID == uuid.Nil {
		// The zero UUID passes a nil check and fails the foreign key, which
		// would read as "competition does not exist" rather than "you sent an
		// empty id".
		return nil, ErrCompetitionRequired
	}
	return &Post{
		ID:            uuid.New(),
		AuthorID:      authorID,
		AuthorType:    authorType,
		Content:       content,
		Metadata:      metadata,
		Visibility:    visibility,
		CompetitionID: competitionID,
		CreatedAt:     time.Now().UTC(),
	}, nil
}

type Comment struct {
	ID         uuid.UUID
	PostID     uuid.UUID
	ParentID   *uuid.UUID // nil for top-level comments
	AuthorID   uuid.UUID
	AuthorType AuthorType
	Content    string
	Depth      int // 1 = comment, 2 = reply
	CreatedAt  time.Time
}

// NewComment validates and constructs a comment or reply. parentDepth
// is 0 for top-level comments, or the parent comment's depth.
func NewComment(
	postID uuid.UUID,
	parentID *uuid.UUID,
	parentDepth int,
	authorID uuid.UUID,
	authorType AuthorType,
	content string,
) (*Comment, error) {
	content = strings.TrimSpace(content)
	if content == "" {
		return nil, ErrEmptyContent
	}
	if len(content) > MaxCommentContent {
		return nil, ErrContentTooLong
	}
	if !authorType.Valid() {
		return nil, ErrInvalidAuthor
	}
	depth := parentDepth + 1
	if depth > MaxCommentDepth {
		return nil, ErrMaxDepthExceeded
	}
	return &Comment{
		ID:         uuid.New(),
		PostID:     postID,
		ParentID:   parentID,
		AuthorID:   authorID,
		AuthorType: authorType,
		Content:    content,
		Depth:      depth,
		CreatedAt:  time.Now().UTC(),
	}, nil
}

type CommentPage struct {
	Comments   []*Comment
	NextCursor string
}

// Repository is the post-aggregate persistence port (posts, comments,
// likes — one aggregate, one port).
type Repository interface {
	InsertPost(ctx context.Context, p *Post) error
	GetPost(ctx context.Context, id uuid.UUID) (*Post, error)
	// SoftDeletePost marks the post deleted (audit-friendly). The
	// repo verifies authorship: only the author may delete.
	SoftDeletePost(ctx context.Context, id, requesterID uuid.UUID) error

	InsertComment(ctx context.Context, c *Comment) error
	GetComment(ctx context.Context, id uuid.UUID) (*Comment, error)
	ListComments(ctx context.Context, postID uuid.UUID, limit int, cursor string) (CommentPage, error)

	// Like / Unlike are idempotent at the DB level (re-like no-ops).
	Like(ctx context.Context, postID, userID uuid.UUID) error
	Unlike(ctx context.Context, postID, userID uuid.UUID) error
}
