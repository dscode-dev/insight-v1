package post

import (
	"errors"
	"testing"

	"github.com/google/uuid"
)

// The public feed is partitioned by competition — the rail under the header
// picks one and the feed narrows to it. These pin the rules that decide
// whether a post can be placed in a rail at all.

func TestCompetitionScopedPostMustNameACompetition(t *testing.T) {
	// The database enforces this too (posts_competition_scope_check). It is
	// repeated here so the caller gets a domain error it can map to a 400,
	// instead of a driver error it has to parse.
	_, err := NewPost(uuid.New(), AuthorUser, "sem campeonato", nil,
		VisibilityCompetition, nil)
	if !errors.Is(err, ErrCompetitionRequired) {
		t.Fatalf("esperava ErrCompetitionRequired, veio %v", err)
	}
}

func TestZeroUUIDIsRejectedAsAbsent(t *testing.T) {
	// A zero UUID passes a nil check and then fails the foreign key, which
	// reports "competition does not exist" — a misleading answer to "you sent
	// an empty id".
	zero := uuid.UUID{}
	_, err := NewPost(uuid.New(), AuthorUser, "id vazio", nil,
		VisibilityCompetition, &zero)
	if !errors.Is(err, ErrCompetitionRequired) {
		t.Fatalf("esperava ErrCompetitionRequired, veio %v", err)
	}
}

func TestPublicPostMayCarryACompetition(t *testing.T) {
	// This is how a public post reaches a competition's rail: the competition
	// says WHERE it appears, the visibility says WHO can see it. Conflating
	// them would make every competition post private to that competition.
	id := uuid.New()
	p, err := NewPost(uuid.New(), AuthorUser, "publico com campeonato", nil,
		VisibilityPublic, &id)
	if err != nil {
		t.Fatalf("post publico com campeonato recusado: %v", err)
	}
	if p.CompetitionID == nil || *p.CompetitionID != id {
		t.Fatalf("competition_id nao preservado: %v", p.CompetitionID)
	}
}

func TestPublicPostWithoutCompetitionIsPlatformWide(t *testing.T) {
	p, err := NewPost(uuid.New(), AuthorUser, "sem campeonato", nil,
		VisibilityPublic, nil)
	if err != nil {
		t.Fatalf("post sem campeonato recusado: %v", err)
	}
	if p.CompetitionID != nil {
		t.Fatalf("esperava nil, veio %v", *p.CompetitionID)
	}
}

func TestCompetitionScopedPostWithACompetitionIsValid(t *testing.T) {
	id := uuid.New()
	p, err := NewPost(uuid.New(), AuthorUser, "valido", nil,
		VisibilityCompetition, &id)
	if err != nil {
		t.Fatalf("recusado: %v", err)
	}
	if p.Visibility != VisibilityCompetition || p.CompetitionID == nil {
		t.Fatal("visibilidade e campeonato deviam viajar juntos")
	}
}

func TestDenormalisedFieldsAreNotAcceptedOnWrite(t *testing.T) {
	// Slug and name are filled on READ, from the join. If NewPost could set
	// them, a caller could publish a post whose chip says "Brasileirão" while
	// competition_id points at LaLiga — and nothing downstream would catch it,
	// because only the id is checked against the registry.
	id := uuid.New()
	p, err := NewPost(uuid.New(), AuthorUser, "x", nil, VisibilityCompetition, &id)
	if err != nil {
		t.Fatalf("recusado: %v", err)
	}
	if p.CompetitionSlug != "" || p.CompetitionName != "" {
		t.Fatalf("campos denormalizados deviam nascer vazios: %q / %q",
			p.CompetitionSlug, p.CompetitionName)
	}
}
