package community

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"
)

// MembersCursor encodes the keyset of the last row of a members page. The
// members listing orders by (role priority ASC, joined_at ASC, user_id ASC) —
// a stable total order — so the cursor carries exactly those three keys.
//
// Kept as a dedicated codec (not the shared pagination.Encode, which is
// (timestamp, uuid) only) because members pagination needs the role-priority
// as the leading sort key.
type MembersCursor struct {
	P int       `json:"p"` // role priority (0=owner … 3=member)
	J time.Time `json:"j"` // joined_at
	U uuid.UUID `json:"u"` // user_id (final tiebreak)
}

// EncodeMembersCursor produces the opaque cursor string for the last row.
func EncodeMembersCursor(role Role, joinedAt time.Time, userID uuid.UUID) string {
	b, _ := json.Marshal(MembersCursor{P: role.Priority(), J: joinedAt.UTC(), U: userID})
	return base64.RawURLEncoding.EncodeToString(b)
}

// DecodeMembersCursor parses an opaque members cursor. Empty string => zero
// cursor (first page). Malformed => ErrInvalidMembersCursor.
func DecodeMembersCursor(s string) (*MembersCursor, error) {
	if s == "" {
		return nil, nil
	}
	raw, err := base64.RawURLEncoding.DecodeString(s)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrInvalidMembersCursor, err)
	}
	var c MembersCursor
	if err := json.Unmarshal(raw, &c); err != nil {
		return nil, fmt.Errorf("%w: %v", ErrInvalidMembersCursor, err)
	}
	if c.P < 0 || c.P > 3 {
		return nil, fmt.Errorf("%w: priority %d out of range", ErrInvalidMembersCursor, c.P)
	}
	return &c, nil
}
