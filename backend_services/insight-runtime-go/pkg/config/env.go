// Package config wraps env-driven configuration parsing.
//
// Insight services follow 12-factor: config lives in env, populated by
// the K8s ConfigMap + Secret in production. Each service defines its
// own `Settings` struct and calls Parse, which fails fast at startup
// when required values are missing or malformed.
package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
)

// MustString returns the env value or panics — only acceptable at
// startup, never inside request handlers.
func MustString(key string) string {
	v := os.Getenv(key)
	if v == "" {
		panic(fmt.Sprintf("config: required env %q not set", key))
	}
	return v
}

// String returns the env value or fallback.
func String(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// Int returns the env value parsed as int, or fallback when unset.
// Malformed values are a startup error — return them so the caller
// can decide whether to panic.
func Int(key string, fallback int) (int, error) {
	raw := os.Getenv(key)
	if raw == "" {
		return fallback, nil
	}
	v, err := strconv.Atoi(raw)
	if err != nil {
		return 0, fmt.Errorf("config: env %q must be int, got %q: %w", key, raw, err)
	}
	return v, nil
}

// Bool parses common true-ish strings. Falls back when unset.
func Bool(key string, fallback bool) bool {
	raw := strings.ToLower(os.Getenv(key))
	switch raw {
	case "":
		return fallback
	case "1", "t", "true", "yes", "on":
		return true
	case "0", "f", "false", "no", "off":
		return false
	default:
		return fallback
	}
}

// Float returns the env value parsed as float64, or fallback when unset.
func Float(key string, fallback float64) (float64, error) {
	raw := os.Getenv(key)
	if raw == "" {
		return fallback, nil
	}
	v, err := strconv.ParseFloat(raw, 64)
	if err != nil {
		return 0, fmt.Errorf("config: env %q must be float, got %q: %w", key, raw, err)
	}
	return v, nil
}
