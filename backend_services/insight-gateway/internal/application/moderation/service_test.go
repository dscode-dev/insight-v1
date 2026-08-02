package moderation

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"

	dommod "github.com/konoha-labs/insight-gateway/internal/domain/moderation"
)

// fakeRepo is an in-memory moderation.Repo for headless service tests.
type fakeRepo struct {
	blocks    map[uuid.UUID]map[uuid.UUID]struct{}
	reports   map[uuid.UUID]*dommod.Report
	actions   []dommod.ActionRecord
	hidden    map[string]struct{}
	userState map[uuid.UUID]dommod.UserState
	userUntil map[uuid.UUID]*time.Time
}

func newFakeRepo() *fakeRepo {
	return &fakeRepo{
		blocks:    map[uuid.UUID]map[uuid.UUID]struct{}{},
		reports:   map[uuid.UUID]*dommod.Report{},
		hidden:    map[string]struct{}{},
		userState: map[uuid.UUID]dommod.UserState{},
		userUntil: map[uuid.UUID]*time.Time{},
	}
}

func (f *fakeRepo) Block(_ context.Context, b, t uuid.UUID) error {
	if f.blocks[b] == nil {
		f.blocks[b] = map[uuid.UUID]struct{}{}
	}
	f.blocks[b][t] = struct{}{}
	return nil
}
func (f *fakeRepo) Unblock(_ context.Context, b, t uuid.UUID) error {
	delete(f.blocks[b], t)
	return nil
}
func (f *fakeRepo) BlockedBy(_ context.Context, b uuid.UUID) ([]uuid.UUID, error) {
	var out []uuid.UUID
	for id := range f.blocks[b] {
		out = append(out, id)
	}
	return out, nil
}
func (f *fakeRepo) CreateReport(_ context.Context, r *dommod.Report) error {
	f.reports[r.ID] = r
	return nil
}
func (f *fakeRepo) ListReports(context.Context, dommod.ReportFilter) ([]dommod.Report, int64, error) {
	return nil, int64(len(f.reports)), nil
}
func (f *fakeRepo) GetReport(_ context.Context, id uuid.UUID) (*dommod.Report, error) {
	if r, ok := f.reports[id]; ok {
		return r, nil
	}
	return nil, dommod.ErrReportNotFound
}
func (f *fakeRepo) SetReportStatus(_ context.Context, id uuid.UUID, s dommod.Status) error {
	if r, ok := f.reports[id]; ok {
		r.Status = s
		return nil
	}
	return dommod.ErrReportNotFound
}
func (f *fakeRepo) CountByStatus(context.Context) (map[dommod.Status]int64, error) {
	return map[dommod.Status]int64{}, nil
}
func (f *fakeRepo) CountByReason(context.Context) ([]dommod.ReasonCount, error) { return nil, nil }
func (f *fakeRepo) TopReportedTargets(context.Context, dommod.TargetType, int) ([]dommod.Aggregate, error) {
	return nil, nil
}
func (f *fakeRepo) TopReporters(context.Context, int) ([]dommod.Aggregate, error) { return nil, nil }
func (f *fakeRepo) RecordAction(_ context.Context, a *dommod.ActionRecord) error {
	f.actions = append(f.actions, *a)
	return nil
}
func (f *fakeRepo) ListActions(context.Context, int) ([]dommod.ActionRecord, error) {
	return f.actions, nil
}
func (f *fakeRepo) HideContent(_ context.Context, t dommod.TargetType, id string) error {
	f.hidden[string(t)+":"+id] = struct{}{}
	return nil
}
func (f *fakeRepo) RestoreContent(_ context.Context, t dommod.TargetType, id string) error {
	delete(f.hidden, string(t)+":"+id)
	return nil
}
func (f *fakeRepo) HiddenContent(context.Context) (map[string]struct{}, error) {
	out := map[string]struct{}{}
	for k := range f.hidden {
		out[k] = struct{}{}
	}
	return out, nil
}
func (f *fakeRepo) SetUserState(_ context.Context, u uuid.UUID, s dommod.UserState, until *time.Time) error {
	f.userState[u] = s
	if f.userUntil == nil {
		f.userUntil = map[uuid.UUID]*time.Time{}
	}
	f.userUntil[u] = until
	return nil
}
func (f *fakeRepo) UserStateOf(_ context.Context, u uuid.UUID) (dommod.UserState, *time.Time, error) {
	if s, ok := f.userState[u]; ok {
		var until *time.Time
		if f.userUntil != nil {
			until = f.userUntil[u]
		}
		return s, until, nil
	}
	return dommod.StateActive, nil, nil
}
func (f *fakeRepo) NonActiveUsers(context.Context) ([]uuid.UUID, error) {
	var out []uuid.UUID
	for u, s := range f.userState {
		if s == dommod.StateBanned || s == dommod.StateSuspended {
			out = append(out, u)
		}
	}
	return out, nil
}

func newSvc() (*Service, *fakeRepo) {
	repo := newFakeRepo()
	return NewService(Deps{Repo: repo}), repo
}

func TestBlock_RejectsSelf(t *testing.T) {
	svc, _ := newSvc()
	me := uuid.New()
	if err := svc.Block(context.Background(), me, me.String()); !errors.Is(err, dommod.ErrSelfBlock) {
		t.Fatalf("expected ErrSelfBlock, got %v", err)
	}
}

func TestReport_ValidatesReasonAndTarget(t *testing.T) {
	svc, _ := newSvc()
	me := uuid.New()
	if _, err := svc.Report(context.Background(), ReportInput{ReporterID: me, TargetType: "post", TargetID: "p1", Reason: "bogus"}); !errors.Is(err, dommod.ErrInvalidReason) {
		t.Fatalf("expected ErrInvalidReason, got %v", err)
	}
	rep, err := svc.Report(context.Background(), ReportInput{ReporterID: me, TargetType: "post", TargetID: "p1", Reason: "spam"})
	if err != nil {
		t.Fatalf("Report: %v", err)
	}
	if rep.Status != dommod.StatusOpen {
		t.Fatalf("new report should be open, got %s", rep.Status)
	}
}

func TestAct_BanUser_AuditsAndSetsState(t *testing.T) {
	svc, repo := newSvc()
	target := uuid.New()
	// seed a report so we can confirm it's resolved
	rep := &dommod.Report{ID: uuid.New(), TargetType: dommod.TargetUser, TargetID: target.String(), Status: dommod.StatusOpen}
	repo.reports[rep.ID] = rep

	err := svc.Act(context.Background(), ActInput{
		ModeratorID: "op-1", Action: "ban_user", ReportID: rep.ID.String(),
		TargetType: "user", TargetID: target.String(),
	})
	if err != nil {
		t.Fatalf("Act: %v", err)
	}
	if repo.userState[target] != dommod.StateBanned {
		t.Fatalf("expected user banned, got %s", repo.userState[target])
	}
	if rep.Status != dommod.StatusResolved {
		t.Fatalf("expected report resolved, got %s", rep.Status)
	}
	if len(repo.actions) != 1 || repo.actions[0].Action != dommod.ActionBanUser {
		t.Fatalf("expected one audited ban action, got %+v", repo.actions)
	}
}

func TestEnsureCanAct_BlocksBanned(t *testing.T) {
	svc, repo := newSvc()
	u := uuid.New()
	repo.userState[u] = dommod.StateBanned
	if err := svc.EnsureCanAct(context.Background(), u); !errors.Is(err, dommod.ErrUserBanned) {
		t.Fatalf("expected ErrUserBanned, got %v", err)
	}
}

func TestViewFor_HidesBlockedBannedAndHiddenContent(t *testing.T) {
	svc, repo := newSvc()
	viewer := uuid.New()
	blocked := uuid.New()
	banned := uuid.New()
	_ = repo.Block(context.Background(), viewer, blocked)
	repo.userState[banned] = dommod.StateBanned
	_ = repo.HideContent(context.Background(), dommod.TargetPost, "post-hidden")
	_ = repo.HideContent(context.Background(), dommod.TargetComment, "comment-hidden")

	v, err := svc.ViewFor(context.Background(), viewer.String())
	if err != nil {
		t.Fatalf("ViewFor: %v", err)
	}
	if !v.AuthorHidden(blocked.String()) {
		t.Fatal("blocked author should be hidden")
	}
	if !v.AuthorHidden(banned.String()) {
		t.Fatal("banned author should be hidden")
	}
	if !v.PostHidden("post-hidden") || !v.CommentHidden("comment-hidden") {
		t.Fatal("admin-hidden content should be hidden")
	}
	if v.AuthorHidden(uuid.New().String()) {
		t.Fatal("random author should not be hidden")
	}
}
