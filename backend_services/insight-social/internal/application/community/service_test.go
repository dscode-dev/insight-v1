package community

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"

	domcommunity "github.com/konoha-labs/insight-social/internal/domain/community"
)

// fakeRepo records calls and returns canned results. Implements the domain
// Repository interface. Only the methods the service exercises are meaningful.
type fakeRepo struct {
	insertOwned    *domcommunity.Community
	insertOwnedErr error
	membersFilter  domcommunity.ListMembersFilter
	membersPage    domcommunity.MembersPage
	removeErr      error
	addErr         error
	addMembership  *domcommunity.Membership
}

func (f *fakeRepo) Insert(context.Context, *domcommunity.Community) error { return nil }

func (f *fakeRepo) InsertOwned(_ context.Context, c *domcommunity.Community) (*domcommunity.Membership, error) {
	f.insertOwned = c
	if f.insertOwnedErr != nil {
		return nil, f.insertOwnedErr
	}
	return &domcommunity.Membership{
		UserID:      *c.OwnerUserID(),
		CommunityID: c.ID(),
		Role:        domcommunity.RoleOwner,
		IsModerator: true,
	}, nil
}

func (f *fakeRepo) GetByID(context.Context, uuid.UUID) (*domcommunity.Community, error) {
	return nil, domcommunity.ErrNotFound
}
func (f *fakeRepo) GetBySlug(context.Context, string) (*domcommunity.Community, error) {
	return nil, domcommunity.ErrNotFound
}
func (f *fakeRepo) List(context.Context, domcommunity.ListFilter) (domcommunity.ListPage, error) {
	return domcommunity.ListPage{}, nil
}
func (f *fakeRepo) ListForUser(context.Context, domcommunity.ListForUserFilter) (domcommunity.ListPage, error) {
	return domcommunity.ListPage{}, nil
}
func (f *fakeRepo) ListMembers(_ context.Context, flt domcommunity.ListMembersFilter) (domcommunity.MembersPage, error) {
	f.membersFilter = flt
	return f.membersPage, nil
}
func (f *fakeRepo) GetMembership(context.Context, uuid.UUID, uuid.UUID) (*domcommunity.Membership, error) {
	return nil, domcommunity.ErrNotMember
}
func (f *fakeRepo) GetStats(context.Context, uuid.UUID) (domcommunity.Stats, error) {
	return domcommunity.Stats{}, nil
}
func (f *fakeRepo) AddMember(context.Context, uuid.UUID, uuid.UUID) (*domcommunity.Membership, error) {
	if f.addErr != nil {
		return nil, f.addErr
	}
	return f.addMembership, nil
}
func (f *fakeRepo) RemoveMember(context.Context, uuid.UUID, uuid.UUID) error { return f.removeErr }

// ---- tests ----

func TestCreateTopic_AtomicOwnedCreation(t *testing.T) {
	f := &fakeRepo{}
	svc := New(f)
	owner := uuid.New()

	c, err := svc.CreateTopic(context.Background(), "tatica-fc", "Tática FC", "4-3-3", "", owner)
	if err != nil {
		t.Fatalf("CreateTopic: %v", err)
	}
	// Must have gone through the ATOMIC owned path (not plain Insert).
	if f.insertOwned == nil {
		t.Fatal("CreateTopic must use InsertOwned (atomic owner + OWNER membership)")
	}
	if !c.OwnerAssigned() || *c.OwnerUserID() != owner {
		t.Fatal("created community must carry the owner")
	}
}

func TestCreateTopic_RejectsMissingOwner(t *testing.T) {
	svc := New(&fakeRepo{})
	if _, err := svc.CreateTopic(context.Background(), "tatica-fc", "Tática FC", "4-3-3", "", uuid.Nil); !errors.Is(err, domcommunity.ErrOwnerRequired) {
		t.Fatalf("missing owner must be rejected before persistence, got %v", err)
	}
}

func TestListMembers_PassesFilterAndClampsLimit(t *testing.T) {
	f := &fakeRepo{}
	svc := New(f)
	cid := uuid.New()
	role := domcommunity.RoleAdmin

	if _, err := svc.ListMembers(context.Background(), cid, &role, 0, "cur"); err != nil {
		t.Fatalf("ListMembers: %v", err)
	}
	if f.membersFilter.CommunityID != cid {
		t.Fatal("community id not forwarded")
	}
	if f.membersFilter.RoleFilter == nil || *f.membersFilter.RoleFilter != role {
		t.Fatal("role filter not forwarded (owner/admin/mod projection reuses ListMembers)")
	}
	if f.membersFilter.Cursor != "cur" {
		t.Fatal("cursor not forwarded")
	}
	if f.membersFilter.Limit != defaultListLimit {
		t.Fatalf("limit 0 must clamp to default %d, got %d", defaultListLimit, f.membersFilter.Limit)
	}
}

func TestLeave_PropagatesOwnerBlock(t *testing.T) {
	// The owner-leave invariant is enforced in the repo; the service must
	// surface it unchanged (never swallow it into success).
	f := &fakeRepo{removeErr: domcommunity.ErrOwnerCannotLeave}
	svc := New(f)
	if err := svc.Leave(context.Background(), uuid.New(), uuid.New()); !errors.Is(err, domcommunity.ErrOwnerCannotLeave) {
		t.Fatalf("owner-leave block must propagate, got %v", err)
	}
}

func TestLeave_IdempotentForNonMember(t *testing.T) {
	f := &fakeRepo{removeErr: domcommunity.ErrNotMember}
	svc := New(f)
	if err := svc.Leave(context.Background(), uuid.New(), uuid.New()); !errors.Is(err, domcommunity.ErrNotMember) {
		t.Fatalf("leave of a non-member surfaces ErrNotMember (idempotent at handler), got %v", err)
	}
}

func TestJoin_AlreadyMemberNeverOverwrites(t *testing.T) {
	// A re-join hits the unique constraint → ErrAlreadyMember; the existing
	// (possibly privileged) role is never overwritten.
	f := &fakeRepo{addErr: domcommunity.ErrAlreadyMember}
	svc := New(f)
	if _, err := svc.Join(context.Background(), uuid.New(), uuid.New()); !errors.Is(err, domcommunity.ErrAlreadyMember) {
		t.Fatalf("re-join must return ErrAlreadyMember (no role overwrite), got %v", err)
	}
}
