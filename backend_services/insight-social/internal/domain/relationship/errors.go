package relationship

import "errors"

var (
	ErrNotFound      = errors.New("relationship: not found")
	ErrAlreadyExists = errors.New("relationship: already exists")
	ErrSelfTarget    = errors.New("relationship: actor cannot target self")
	ErrInvalidKind   = errors.New("relationship: invalid kind")
	ErrUserNotFound  = errors.New("relationship: user not found")
)
