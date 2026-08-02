package discussionrepo

import (
	"encoding/base64"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/konoha-labs/insight-social/internal/infrastructure/postgres/pagination"
)

// message cursor: base64url("<RFC3339Nano>|<bigint>").
//
// Separate codec from pagination.Encode/Decode because messages use a
// BIGSERIAL primary key, not a UUID. Kept private — only ListMessages
// produces and consumes it.

func encodeMessageCursor(createdAt time.Time, id int64) string {
	if createdAt.IsZero() {
		return ""
	}
	raw := createdAt.UTC().Format(time.RFC3339Nano) + "|" + strconv.FormatInt(id, 10)
	return base64.RawURLEncoding.EncodeToString([]byte(raw))
}

func decodeMessageCursor(cursor string) (time.Time, int64, error) {
	if cursor == "" {
		return time.Time{}, 0, nil
	}
	raw, err := base64.RawURLEncoding.DecodeString(cursor)
	if err != nil {
		return time.Time{}, 0, fmt.Errorf("%w: %v", pagination.ErrInvalidCursor, err)
	}
	parts := strings.SplitN(string(raw), "|", 2)
	if len(parts) != 2 {
		return time.Time{}, 0, errors.Join(pagination.ErrInvalidCursor, errors.New("split"))
	}
	ts, err := time.Parse(time.RFC3339Nano, parts[0])
	if err != nil {
		return time.Time{}, 0, fmt.Errorf("%w: ts: %v", pagination.ErrInvalidCursor, err)
	}
	id, err := strconv.ParseInt(parts[1], 10, 64)
	if err != nil {
		return time.Time{}, 0, fmt.Errorf("%w: id: %v", pagination.ErrInvalidCursor, err)
	}
	return ts.UTC(), id, nil
}
