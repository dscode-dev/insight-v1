package signal

import "errors"

var (
	ErrNotFound          = errors.New("signal: not found")
	ErrInvalidLabel      = errors.New("signal: invalid label")
	ErrInvalidBody       = errors.New("signal: invalid body")
	ErrInvalidConfidence = errors.New("signal: invalid confidence (must be 0..1)")
	ErrAuthorNotFound    = errors.New("signal: author not found")
	ErrMatchNotFound     = errors.New("signal: match not found")
	ErrPublish           = errors.New("signal: publish failed")
)
