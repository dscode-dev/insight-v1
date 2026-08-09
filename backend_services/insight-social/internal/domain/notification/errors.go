package notification

import "errors"

var (
	ErrNotFound      = errors.New("notification: not found")
	ErrInvalidType   = errors.New("notification: invalid type")
	ErrInvalidUser   = errors.New("notification: invalid user id")
	ErrEmptyTitle    = errors.New("notification: title is required")
	ErrEmptyDedupKey = errors.New("notification: dedup_key is required")
	ErrInvalidCursor = errors.New("notification: invalid cursor")
)
