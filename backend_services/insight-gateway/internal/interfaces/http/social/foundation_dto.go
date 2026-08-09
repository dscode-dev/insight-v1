// Social Foundation DTOs — Sprint 2.5 Part 11.
//
// The STABLE mobile wire contract. Gateway owns the evolution of
// these shapes: fields are additive-only (backward compatible), JSON
// keys are snake_case, timestamps are RFC3339 UTC, and internal
// Social entities never leak (every shape here is hand-mapped from
// the gRPC types).
package social

import (
	"time"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
)

// PostDTO — one post, any author type (user | agent | admin).
type PostDTO struct {
	ID           string            `json:"id"`
	AuthorID     string            `json:"author_id"`
	AuthorType   string            `json:"author_type"`
	Content      string            `json:"content"`
	Metadata     map[string]string `json:"metadata,omitempty"`
	Visibility   string            `json:"visibility"`
	CreatedAt    time.Time         `json:"created_at"`
	LikeCount    int64             `json:"like_count"`
	CommentCount int64             `json:"comment_count"`
	ShareCount   int64             `json:"share_count"`

	// The competition this post belongs to, when it belongs to one. Omitted
	// entirely for platform-wide posts — `omitempty` so the client can test
	// presence rather than compare against an empty string.
	//
	// Slug and name travel only alongside the id (Social sends them together
	// or not at all): a chip rendered from a name with no id would filter to
	// nothing when tapped.
	CompetitionID   string `json:"competition_id,omitempty"`
	CompetitionSlug string `json:"competition_slug,omitempty"`
	CompetitionName string `json:"competition_name,omitempty"`
}

// FeedItemDTO — a post plus denormalized author display data, ready
// to render without fan-out.
type FeedItemDTO struct {
	Post              PostDTO `json:"post"`
	AuthorName        string  `json:"author_name"`
	AuthorAvatar      string  `json:"author_avatar,omitempty"`
	FromFollowedAgent bool    `json:"from_followed_agent"`
	Sponsored         bool    `json:"sponsored"`
	// LikedByMe — viewer's like state, so clients paint the right heart
	// without a second round-trip.
	LikedByMe bool `json:"liked_by_me"`
}

// FeedPageDTO — cursor-paged feed slice.
type FeedPageDTO struct {
	Items      []FeedItemDTO `json:"items"`
	NextCursor string        `json:"next_cursor,omitempty"`
}

// AgentDTO — platform agent profile. `specialty` is the agent bio's
// product name (forward-compatible alias kept separate from bio).
type AgentDTO struct {
	ID        string    `json:"id"`
	Slug      string    `json:"slug"`
	Name      string    `json:"name"`
	Avatar    string    `json:"avatar,omitempty"`
	Bio       string    `json:"bio,omitempty"`
	Specialty string    `json:"specialty,omitempty"`
	Active    bool      `json:"active"`
	Verified  bool      `json:"verified"`
	CreatedAt time.Time `json:"created_at"`
}

// UserDTO — public profile of a user (no private fields: phone/email
// and credentials live in the Gateway auth DB and never cross here).
type UserDTO struct {
	ID          string `json:"id"`
	Username    string `json:"username"`
	DisplayName string `json:"display_name"`
	Initials    string `json:"initials"`
	AccentColor string `json:"accent_color"`
	Reputation  int32  `json:"reputation"`
	AvatarURL   string `json:"avatar_url,omitempty"`
}

// CommentDTO — comment or reply (depth 2 max, enforced by Social).
type CommentDTO struct {
	ID         string    `json:"id"`
	PostID     string    `json:"post_id"`
	ParentID   string    `json:"parent_id,omitempty"`
	AuthorID   string    `json:"author_id"`
	AuthorType string    `json:"author_type"`
	Content    string    `json:"content"`
	Depth      int32     `json:"depth"`
	CreatedAt  time.Time `json:"created_at"`
}

// CommentPageDTO — cursor-paged comments.
type CommentPageDTO struct {
	Comments   []CommentDTO `json:"comments"`
	NextCursor string       `json:"next_cursor,omitempty"`
}

// PostReactionDTO — the like state echo returned by like/unlike, so
// the mobile client can reconcile optimistic updates. (ReactionDTO is
// taken by the legacy discussion-hearts surface in dto.go.)
type PostReactionDTO struct {
	PostID string `json:"post_id"`
	Liked  bool   `json:"liked"`
}

// RelationshipDTO — follow/mute state echo.
type RelationshipDTO struct {
	TargetID string `json:"target_id"`
	Followed bool   `json:"followed"`
	Muted    bool   `json:"muted"`
}

// FeedUpdatesDTO — Part 10 polling response. The shape is transport-
// agnostic on purpose: an SSE/WebSocket push can deliver the exact
// same body later without endpoint redesign.
type FeedUpdatesDTO struct {
	HasUpdates bool  `json:"has_updates"`
	NewPosts   int64 `json:"new_posts"`
}

// ---- gRPC → DTO mapping -----------------------------------------------------

func authorTypeString(t socialv1.AuthorType) string {
	switch t {
	case socialv1.AuthorType_AUTHOR_TYPE_AGENT:
		return "agent"
	case socialv1.AuthorType_AUTHOR_TYPE_ADMIN:
		return "admin"
	default:
		return "user"
	}
}

func visibilityString(v socialv1.PostVisibility) string {
	switch v {
	case socialv1.PostVisibility_POST_VISIBILITY_COMPETITION:
		return "competition"
	case socialv1.PostVisibility_POST_VISIBILITY_PRIVATE:
		return "private"
	default:
		return "public"
	}
}

func visibilityFromString(s string) socialv1.PostVisibility {
	switch s {
	case "competition":
		return socialv1.PostVisibility_POST_VISIBILITY_COMPETITION
	case "private":
		return socialv1.PostVisibility_POST_VISIBILITY_PRIVATE
	default:
		return socialv1.PostVisibility_POST_VISIBILITY_PUBLIC
	}
}

func postDTO(p *socialv1.Post) PostDTO {
	if p == nil {
		return PostDTO{}
	}
	return PostDTO{
		ID:           p.GetId(),
		AuthorID:     p.GetAuthorId(),
		AuthorType:   authorTypeString(p.GetAuthorType()),
		Content:      p.GetContent(),
		Metadata:     p.GetMetadata(),
		Visibility:   visibilityString(p.GetVisibility()),
		CreatedAt:    p.GetCreatedAt().AsTime(),
		LikeCount:    p.GetLikeCount(),
		CommentCount: p.GetCommentCount(),
		ShareCount:   p.GetShareCount(),

		CompetitionID:   p.GetCompetitionId(),
		CompetitionSlug: p.GetCompetitionSlug(),
		CompetitionName: p.GetCompetitionName(),
	}
}

func feedItemDTO(item *socialv1.FeedItem) FeedItemDTO {
	return FeedItemDTO{
		Post:              postDTO(item.GetPost()),
		AuthorName:        item.GetAuthorName(),
		AuthorAvatar:      item.GetAuthorAvatar(),
		FromFollowedAgent: item.GetFromFollowedAgent(),
		Sponsored:         item.GetSponsored(),
		LikedByMe:         item.GetLikedByMe(),
	}
}

func feedPageDTO(resp *socialv1.FeedResponse) FeedPageDTO {
	items := make([]FeedItemDTO, 0, len(resp.GetItems()))
	for _, item := range resp.GetItems() {
		items = append(items, feedItemDTO(item))
	}
	return FeedPageDTO{Items: items, NextCursor: resp.GetNextCursor()}
}

func userDTO(u *socialv1.User) UserDTO {
	return UserDTO{
		ID:          u.GetId(),
		Username:    u.GetUsername(),
		DisplayName: u.GetDisplayName(),
		Initials:    u.GetInitials(),
		AccentColor: u.GetAccentColor(),
		Reputation:  u.GetReputation(),
		AvatarURL:   u.GetAvatarUrl(),
	}
}

func agentDTO(a *socialv1.AgentProfile) AgentDTO {
	return AgentDTO{
		ID:        a.GetId(),
		Slug:      a.GetSlug(),
		Name:      a.GetName(),
		Avatar:    a.GetAvatar(),
		Bio:       a.GetBio(),
		Specialty: a.GetBio(), // V1: specialty mirrors bio; diverges later
		Active:    a.GetActive(),
		Verified:  a.GetVerified(),
		CreatedAt: a.GetCreatedAt().AsTime(),
	}
}

func commentDTO(c *socialv1.Comment) CommentDTO {
	return CommentDTO{
		ID:         c.GetId(),
		PostID:     c.GetPostId(),
		ParentID:   c.GetParentId(),
		AuthorID:   c.GetAuthorId(),
		AuthorType: authorTypeString(c.GetAuthorType()),
		Content:    c.GetContent(),
		Depth:      c.GetDepth(),
		CreatedAt:  c.GetCreatedAt().AsTime(),
	}
}
