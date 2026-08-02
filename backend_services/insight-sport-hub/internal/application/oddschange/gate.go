// Package oddschange — Sprint 6.1 odds change-detection publish gate.
//
// Odds drift continuously; most ticks move a price by a fraction of a
// percent. Publishing every one floods the odds stream and Atlas with
// noise. This gate compares an about-to-publish odds snapshot against
// the last PUBLISHED snapshot for the same (match, bookmaker, market)
// lane and suppresses the publish when no price moved by at least the
// configured threshold.
//
// Scope (per the Sprint 6.1 spec): this affects PUBLICATION only. The
// Hub still persists the raw + canonical event upstream (audit), and a
// new outcome / a vanished outcome / the first-ever snapshot always
// publish — so the published timeline stays logically correct, just
// denoised.
//
// outcomes[] is the source of truth for the comparison; the h2h
// home/draw/away convenience fields are folded in when present.
package oddschange

import (
	"context"
	"fmt"
	"math"
	"time"

	"github.com/konoha-labs/insight-sports-hub/internal/domain/event"
)

// LastOddsStore persists the last-published price vector per lane key.
// Redis-backed in production; in-memory for tests / single instance.
type LastOddsStore interface {
	Get(ctx context.Context, key string) (map[string]float64, bool, error)
	Put(ctx context.Context, key string, prices map[string]float64, ttl time.Duration) error
}

// Gate decides whether an odds canonical event is worth publishing.
type Gate struct {
	thresholdPercent float64
	store            LastOddsStore
	ttl              time.Duration
}

// NewGate builds the gate. A non-positive threshold means "publish
// everything" (the gate becomes a no-op) — convenient for disabling
// denoising via config without removing the wiring.
func NewGate(thresholdPercent float64, store LastOddsStore, ttl time.Duration) *Gate {
	if ttl <= 0 {
		ttl = 24 * time.Hour
	}
	return &Gate{thresholdPercent: thresholdPercent, store: store, ttl: ttl}
}

// ShouldPublish reports whether the event carries a meaningful change.
// Non-odds events always pass (the gate only judges match.odds). On any
// store error it fails OPEN (publishes) — losing a snapshot is worse
// than emitting an extra one.
func (g *Gate) ShouldPublish(ctx context.Context, c *event.CanonicalSportsEvent) (bool, error) {
	if c.EventType() != "match.odds" {
		return true, nil
	}
	if g.thresholdPercent <= 0 {
		return true, nil
	}

	payload := c.Payload()
	key := laneKey(payload)
	current := extractPrices(payload)
	if len(current) == 0 {
		// Nothing numeric to compare — let it through.
		return true, nil
	}

	last, found, err := g.store.Get(ctx, key)
	if err != nil {
		return true, fmt.Errorf("oddschange: store get: %w", err)
	}

	publish := !found || meaningfulChange(last, current, g.thresholdPercent)
	if publish {
		if perr := g.store.Put(ctx, key, current, g.ttl); perr != nil {
			// Persisting the new baseline failed; still publish but
			// surface the error so the caller can log it.
			return true, fmt.Errorf("oddschange: store put: %w", perr)
		}
	}
	return publish, nil
}

// laneKey identifies the (match, bookmaker, market) lane. Falls back to
// the canonical ids when payload fields are missing so distinct lanes
// never collide.
func laneKey(payload map[string]any) string {
	return fmt.Sprintf("oddschange:%s:%s:%s",
		str(payload["match_id"]), str(payload["bookmaker"]), str(payload["market"]))
}

// extractPrices flattens every comparable numeric price into a flat
// map. outcomes[] is authoritative; home/draw/away are added when
// present (h2h convenience).
func extractPrices(payload map[string]any) map[string]float64 {
	out := map[string]float64{}
	if raw, ok := payload["outcomes"]; ok {
		for _, item := range asSlice(raw) {
			m, ok := item.(map[string]any)
			if !ok {
				continue
			}
			name := str(m["name"])
			if name == "" {
				continue
			}
			if price, ok := toFloat(m["price"]); ok {
				keyName := "o:" + name
				if pt, hasPt := toFloat(m["point"]); hasPt {
					keyName = fmt.Sprintf("o:%s@%g", name, pt)
				}
				out[keyName] = price
			}
		}
	}
	for _, f := range []string{"home", "draw", "away"} {
		if price, ok := toFloat(payload[f]); ok {
			out[f] = price
		}
	}
	return out
}

// meaningfulChange reports whether current differs from last by at
// least thresholdPercent on any shared key, OR the key set changed
// (a new/removed outcome is always meaningful).
func meaningfulChange(last, current map[string]float64, thresholdPercent float64) bool {
	if len(last) != len(current) {
		return true
	}
	for k, cur := range current {
		prev, ok := last[k]
		if !ok {
			return true // new outcome
		}
		if prev == 0 {
			if cur != 0 {
				return true
			}
			continue
		}
		pct := math.Abs(cur-prev) / math.Abs(prev) * 100.0
		if pct >= thresholdPercent {
			return true
		}
	}
	return false
}

// ---- small coercion helpers ----

func str(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}

func asSlice(v any) []any {
	switch s := v.(type) {
	case []any:
		return s
	case []map[string]any:
		out := make([]any, len(s))
		for i := range s {
			out[i] = s[i]
		}
		return out
	default:
		return nil
	}
}

func toFloat(v any) (float64, bool) {
	switch n := v.(type) {
	case float64:
		return n, true
	case float32:
		return float64(n), true
	case int:
		return float64(n), true
	case int64:
		return float64(n), true
	default:
		return 0, false
	}
}
