package discussion

import "errors"

var (
	ErrNotFound          = errors.New("discussion: not found")
	ErrCommunityNotFound = errors.New("discussion: community not found")
	ErrInvalidTitle      = errors.New("discussion: invalid title")
	ErrInvalidBody       = errors.New("discussion: invalid body")
)
