package sentiment

import "errors"

var (
	ErrNotFound = errors.New("sentiment: no snapshot for match")
)
