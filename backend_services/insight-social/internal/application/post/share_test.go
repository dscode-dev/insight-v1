package post

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"

	dompost "github.com/konoha-labs/insight-social/internal/domain/post"
)

// Two rules live in the service rather than the repository, because both
// produce an answer the API turns into a 400 naming a field — where a
// constraint violation would arrive as a driver error the caller must parse.

func TestRepostRejectsAChannel(t *testing.T) {
	// A channel says WHERE an external share went. On a repost it is a value
	// no reader can interpret, and the database refuses it too
	// (post_shares_channel_scope_check).
	svc := New(newMemRepo())
	_, _, err := svc.Share(context.Background(), uuid.New(), uuid.New(),
		dompost.ShareFeed, "whatsapp")
	if !errors.Is(err, dompost.ErrChannelOnRepost) {
		t.Fatalf("esperava ErrChannelOnRepost, veio %v", err)
	}
}

func TestExternalShareAcceptsAChannelAndAlsoNone(t *testing.T) {
	// Optional by design: the client often cannot tell where a share went, and
	// a required field would be filled with a guess.
	svc := New(newMemRepo())
	post, user := uuid.New(), uuid.New()
	for _, channel := range []string{"whatsapp", ""} {
		if _, _, err := svc.Share(context.Background(), post, user,
			dompost.ShareExternal, channel); err != nil {
			t.Fatalf("canal %q recusado: %v", channel, err)
		}
	}
}

func TestUnknownTargetNeverReachesSQL(t *testing.T) {
	svc := New(newMemRepo())
	for _, target := range []string{"", "telepatia", "FEED"} {
		_, _, err := svc.Share(context.Background(), uuid.New(), uuid.New(), target, "")
		if !errors.Is(err, dompost.ErrInvalidShareTarget) {
			t.Errorf("target %q devia ser recusado, veio %v", target, err)
		}
	}
}

func TestRepostIsAStateAndExternalShareIsAnEvent(t *testing.T) {
	// The distinction the whole design rests on. A repost twice leaves one and
	// reports created=false, so the client can tell "done" from "already done"
	// instead of animating a change that never happened. An external share
	// repeats, because the same person really does send the same post twice.
	svc := New(newMemRepo())
	post, user := uuid.New(), uuid.New()

	created, first, err := svc.Share(context.Background(), post, user, dompost.ShareFeed, "")
	if err != nil || !created {
		t.Fatalf("primeiro repost: created=%v err=%v", created, err)
	}
	created, second, err := svc.Share(context.Background(), post, user, dompost.ShareFeed, "")
	if err != nil {
		t.Fatalf("repost repetido: %v", err)
	}
	if created {
		t.Error("repost repetido devia reportar created=false")
	}
	if second != first {
		t.Errorf("contagem mudou num repost repetido: %d -> %d", first, second)
	}

	_, afterA, _ := svc.Share(context.Background(), post, user, dompost.ShareExternal, "whatsapp")
	_, afterB, _ := svc.Share(context.Background(), post, user, dompost.ShareExternal, "copy_link")
	if afterB <= afterA {
		t.Errorf("compartilhamentos externos deviam somar: %d -> %d", afterA, afterB)
	}
}

func TestUnshareIsIdempotent(t *testing.T) {
	// The button is a toggle: removing a repost that is not there satisfies
	// the same intent, so it is not an error.
	svc := New(newMemRepo())
	post, user := uuid.New(), uuid.New()
	if err := svc.Unshare(context.Background(), post, user); err != nil {
		t.Fatalf("unshare sem repost devia passar: %v", err)
	}
	if _, _, err := svc.Share(context.Background(), post, user, dompost.ShareFeed, ""); err != nil {
		t.Fatal(err)
	}
	if err := svc.Unshare(context.Background(), post, user); err != nil {
		t.Fatalf("unshare: %v", err)
	}
	// Reposting after unsharing is a fresh creation, not a no-op.
	created, _, err := svc.Share(context.Background(), post, user, dompost.ShareFeed, "")
	if err != nil || !created {
		t.Fatalf("repost apos unshare: created=%v err=%v", created, err)
	}
}
