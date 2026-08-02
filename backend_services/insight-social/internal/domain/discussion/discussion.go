// Package discussion holds the Discussion aggregate + Message entity.
//
// Invariants enforced on construction (Start / Post):
//   - title: 1..200 chars after trim (Discussion only)
//   - body: 1..16384 chars after trim
//
// `reaction_count` exists in the proto but the W2.0 schema doesn't
// model reactions yet (no table, no event). Returned as 0 from the
// repo until a Reaction aggregate ships.
package discussion

import (
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
)

const (
	minBodyLen  = 1
	maxBodyLen  = 16384
	minTitleLen = 1
	maxTitleLen = 200
)

type Discussion struct {
	id               uuid.UUID
	communityID      uuid.UUID
	authorID         uuid.UUID
	title            string
	body             string
	matchID          *uuid.UUID
	messageCount     int64
	participantCount int64
	lastActivityTs   time.Time
	createdAt        time.Time
}

// Start constructs a fresh Discussion. The author is automatically
// counted as the first participant (participant_count = 1) but
// message_count stays 0 — the opening post lives in the
// `body` field, not in discussion_messages (legacy schema layout).
func Start(communityID, authorID uuid.UUID, title, body string, matchID *uuid.UUID) (*Discussion, error) {
	title = strings.TrimSpace(title)
	body = strings.TrimSpace(body)

	if l := len(title); l < minTitleLen || l > maxTitleLen {
		return nil, fmt.Errorf("%w: length %d out of %d..%d", ErrInvalidTitle, l, minTitleLen, maxTitleLen)
	}
	if l := len(body); l < minBodyLen || l > maxBodyLen {
		return nil, fmt.Errorf("%w: length %d out of %d..%d", ErrInvalidBody, l, minBodyLen, maxBodyLen)
	}

	now := time.Now().UTC()
	return &Discussion{
		id:               uuid.New(),
		communityID:      communityID,
		authorID:         authorID,
		title:            title,
		body:             body,
		matchID:          matchID,
		messageCount:     0,
		participantCount: 1,
		lastActivityTs:   now,
		createdAt:        now,
	}, nil
}

func ReconstituteDiscussion(id, communityID, authorID uuid.UUID, title, body string,
	matchID *uuid.UUID, messageCount, participantCount int64,
	lastActivityTs, createdAt time.Time) *Discussion {
	return &Discussion{
		id:               id,
		communityID:      communityID,
		authorID:         authorID,
		title:            title,
		body:             body,
		matchID:          matchID,
		messageCount:     messageCount,
		participantCount: participantCount,
		lastActivityTs:   lastActivityTs,
		createdAt:        createdAt,
	}
}

func (d *Discussion) ID() uuid.UUID             { return d.id }
func (d *Discussion) CommunityID() uuid.UUID    { return d.communityID }
func (d *Discussion) AuthorID() uuid.UUID       { return d.authorID }
func (d *Discussion) Title() string             { return d.title }
func (d *Discussion) Body() string              { return d.body }
func (d *Discussion) MatchID() *uuid.UUID       { return d.matchID }
func (d *Discussion) MessageCount() int64       { return d.messageCount }
func (d *Discussion) ParticipantCount() int64   { return d.participantCount }
func (d *Discussion) LastActivityTs() time.Time { return d.lastActivityTs }
func (d *Discussion) CreatedAt() time.Time      { return d.createdAt }

// Message is a reply on a discussion. Its own entity because it has
// its own lifecycle and is paginated independently.
type Message struct {
	ID           uuid.UUID
	DiscussionID uuid.UUID
	AuthorID     uuid.UUID
	Body         string
	CreatedAt    time.Time
}

// NewMessage validates a fresh reply.
func NewMessage(discussionID, authorID uuid.UUID, body string) (*Message, error) {
	body = strings.TrimSpace(body)
	if l := len(body); l < minBodyLen || l > maxBodyLen {
		return nil, fmt.Errorf("%w: length %d out of %d..%d", ErrInvalidBody, l, minBodyLen, maxBodyLen)
	}
	return &Message{
		ID:           uuid.New(),
		DiscussionID: discussionID,
		AuthorID:     authorID,
		Body:         body,
		CreatedAt:    time.Now().UTC(),
	}, nil
}
