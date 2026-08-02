// Package pagination provides an opaque keyset cursor used by every
// list repo in this service.
//
// Encoding: base64url("<RFC3339Nano>|<uuid>"). Opaque to callers —
// the format is a private detail; callers MUST treat it as a blob.
// Keyset (created_at, id) provides total order even when timestamps
// collide, so pages don't drift under concurrent inserts.
package pagination

import (
	"encoding/base64"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
)

var ErrInvalidCursor = errors.New("pagination: invalid cursor")

// Encode produces an opaque cursor for the row identified by
// (createdAt, id). Returns "" for the empty/zero case so the repo can
// signal "no next page" trivially.
func Encode(createdAt time.Time, id uuid.UUID) string {
	if createdAt.IsZero() {
		return ""
	}
	raw := createdAt.UTC().Format(time.RFC3339Nano) + "|" + id.String()
	return base64.RawURLEncoding.EncodeToString([]byte(raw))
}

// Decode parses a cursor back to its components. Empty cursor is
// allowed and returns zero values + no error — repos treat it as
// "first page".
func Decode(cursor string) (time.Time, uuid.UUID, error) {
	if cursor == "" {
		return time.Time{}, uuid.Nil, nil
	}
	raw, err := base64.RawURLEncoding.DecodeString(cursor)
	if err != nil {
		return time.Time{}, uuid.Nil, fmt.Errorf("%w: %v", ErrInvalidCursor, err)
	}
	parts := strings.SplitN(string(raw), "|", 2)
	if len(parts) != 2 {
		return time.Time{}, uuid.Nil, ErrInvalidCursor
	}
	ts, err := time.Parse(time.RFC3339Nano, parts[0])
	if err != nil {
		return time.Time{}, uuid.Nil, fmt.Errorf("%w: ts: %v", ErrInvalidCursor, err)
	}
	id, err := uuid.Parse(parts[1])
	if err != nil {
		return time.Time{}, uuid.Nil, fmt.Errorf("%w: id: %v", ErrInvalidCursor, err)
	}
	return ts.UTC(), id, nil
}
