// CONSOLE-SOCIAL-B — report lifecycle transitions + enforcement read model proofs.
package moderation

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"

	dommod "github.com/konoha-labs/insight-gateway/internal/domain/moderation"
)

func seedReport(repo *fakeRepo, status dommod.Status) uuid.UUID {
	id := uuid.New()
	repo.reports[id] = &dommod.Report{ID: id, Status: status, TargetType: dommod.TargetPost, TargetID: "p1"}
	return id
}

func TestTransitionReport_ValidAndIdempotent(t *testing.T) {
	svc, repo := newSvc()
	id := seedReport(repo, dommod.StatusOpen)

	if err := svc.TransitionReport(context.Background(), id, dommod.StatusReviewing); err != nil {
		t.Fatalf("open→reviewing should succeed: %v", err)
	}
	if repo.reports[id].Status != dommod.StatusReviewing {
		t.Fatalf("status not updated: %s", repo.reports[id].Status)
	}
	// Idempotent: reviewing→reviewing is a no-op, not an error.
	if err := svc.TransitionReport(context.Background(), id, dommod.StatusReviewing); err != nil {
		t.Fatalf("idempotent transition should succeed: %v", err)
	}
	if err := svc.TransitionReport(context.Background(), id, dommod.StatusResolved); err != nil {
		t.Fatalf("reviewing→resolved should succeed: %v", err)
	}
}

func TestTransitionReport_InvalidTarget(t *testing.T) {
	svc, repo := newSvc()
	id := seedReport(repo, dommod.StatusOpen)
	// "open" is not a valid *destination* transition state.
	if err := svc.TransitionReport(context.Background(), id, dommod.StatusOpen); err != dommod.ErrInvalidAction {
		t.Fatalf("want ErrInvalidAction for illegal destination, got %v", err)
	}
}

func TestTransitionReport_NotFound(t *testing.T) {
	svc, _ := newSvc()
	if err := svc.TransitionReport(context.Background(), uuid.New(), dommod.StatusResolved); err != dommod.ErrReportNotFound {
		t.Fatalf("want ErrReportNotFound, got %v", err)
	}
}

func TestUserState_DerivesExpiredSuspensionAsActive(t *testing.T) {
	svc, repo := newSvc()
	u := uuid.New()
	past := time.Now().Add(-time.Hour)
	repo.userState[u] = dommod.StateSuspended
	repo.userUntil = map[uuid.UUID]*time.Time{u: &past}

	state, _, err := svc.UserState(context.Background(), u)
	if err != nil {
		t.Fatal(err)
	}
	if state != dommod.StateActive {
		t.Fatalf("elapsed suspension must read active, got %s", state)
	}
}

func TestIsContentHidden(t *testing.T) {
	svc, repo := newSvc()
	_ = repo.HideContent(context.Background(), dommod.TargetPost, "p9")
	hidden, err := svc.IsContentHidden(context.Background(), dommod.TargetPost, "p9")
	if err != nil || !hidden {
		t.Fatalf("expected hidden, got hidden=%v err=%v", hidden, err)
	}
	visible, _ := svc.IsContentHidden(context.Background(), dommod.TargetPost, "nope")
	if visible {
		t.Fatal("unknown content must read not-hidden")
	}
}
