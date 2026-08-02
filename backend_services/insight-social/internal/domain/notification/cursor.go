package notification

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"
)

// Cursor is the keyset of the last row of a page: (created_at, id) DESC. Opaque
// at the app/interface layers. No offset anywhere.
type Cursor struct {
	C time.Time `json:"c"`
	I uuid.UUID `json:"i"`
}

func EncodeCursor(createdAt time.Time, id uuid.UUID) string {
	b, _ := json.Marshal(Cursor{C: createdAt.UTC(), I: id})
	return base64.RawURLEncoding.EncodeToString(b)
}

// DecodeCursor parses an opaque cursor. Empty ⇒ nil (first page). Malformed ⇒
// ErrInvalidCursor.
func DecodeCursor(s string) (*Cursor, error) {
	if s == "" {
		return nil, nil
	}
	raw, err := base64.RawURLEncoding.DecodeString(s)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrInvalidCursor, err)
	}
	var c Cursor
	if err := json.Unmarshal(raw, &c); err != nil {
		return nil, fmt.Errorf("%w: %v", ErrInvalidCursor, err)
	}
	return &c, nil
}
