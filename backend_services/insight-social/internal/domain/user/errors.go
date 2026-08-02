package user

import "errors"

// Domain-level errors. The interface layer maps these to gRPC status
// codes; the infrastructure layer raises ErrNotFound / ErrUsernameTaken
// when pgx returns the corresponding row-level signals.
var (
	ErrNotFound           = errors.New("user: not found")
	ErrUsernameTaken      = errors.New("user: username already taken")
	ErrInvalidUsername    = errors.New("user: invalid username")
	ErrInvalidDisplayName = errors.New("user: invalid display name")
	ErrInvalidAccentColor = errors.New("user: invalid accent color")
	ErrInvalidAvatarURL   = errors.New("user: invalid avatar URL") // Sprint C
)
