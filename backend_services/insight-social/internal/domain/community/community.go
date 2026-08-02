// Package community holds the Community aggregate + CommunityMember
// entity.
//
// Invariants:
//   - slug: 3..48 chars, [a-z0-9_-], lowercased on creation
//   - name: 1..80 chars after trim
//   - topic: 1..160 chars after trim
//   - accent_color: #RRGGBB; auto-derived from slug if empty
//   - kind: TOPIC (from CreateTopic) or COMPETITION (from a separate
//     sync path not yet implemented in W2.1a)
package community

import (
	"fmt"
	"hash/crc32"
	"regexp"
	"strings"
	"time"

	"github.com/google/uuid"
)

// Same palette as user accents — keeps the brand surface consistent
// across the app. Append-only to avoid shifting existing rows.
var accentPalette = []string{
	"#5BA8FF", "#FF7A59", "#FFC857", "#56C596",
	"#B388EB", "#FF6B9D", "#4ECDC4", "#F4A261",
}

var (
	slugRE     = regexp.MustCompile(`^[a-z0-9_-]{3,48}$`)
	hexColorRE = regexp.MustCompile(`^#[0-9A-Fa-f]{6}$`)
)

type Community struct {
	id            uuid.UUID
	slug          string
	name          string
	topic         string
	kind          Kind
	competitionID *uuid.UUID // nil for KindTopic
	accentColor   string
	memberCount   int64
	activeNow     int64
	createdAt     time.Time
	ownerUserID   *uuid.UUID // nil => OWNER_UNASSIGNED (legacy / competition)
}

// NewTopic constructs a user-curated topic community OWNED by ownerUserID.
// New topic communities are always born with an owner (invariant): the
// repository creates the community and the OWNER membership in one
// transaction. CompetitionID is always nil for this constructor —
// auto-created competition communities use a different, ownerless path and
// remain OWNER_UNASSIGNED.
func NewTopic(slug, name, topic, accentColor string, ownerUserID uuid.UUID) (*Community, error) {
	slug = strings.ToLower(strings.TrimSpace(slug))
	name = strings.TrimSpace(name)
	topic = strings.TrimSpace(topic)

	if ownerUserID == uuid.Nil {
		return nil, ErrOwnerRequired
	}
	if !slugRE.MatchString(slug) {
		return nil, fmt.Errorf("%w: must match %s", ErrInvalidSlug, slugRE.String())
	}
	if l := len(name); l < 1 || l > 80 {
		return nil, fmt.Errorf("%w: length %d out of 1..80", ErrInvalidName, l)
	}
	if l := len(topic); l < 1 || l > 160 {
		return nil, fmt.Errorf("%w: length %d out of 1..160", ErrInvalidTopic, l)
	}
	if accentColor == "" {
		accentColor = deriveAccent(slug)
	} else if !hexColorRE.MatchString(accentColor) {
		return nil, fmt.Errorf("%w: %q is not #RRGGBB", ErrInvalidAccentColor, accentColor)
	}

	owner := ownerUserID
	return &Community{
		id:          uuid.New(),
		slug:        slug,
		name:        name,
		topic:       topic,
		kind:        KindTopic,
		accentColor: accentColor,
		createdAt:   time.Now().UTC(),
		ownerUserID: &owner,
	}, nil
}

// Reconstitute rebuilds from persisted state without validation.
// ownerUserID is nil for OWNER_UNASSIGNED communities.
func Reconstitute(id uuid.UUID, slug, name, topic string, kind Kind,
	competitionID *uuid.UUID, accentColor string, memberCount, activeNow int64,
	createdAt time.Time, ownerUserID *uuid.UUID) *Community {
	return &Community{
		id:            id,
		slug:          slug,
		name:          name,
		topic:         topic,
		kind:          kind,
		competitionID: competitionID,
		accentColor:   accentColor,
		memberCount:   memberCount,
		activeNow:     activeNow,
		createdAt:     createdAt,
		ownerUserID:   ownerUserID,
	}
}

// ---- accessors ----
func (c *Community) ID() uuid.UUID             { return c.id }
func (c *Community) Slug() string              { return c.slug }
func (c *Community) Name() string              { return c.name }
func (c *Community) Topic() string             { return c.topic }
func (c *Community) Kind() Kind                { return c.kind }
func (c *Community) CompetitionID() *uuid.UUID { return c.competitionID }
func (c *Community) AccentColor() string       { return c.accentColor }
func (c *Community) MemberCount() int64        { return c.memberCount }
func (c *Community) ActiveNow() int64          { return c.activeNow }
func (c *Community) CreatedAt() time.Time      { return c.createdAt }
func (c *Community) OwnerUserID() *uuid.UUID   { return c.ownerUserID }

// OwnerAssigned reports whether the community has a known owner. False =>
// OWNER_UNASSIGNED (a legacy community, or a competition community).
func (c *Community) OwnerAssigned() bool { return c.ownerUserID != nil }

func deriveAccent(slug string) string {
	h := crc32.ChecksumIEEE([]byte(slug))
	return accentPalette[int(h)%len(accentPalette)]
}

// ---- Membership entity ----
//
// A standalone entity (not nested inside Community) because the join
// table has its own lifecycle (created at JOIN, deleted at LEAVE) and
// the aggregate boundary stays small (we don't load all members when
// we load a community).
type Membership struct {
	UserID      uuid.UUID
	CommunityID uuid.UUID
	JoinedAt    time.Time
	Role        Role
	// IsModerator is DEPRECATED — kept for wire compatibility and always
	// derived from Role (Role.LegacyIsModerator). Do not read it for
	// authorization; use Role.
	IsModerator bool
}

// MemberProfile is an enriched member row (community_members JOIN users)
// returned by ListMembers. Only PUBLIC profile fields — never private data.
type MemberProfile struct {
	UserID      uuid.UUID
	Username    string
	DisplayName string
	Initials    string
	AccentColor string
	AvatarURL   string
	Reputation  int32
	Role        Role
	JoinedAt    time.Time
}

// MembersPage is the repository return shape for ListMembers.
type MembersPage struct {
	Members    []MemberProfile
	NextCursor string
}

// RoleCounts is the distribution of a community's members by role. Zeroes are
// meaningful (a community with no admins reports Admin: 0).
type RoleCounts struct {
	Owner     int64
	Admin     int64
	Moderator int64
	Member    int64
}

// Total is the sum across roles — an authoritative member count derived from
// the same GROUP BY, independent of the cached communities.member_count.
func (rc RoleCounts) Total() int64 { return rc.Owner + rc.Admin + rc.Moderator + rc.Member }

// Stats is the user-independent numeric projection of a community. Backs the
// Gateway aggregate detail (counters + role distribution). DiscussionCount is
// the OFFICIAL community content domain (Discussions) — never Posts.
type Stats struct {
	CommunityID     uuid.UUID
	MemberCount     int64
	ActiveNow       int64
	DiscussionCount int64
	RoleCounts      RoleCounts
}
