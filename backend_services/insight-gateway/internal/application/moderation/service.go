// Package moderation is the Gateway application service for UGC safety
// (Store-A): user blocks, reports, admin actions, and the per-request
// content-filter "view" the social BFF applies to proxied Social responses.
package moderation

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"

	dommod "github.com/konoha-labs/insight-gateway/internal/domain/moderation"
)

type Service struct {
	repo    dommod.Repo
	metrics Metrics
	now     func() time.Time
}

type Deps struct {
	Repo    dommod.Repo
	Metrics Metrics // optional; nil disables instrumentation
}

func NewService(d Deps) *Service {
	return &Service{repo: d.Repo, metrics: d.Metrics, now: time.Now}
}

// ---- blocks (user-facing) ----

func (s *Service) Block(ctx context.Context, blocker uuid.UUID, blockedID string) error {
	blocked, err := uuid.Parse(blockedID)
	if err != nil {
		return dommod.ErrInvalidTarget
	}
	if blocked == blocker {
		return dommod.ErrSelfBlock
	}
	if err := s.repo.Block(ctx, blocker, blocked); err != nil {
		return err
	}
	s.mInc("block")
	return nil
}

func (s *Service) Unblock(ctx context.Context, blocker uuid.UUID, blockedID string) error {
	blocked, err := uuid.Parse(blockedID)
	if err != nil {
		return dommod.ErrInvalidTarget
	}
	if err := s.repo.Unblock(ctx, blocker, blocked); err != nil {
		return err
	}
	s.mInc("unblock")
	return nil
}

// ---- reports (user-facing) ----

type ReportInput struct {
	ReporterID  uuid.UUID
	TargetType  string
	TargetID    string
	Reason      string
	Description string
}

func (s *Service) Report(ctx context.Context, in ReportInput) (*dommod.Report, error) {
	tt := dommod.TargetType(in.TargetType)
	if !tt.Valid() {
		return nil, dommod.ErrInvalidTarget
	}
	reason := dommod.Reason(in.Reason)
	if !reason.Valid() {
		return nil, dommod.ErrInvalidReason
	}
	if strings.TrimSpace(in.TargetID) == "" {
		return nil, dommod.ErrInvalidTarget
	}
	now := s.now()
	rep := &dommod.Report{
		ID:          uuid.New(),
		ReporterID:  in.ReporterID,
		TargetType:  tt,
		TargetID:    strings.TrimSpace(in.TargetID),
		Reason:      reason,
		Description: strings.TrimSpace(in.Description),
		Status:      dommod.StatusOpen,
		CreatedAt:   now,
		UpdatedAt:   now,
	}
	if err := s.repo.CreateReport(ctx, rep); err != nil {
		return nil, err
	}
	s.mReport(string(reason))
	return rep, nil
}

// ---- write-gate (ban/suspension enforcement for posting/commenting/reporting) ----

// EnsureCanAct returns ErrUserBanned / ErrUserSuspended when the user may not
// create content. Active users (the common case) pass with one indexed lookup.
func (s *Service) EnsureCanAct(ctx context.Context, userID uuid.UUID) error {
	state, until, err := s.repo.UserStateOf(ctx, userID)
	if err != nil {
		return err
	}
	switch state {
	case dommod.StateBanned:
		return dommod.ErrUserBanned
	case dommod.StateSuspended:
		if until == nil || until.After(s.now()) {
			return dommod.ErrUserSuspended
		}
	}
	return nil
}

// ---- per-request filter view (social BFF) ----

// View is the moderation lens for one viewer: which authors + content the
// Gateway must drop from proxied Social responses.
type View struct {
	hiddenAuthors  map[string]struct{}
	hiddenPosts    map[string]struct{}
	hiddenComments map[string]struct{}
}

func (v *View) AuthorHidden(id string) bool {
	if v == nil {
		return false
	}
	_, ok := v.hiddenAuthors[id]
	return ok
}

func (v *View) PostHidden(id string) bool {
	if v == nil {
		return false
	}
	_, ok := v.hiddenPosts[id]
	return ok
}

func (v *View) CommentHidden(id string) bool {
	if v == nil {
		return false
	}
	_, ok := v.hiddenComments[id]
	return ok
}

// ViewFor assembles the viewer's filter: authors they blocked + globally
// non-active (banned/suspended) users + admin-hidden posts/comments.
func (s *Service) ViewFor(ctx context.Context, viewerID string) (*View, error) {
	v := &View{
		hiddenAuthors:  map[string]struct{}{},
		hiddenPosts:    map[string]struct{}{},
		hiddenComments: map[string]struct{}{},
	}
	if vid, err := uuid.Parse(viewerID); err == nil {
		blocked, err := s.repo.BlockedBy(ctx, vid)
		if err != nil {
			return nil, err
		}
		for _, id := range blocked {
			v.hiddenAuthors[id.String()] = struct{}{}
		}
	}
	nonActive, err := s.repo.NonActiveUsers(ctx)
	if err != nil {
		return nil, err
	}
	for _, id := range nonActive {
		v.hiddenAuthors[id.String()] = struct{}{}
	}
	hidden, err := s.repo.HiddenContent(ctx)
	if err != nil {
		return nil, err
	}
	for key := range hidden {
		if t, id, ok := strings.Cut(key, ":"); ok {
			switch dommod.TargetType(t) {
			case dommod.TargetPost:
				v.hiddenPosts[id] = struct{}{}
			case dommod.TargetComment:
				v.hiddenComments[id] = struct{}{}
			}
		}
	}
	return v, nil
}

// ---- admin (Console) ----

func (s *Service) ListReports(ctx context.Context, f dommod.ReportFilter) ([]dommod.Report, int64, error) {
	return s.repo.ListReports(ctx, f)
}

func (s *Service) ListActions(ctx context.Context, limit int) ([]dommod.ActionRecord, error) {
	return s.repo.ListActions(ctx, limit)
}

// Stats is the Console dashboard aggregate.
type Stats struct {
	ByStatus    map[dommod.Status]int64
	ByReason    []dommod.ReasonCount
	TopPosts    []dommod.Aggregate
	TopUsers    []dommod.Aggregate
	TopReporter []dommod.Aggregate
}

func (s *Service) Stats(ctx context.Context) (*Stats, error) {
	byStatus, err := s.repo.CountByStatus(ctx)
	if err != nil {
		return nil, err
	}
	byReason, err := s.repo.CountByReason(ctx)
	if err != nil {
		return nil, err
	}
	topPosts, err := s.repo.TopReportedTargets(ctx, dommod.TargetPost, 10)
	if err != nil {
		return nil, err
	}
	topUsers, err := s.repo.TopReportedTargets(ctx, dommod.TargetUser, 10)
	if err != nil {
		return nil, err
	}
	topReporter, err := s.repo.TopReporters(ctx, 10)
	if err != nil {
		return nil, err
	}
	return &Stats{ByStatus: byStatus, ByReason: byReason, TopPosts: topPosts, TopUsers: topUsers, TopReporter: topReporter}, nil
}

// ActInput is one admin moderation decision.
type ActInput struct {
	ModeratorID string
	Action      string
	ReportID    string // optional
	TargetType  string
	TargetID    string
	Note        string
	SuspendDays int // for suspend_user; 0 = indefinite
}

// Act performs + audits an admin moderation action. Every action writes a
// moderation_actions row (audit) regardless of side effects.
func (s *Service) Act(ctx context.Context, in ActInput) error {
	action := dommod.Action(in.Action)
	if !action.Valid() {
		return dommod.ErrInvalidAction
	}
	tt := dommod.TargetType(in.TargetType)
	if !tt.Valid() {
		return dommod.ErrInvalidTarget
	}

	var reportID *uuid.UUID
	if strings.TrimSpace(in.ReportID) != "" {
		id, err := uuid.Parse(in.ReportID)
		if err != nil {
			return dommod.ErrReportNotFound
		}
		reportID = &id
	}

	// Side effects per action.
	switch action {
	case dommod.ActionRemove:
		if err := s.repo.HideContent(ctx, tt, in.TargetID); err != nil {
			return err
		}
		s.resolveReport(ctx, reportID, dommod.StatusResolved)
	case dommod.ActionRestore:
		if err := s.repo.RestoreContent(ctx, tt, in.TargetID); err != nil {
			return err
		}
		s.resolveReport(ctx, reportID, dommod.StatusResolved)
	case dommod.ActionSuspendUser:
		uid, err := uuid.Parse(in.TargetID)
		if err != nil {
			return dommod.ErrInvalidTarget
		}
		var until *time.Time
		if in.SuspendDays > 0 {
			t := s.now().Add(time.Duration(in.SuspendDays) * 24 * time.Hour)
			until = &t
		}
		if err := s.repo.SetUserState(ctx, uid, dommod.StateSuspended, until); err != nil {
			return err
		}
		s.resolveReport(ctx, reportID, dommod.StatusResolved)
	case dommod.ActionBanUser:
		uid, err := uuid.Parse(in.TargetID)
		if err != nil {
			return dommod.ErrInvalidTarget
		}
		if err := s.repo.SetUserState(ctx, uid, dommod.StateBanned, nil); err != nil {
			return err
		}
		s.resolveReport(ctx, reportID, dommod.StatusResolved)
	case dommod.ActionRestoreUser:
		uid, err := uuid.Parse(in.TargetID)
		if err != nil {
			return dommod.ErrInvalidTarget
		}
		if err := s.repo.SetUserState(ctx, uid, dommod.StateActive, nil); err != nil {
			return err
		}
	case dommod.ActionDismiss:
		s.resolveReport(ctx, reportID, dommod.StatusDismissed)
	}

	// Audit (always).
	rec := &dommod.ActionRecord{
		ID:          uuid.New(),
		ReportID:    reportID,
		ModeratorID: in.ModeratorID,
		Action:      action,
		TargetType:  tt,
		TargetID:    in.TargetID,
		Note:        strings.TrimSpace(in.Note),
		CreatedAt:   s.now(),
	}
	if err := s.repo.RecordAction(ctx, rec); err != nil {
		return fmt.Errorf("audit moderation action: %w", err)
	}
	s.mAction(in.Action)
	return nil
}

// ---- CONSOLE-SOCIAL-B: operator-driven read/transition helpers ----

// validReportTransition guards the report lifecycle. Idempotent (to == from) is
// allowed. open→reviewing/resolved/dismissed, reviewing→resolved/dismissed, and
// resolved/dismissed→reviewing (re-open for correction) are permitted.
func validReportTransition(from, to dommod.Status) bool {
	if from == to {
		return true
	}
	switch to {
	case dommod.StatusReviewing:
		return from == dommod.StatusOpen || from == dommod.StatusResolved || from == dommod.StatusDismissed
	case dommod.StatusResolved, dommod.StatusDismissed:
		return from == dommod.StatusOpen || from == dommod.StatusReviewing
	}
	return false
}

// TransitionReport moves a report to a valid lifecycle state (review/resolve/
// dismiss). Returns ErrReportNotFound / ErrInvalidAction on bad input. This is a
// pure report-status transition — content/user side effects go through Act.
func (s *Service) TransitionReport(ctx context.Context, id uuid.UUID, to dommod.Status) error {
	switch to {
	case dommod.StatusReviewing, dommod.StatusResolved, dommod.StatusDismissed:
	default:
		return dommod.ErrInvalidAction
	}
	rep, err := s.repo.GetReport(ctx, id)
	if err != nil {
		return dommod.ErrReportNotFound
	}
	if !validReportTransition(rep.Status, to) {
		return dommod.ErrInvalidAction
	}
	if rep.Status == to {
		return nil // idempotent no-op
	}
	if err := s.repo.SetReportStatus(ctx, id, to); err != nil {
		return err
	}
	s.mAction("report_" + string(to))
	return nil
}

// GetReport exposes a single report for the operator read model / correlation.
func (s *Service) GetReport(ctx context.Context, id uuid.UUID) (*dommod.Report, error) {
	return s.repo.GetReport(ctx, id)
}

// UserState exposes the current enforcement state of a user (read model +
// post-condition verification). Suspension expiry is derived: an elapsed
// suspension reads as active.
func (s *Service) UserState(ctx context.Context, userID uuid.UUID) (dommod.UserState, *time.Time, error) {
	state, until, err := s.repo.UserStateOf(ctx, userID)
	if err != nil {
		return "", nil, err
	}
	if state == dommod.StateSuspended && until != nil && !until.After(s.now()) {
		return dommod.StateActive, nil, nil
	}
	return state, until, nil
}

// IsContentHidden reports whether a post/comment is admin-hidden (read model +
// post-condition verification).
func (s *Service) IsContentHidden(ctx context.Context, t dommod.TargetType, id string) (bool, error) {
	hidden, err := s.repo.HiddenContent(ctx)
	if err != nil {
		return false, err
	}
	_, ok := hidden[string(t)+":"+id]
	return ok, nil
}

func (s *Service) resolveReport(ctx context.Context, id *uuid.UUID, status dommod.Status) {
	if id == nil {
		return
	}
	// Best-effort: a missing report must not fail the action's side effects.
	_ = s.repo.SetReportStatus(ctx, *id, status)
}

// ---- metrics (nil-safe) ----

func (s *Service) mInc(action string) {
	if s.metrics != nil {
		s.metrics.Block(action)
	}
}
func (s *Service) mReport(reason string) {
	if s.metrics != nil {
		s.metrics.Report(reason)
	}
}
func (s *Service) mAction(action string) {
	if s.metrics != nil {
		s.metrics.ModerationAction(action)
	}
}
