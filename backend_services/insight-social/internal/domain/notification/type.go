package notification

// Canonical enums for the Notification domain. Stored as their String() form in
// the `type`/`priority` columns; parsed back on read. Status is DERIVED from
// read_at (never stored) so there is a single source of truth for read state.

type Type int

const (
	TypeUnspecified Type = iota
	TypeCommunityJoin
	TypeDiscussionReply
	TypeMention
	TypeReaction
	TypeSystem
)

func (t Type) String() string {
	switch t {
	case TypeCommunityJoin:
		return "community_join"
	case TypeDiscussionReply:
		return "discussion_reply"
	case TypeMention:
		return "mention"
	case TypeReaction:
		return "reaction"
	case TypeSystem:
		return "system"
	default:
		return ""
	}
}

func ParseType(s string) Type {
	switch s {
	case "community_join":
		return TypeCommunityJoin
	case "discussion_reply":
		return TypeDiscussionReply
	case "mention":
		return TypeMention
	case "reaction":
		return TypeReaction
	case "system":
		return TypeSystem
	default:
		return TypeUnspecified
	}
}

func (t Type) Valid() bool { return t != TypeUnspecified && t.String() != "" }

type Priority int

const (
	PriorityUnspecified Priority = iota
	PriorityLow
	PriorityNormal
	PriorityHigh
)

func (p Priority) String() string {
	switch p {
	case PriorityLow:
		return "low"
	case PriorityHigh:
		return "high"
	default:
		return "normal" // unspecified persists as the safe default
	}
}

func ParsePriority(s string) Priority {
	switch s {
	case "low":
		return PriorityLow
	case "high":
		return PriorityHigh
	default:
		return PriorityNormal
	}
}

// Status is derived, never stored.
type Status int

const (
	StatusUnread Status = iota
	StatusRead
)

func (s Status) String() string {
	if s == StatusRead {
		return "read"
	}
	return "unread"
}
