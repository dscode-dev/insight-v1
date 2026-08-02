// CONSOLE-SOCIAL-B — agent publication enforcement proofs.
//
// A deactivated agent must not publish through the create choke point; an active
// agent (and any user) is unaffected. This is the authoritative enforcement that
// makes agent deactivation non-decorative.
package post

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"

	dompost "github.com/konoha-labs/insight-social/internal/domain/post"
)

type memPostRepo struct{ posts map[uuid.UUID]*dompost.Post }

func newMemRepo() *memPostRepo { return &memPostRepo{posts: map[uuid.UUID]*dompost.Post{}} }

func (m *memPostRepo) InsertPost(_ context.Context, p *dompost.Post) error {
	m.posts[p.ID] = p
	return nil
}
func (m *memPostRepo) GetPost(_ context.Context, id uuid.UUID) (*dompost.Post, error) {
	if p, ok := m.posts[id]; ok {
		return p, nil
	}
	return nil, dompost.ErrNotFound
}
func (m *memPostRepo) SoftDeletePost(context.Context, uuid.UUID, uuid.UUID) error { return nil }
func (m *memPostRepo) InsertComment(context.Context, *dompost.Comment) error      { return nil }
func (m *memPostRepo) GetComment(context.Context, uuid.UUID) (*dompost.Comment, error) {
	return nil, dompost.ErrCommentNotFound
}
func (m *memPostRepo) ListComments(context.Context, uuid.UUID, int, string) (dompost.CommentPage, error) {
	return dompost.CommentPage{}, nil
}
func (m *memPostRepo) Like(context.Context, uuid.UUID, uuid.UUID) error   { return nil }
func (m *memPostRepo) Unlike(context.Context, uuid.UUID, uuid.UUID) error { return nil }

type stubGuard struct {
	active bool
	err    error
	calls  int
}

func (g *stubGuard) IsActive(context.Context, uuid.UUID) (bool, error) {
	g.calls++
	return g.active, g.err
}

func TestCreate_AgentInactive_Blocked(t *testing.T) {
	g := &stubGuard{active: false}
	svc := New(newMemRepo()).WithAgentGuard(g)
	_, err := svc.Create(context.Background(), uuid.New(), dompost.AuthorAgent, "x", nil, dompost.VisibilityPublic)
	if !errors.Is(err, dompost.ErrAgentInactive) {
		t.Fatalf("want ErrAgentInactive, got %v", err)
	}
	if g.calls != 1 {
		t.Fatalf("guard should be consulted once, got %d", g.calls)
	}
}

func TestCreate_AgentActive_Allowed(t *testing.T) {
	g := &stubGuard{active: true}
	svc := New(newMemRepo()).WithAgentGuard(g)
	p, err := svc.Create(context.Background(), uuid.New(), dompost.AuthorAgent, "x", nil, dompost.VisibilityPublic)
	if err != nil || p == nil {
		t.Fatalf("active agent should publish, got err=%v", err)
	}
}

func TestCreate_User_NotGated(t *testing.T) {
	g := &stubGuard{active: false} // would block an agent
	svc := New(newMemRepo()).WithAgentGuard(g)
	p, err := svc.Create(context.Background(), uuid.New(), dompost.AuthorUser, "x", nil, dompost.VisibilityPublic)
	if err != nil || p == nil {
		t.Fatalf("user publish must not be agent-gated, got err=%v", err)
	}
	if g.calls != 0 {
		t.Fatalf("guard must not be consulted for user authorship, got %d calls", g.calls)
	}
}

func TestCreate_AgentGuardError_FailsClosed(t *testing.T) {
	g := &stubGuard{err: errors.New("db down")}
	svc := New(newMemRepo()).WithAgentGuard(g)
	_, err := svc.Create(context.Background(), uuid.New(), dompost.AuthorAgent, "x", nil, dompost.VisibilityPublic)
	if err == nil {
		t.Fatal("guard error must fail closed (no publish)")
	}
}
