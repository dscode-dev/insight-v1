package proxy

import (
	"fmt"
	"strconv"
	"strings"
)

// RolloutMode controls how a single endpoint splits traffic between
// the native Go handler and the legacy upstream during the
// Strangler migration window.
type RolloutMode int

const (
	// RolloutOff — 100% legacy upstream. The default at registration time;
	// keep here until the handler is built and validated.
	RolloutOff RolloutMode = iota

	// RolloutShadow — 100% legacy upstream serves the response, AND the Go
	// handler is invoked in a goroutine with the response discarded.
	// Used for response-shape validation before any real traffic
	// flips to Go.
	RolloutShadow

	// RolloutPercent — split between Go (percent%) and the legacy upstream
	// (100 - percent%). Percentage is stored on the Flag struct.
	RolloutPercent
)

// Flag is the per-endpoint rollout decision. Construct via ParseFlag.
type Flag struct {
	Mode    RolloutMode
	Percent int // 0..100, only meaningful when Mode == RolloutPercent
}

// String renders the flag in env-format ("off" / "shadow" / "75").
func (f Flag) String() string {
	switch f.Mode {
	case RolloutShadow:
		return "shadow"
	case RolloutPercent:
		return strconv.Itoa(f.Percent)
	default:
		return "off"
	}
}

// ParseFlag interprets the env value:
//
//	""       → off  (the default for unset)
//	"off"    → off
//	"false"  → off
//	"shadow" → shadow
//	"0"      → off  (alias)
//	"100"    → percent=100  (full go cutover)
//	"<N>"    → percent=N for 0 < N <= 100
//
// Anything else falls back to off — we never want a typo accidentally
// promoting an endpoint to Go before it's ready.
func ParseFlag(raw string) Flag {
	v := strings.TrimSpace(strings.ToLower(raw))
	switch v {
	case "", "off", "false", "0":
		return Flag{Mode: RolloutOff}
	case "shadow":
		return Flag{Mode: RolloutShadow}
	}
	if n, err := strconv.Atoi(v); err == nil && n > 0 && n <= 100 {
		return Flag{Mode: RolloutPercent, Percent: n}
	}
	return Flag{Mode: RolloutOff}
}

// MustParseFlag is ParseFlag that panics on invalid input. Use only
// in tests; production uses ParseFlag which is forgiving by design.
func MustParseFlag(raw string) Flag {
	f := ParseFlag(raw)
	// Round-trip check: if the round-trip doesn't match, the input was
	// invalid. Skip for "off" since multiple inputs alias to it.
	if !strings.EqualFold(strings.TrimSpace(raw), "") &&
		!strings.EqualFold(strings.TrimSpace(raw), "off") &&
		!strings.EqualFold(strings.TrimSpace(raw), "false") &&
		!strings.EqualFold(strings.TrimSpace(raw), "0") &&
		f.Mode == RolloutOff {
		panic(fmt.Sprintf("invalid rollout flag: %q", raw))
	}
	return f
}
