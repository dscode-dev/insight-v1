// Package moderation is the Gateway's UGC-safety domain (Store-A): user
// blocks, content reports, admin moderation actions, platform-hidden content
// and user bans. Standard-library-only domain; ports are interfaces here,
// implemented by internal/infrastructure/postgres.
package moderation

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
)

// ---- target / reason / status / action vocabularies ----

// TargetType — what a report or action points at.
type TargetType string

const (
	TargetPost    TargetType = "post"
	TargetComment TargetType = "comment"
	TargetUser    TargetType = "user"
)

func (t TargetType) Valid() bool {
	switch t {
	case TargetPost, TargetComment, TargetUser:
		return true
	}
	return false
}

// Reason — why content was reported. Mirrors the App Store / Play categories.
type Reason string

const (
	ReasonInappropriate Reason = "inappropriate" // pornography / inappropriate
	ReasonHate          Reason = "hate"          // hate speech / harassment
	ReasonSpam          Reason = "spam"          // spam / scam
	ReasonViolence      Reason = "violence"      // violence / threat
	ReasonOther         Reason = "other"
)

func (r Reason) Valid() bool {
	switch r {
	case ReasonInappropriate, ReasonHate, ReasonSpam, ReasonViolence, ReasonOther:
		return true
	}
	return false
}

// Status — report lifecycle.
type Status string

const (
	StatusOpen      Status = "open"
	StatusReviewing Status = "reviewing"
	StatusResolved  Status = "resolved"
	StatusDismissed Status = "dismissed"
)

// Action — an admin moderation action (audited).
type Action string

const (
	ActionDismiss     Action = "dismiss"
	ActionRemove      Action = "remove_content"
	ActionRestore     Action = "restore_content"
	ActionSuspendUser Action = "suspend_user"
	ActionBanUser     Action = "ban_user"
	ActionRestoreUser Action = "restore_user"
)

func (a Action) Valid() bool {
	switch a {
	case ActionDismiss, ActionRemove, ActionRestore, ActionSuspendUser, ActionBanUser, ActionRestoreUser:
		return true
	}
	return false
}

// UserState — moderation state of a user account.
type UserState string

const (
	StateActive    UserState = "active"
	StateSuspended UserState = "suspended"
	StateBanned    UserState = "banned"
)

// ---- entities ----

type Report struct {
	ID          uuid.UUID
	ReporterID  uuid.UUID
	TargetType  TargetType
	TargetID    string
	Reason      Reason
	Description string
	Status      Status
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

type ActionRecord struct {
	ID          uuid.UUID
	ReportID    *uuid.UUID
	ModeratorID string
	Action      Action
	TargetType  TargetType
	TargetID    string
	Note        string
	CreatedAt   time.Time
}

// ReasonCount / ReporterCount / TargetCount feed the Console dashboards.
type ReasonCount struct {
	Reason Reason
	Count  int64
}
type Aggregate struct {
	Key   string
	Count int64
}

// ReportFilter narrows ListReports for the Console queue.
type ReportFilter struct {
	Status     *Status
	Reason     *Reason
	TargetType *TargetType
	TargetID   *string
	ReporterID *string
	Limit      int
	Offset     int
}

// ---- errors ----

var (
	ErrSelfBlock      = errors.New("cannot_block_self")
	ErrInvalidTarget  = errors.New("invalid_target_type")
	ErrInvalidReason  = errors.New("invalid_reason")
	ErrInvalidAction  = errors.New("invalid_action")
	ErrReportNotFound = errors.New("report_not_found")
	ErrUserBanned     = errors.New("user_banned")
	ErrUserSuspended  = errors.New("user_suspended")
)

// ---- ports ----

// Repo persists + queries all moderation state. Implemented in
// infrastructure/postgres.
type Repo interface {
	// Blocks
	Block(ctx context.Context, blocker, blocked uuid.UUID) error
	Unblock(ctx context.Context, blocker, blocked uuid.UUID) error
	BlockedBy(ctx context.Context, blocker uuid.UUID) ([]uuid.UUID, error)

	// Reports
	CreateReport(ctx context.Context, r *Report) error
	ListReports(ctx context.Context, f ReportFilter) ([]Report, int64, error)
	GetReport(ctx context.Context, id uuid.UUID) (*Report, error)
	SetReportStatus(ctx context.Context, id uuid.UUID, s Status) error
	CountByStatus(ctx context.Context) (map[Status]int64, error)
	CountByReason(ctx context.Context) ([]ReasonCount, error)
	TopReportedTargets(ctx context.Context, t TargetType, limit int) ([]Aggregate, error)
	TopReporters(ctx context.Context, limit int) ([]Aggregate, error)

	// Admin actions (audit)
	RecordAction(ctx context.Context, a *ActionRecord) error
	ListActions(ctx context.Context, limit int) ([]ActionRecord, error)

	// Hidden content
	HideContent(ctx context.Context, t TargetType, id string) error
	RestoreContent(ctx context.Context, t TargetType, id string) error
	HiddenContent(ctx context.Context) (map[string]struct{}, error) // key: "<type>:<id>"

	// User state
	SetUserState(ctx context.Context, userID uuid.UUID, state UserState, until *time.Time) error
	UserStateOf(ctx context.Context, userID uuid.UUID) (UserState, *time.Time, error)
	NonActiveUsers(ctx context.Context) ([]uuid.UUID, error) // suspended (live) + banned
}
