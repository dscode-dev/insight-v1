package reaction

import "errors"

var (
	ErrDiscussionNotFound = errors.New("reaction: discussion not found")
	ErrUserNotFound       = errors.New("reaction: user not found")
)
