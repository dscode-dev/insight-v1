// DLQ operations — V1.1 poison-message policy: every dead-lettered
// entry (poison or max-deliveries) is inspectable and replayable.
// Replay re-XADDs the original payload onto the trend stream (so it
// re-enters the normal consumer path, decode included) and deletes the
// DLQ entry only after the re-add succeeds.
package redisstream

import (
	"context"
	"encoding/json"
	"fmt"

	goredis "github.com/redis/go-redis/v9"

	"github.com/konoha-labs/insight-nexus/internal/ports"
)

// DLQOps reads/replays the Nexus dead-letter stream. Constructed over
// the same client the consumer uses.
type DLQOps struct {
	client      *goredis.Client
	dlqStream   string
	trendStream string
}

func NewDLQOps(client *goredis.Client, dlqStream, trendStream string) *DLQOps {
	if dlqStream == "" {
		dlqStream = "insight:dlq:nexus"
	}
	if trendStream == "" {
		trendStream = "insight:stream:trends"
	}
	return &DLQOps{client: client, dlqStream: dlqStream, trendStream: trendStream}
}

// DLQOpsFromConsumer reuses the consumer's connection + config.
func DLQOpsFromConsumer(c *Consumer) *DLQOps {
	return NewDLQOps(c.client, c.cfg.Claimer.DLQStream, c.cfg.Stream)
}

func (d *DLQOps) entry(msg goredis.XMessage) ports.DLQEntry {
	e := ports.DLQEntry{ID: msg.ID, Kind: "max_deliveries"}
	if v, ok := msg.Values["source_entry_id"].(string); ok {
		e.SourceEntryID = v
	}
	if v, ok := msg.Values["kind"].(string); ok && v != "" {
		e.Kind = v
	}
	if v, ok := msg.Values["reason"].(string); ok {
		e.Reason = v
	}
	if v, ok := msg.Values["payload"].(string); ok {
		e.Payload = v
	}
	return e
}

// List returns the newest entries first, capped at limit.
func (d *DLQOps) List(ctx context.Context, limit int64) ([]ports.DLQEntry, error) {
	if limit <= 0 || limit > 500 {
		limit = 100
	}
	msgs, err := d.client.XRevRangeN(ctx, d.dlqStream, "+", "-", limit).Result()
	if err != nil {
		return nil, fmt.Errorf("dlq list: %w", err)
	}
	out := make([]ports.DLQEntry, 0, len(msgs))
	for _, m := range msgs {
		out = append(out, d.entry(m))
	}
	return out, nil
}

// Get returns one entry by DLQ stream id.
func (d *DLQOps) Get(ctx context.Context, id string) (ports.DLQEntry, error) {
	msgs, err := d.client.XRangeN(ctx, d.dlqStream, id, id, 1).Result()
	if err != nil {
		return ports.DLQEntry{}, fmt.Errorf("dlq get: %w", err)
	}
	if len(msgs) == 0 {
		return ports.DLQEntry{}, ErrDLQNotFound
	}
	return d.entry(msgs[0]), nil
}

// Replay re-enqueues the ORIGINAL trend payload onto the trend stream
// and removes the DLQ entry. The payload re-enters the standard
// consumer path — including decode — so replaying a still-broken
// entry dead-letters it again instead of crashing anything.
func (d *DLQOps) Replay(ctx context.Context, id string) error {
	e, err := d.Get(ctx, id)
	if err != nil {
		return err
	}
	var body struct {
		Payload string `json:"payload"`
	}
	if err := json.Unmarshal([]byte(e.Payload), &body); err != nil || body.Payload == "" {
		return fmt.Errorf("dlq replay: entry %s has no recoverable payload", id)
	}
	if err := d.client.XAdd(ctx, &goredis.XAddArgs{
		Stream: d.trendStream,
		Values: map[string]any{"payload": body.Payload, "replayed_from": id},
	}).Err(); err != nil {
		return fmt.Errorf("dlq replay xadd: %w", err)
	}
	if err := d.client.XDel(ctx, d.dlqStream, id).Err(); err != nil {
		// Replayed but not deleted: surfaced so the operator can XDEL
		// manually; replaying twice is safe (trend_id dedup downstream
		// via anti-spam cooldowns).
		return fmt.Errorf("dlq replay: re-added but delete failed: %w", err)
	}
	return nil
}

// Depth returns the DLQ stream length (served as a gauge + API field).
func (d *DLQOps) Depth(ctx context.Context) (int64, error) {
	return d.client.XLen(ctx, d.dlqStream).Result()
}

var ErrDLQNotFound = fmt.Errorf("dlq: entry not found")

var _ ports.TrendDLQ = (*DLQOps)(nil)
