package realtime

import (
	"context"
	"encoding/json"
	"strconv"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/redis/go-redis/v9"
	"github.com/rs/zerolog"
)

// BrokerConfig — tuning + dependencies.
type BrokerConfig struct {
	Redis              *redis.Client
	StreamKeys         []string // insight:stream:derived:p0..pN
	BlockMs            int      // XREAD block ms (default 2000)
	SubscriberQueueMax int      // per-sub channel buffer (default 1000)
	StartFrom          string   // "$" = only new entries; "0" = full history
}

// Broker fans Redis derived-stream events out to subscribed SSE clients.
//
// One goroutine reads XREAD across all configured stream keys and
// dispatches matching events into each subscriber's channel via a
// non-blocking send. Slow consumers drop events rather than blocking
// the broker — the subscriber's eventsDropped counter records the
// loss so it surfaces in /metrics.
type Broker struct {
	cfg    BrokerConfig
	mu     sync.RWMutex
	subs   map[string]*Subscription
	cursor map[string]string // streamKey → last-seen id

	// metrics
	subscribersGauge   prometheus.Gauge
	eventsDispatched   prometheus.Counter
	eventsDroppedTotal *prometheus.CounterVec
}

// Subscription is the handle returned by Subscribe. The SSE handler
// reads from Events, calling Close when the client disconnects.
type Subscription struct {
	ID      string
	Filters SubscriptionFilters
	Events  chan *Event

	closeOnce sync.Once
	closed    chan struct{}
}

// Close signals the broker to stop dispatching to this subscription
// and drops references. Safe to call from any goroutine; idempotent.
func (s *Subscription) Close() {
	s.closeOnce.Do(func() { close(s.closed) })
}

// Done returns a channel that is closed when Close() has been called.
// Mirrors context.Context.Done() — lets the broker react to a
// subscriber's exit without holding a reference forever.
func (s *Subscription) Done() <-chan struct{} { return s.closed }

func NewBroker(cfg BrokerConfig, reg prometheus.Registerer) *Broker {
	if cfg.BlockMs == 0 {
		cfg.BlockMs = 2000
	}
	if cfg.SubscriberQueueMax == 0 {
		cfg.SubscriberQueueMax = 1000
	}
	if cfg.StartFrom == "" {
		cfg.StartFrom = "$" // only events arriving after subscribe
	}

	b := &Broker{
		cfg:    cfg,
		subs:   make(map[string]*Subscription),
		cursor: make(map[string]string),

		subscribersGauge: prometheus.NewGauge(prometheus.GaugeOpts{
			Name: "gateway_realtime_subscribers",
			Help: "Number of currently connected SSE subscribers.",
		}),
		eventsDispatched: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "gateway_realtime_events_dispatched_total",
			Help: "Total events dispatched across all subscribers (post-filter).",
		}),
		eventsDroppedTotal: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "gateway_realtime_events_dropped_total",
			Help: "Events dropped because a subscriber's queue was full.",
		}, []string{"reason"}),
	}

	if reg != nil {
		reg.MustRegister(b.subscribersGauge, b.eventsDispatched, b.eventsDroppedTotal)
	}

	// Initialise cursor: read only fresh entries (after Start time).
	for _, k := range cfg.StreamKeys {
		b.cursor[k] = cfg.StartFrom
	}
	return b
}

// Subscribe registers a new subscription and returns it. Caller MUST
// call Subscription.Close() when finished (typically via `defer`).
func (b *Broker) Subscribe(filters SubscriptionFilters) *Subscription {
	sub := &Subscription{
		ID:      uuid.NewString(),
		Filters: filters,
		Events:  make(chan *Event, b.cfg.SubscriberQueueMax),
		closed:  make(chan struct{}),
	}

	b.mu.Lock()
	b.subs[sub.ID] = sub
	b.mu.Unlock()
	b.subscribersGauge.Inc()

	// Reaper — when the subscriber's Done channel fires, drop it from
	// the map. Done independently of the loop's tick because slow
	// subscribers shouldn't delay other subscribers' tear-down.
	go func() {
		<-sub.Done()
		b.mu.Lock()
		delete(b.subs, sub.ID)
		b.mu.Unlock()
		b.subscribersGauge.Dec()
		close(sub.Events)
	}()
	return sub
}

// Run blocks until ctx is cancelled. Spawns the XREAD loop and
// dispatches every matching event to each subscriber.
func (b *Broker) Run(ctx context.Context) {
	logger := zerolog.Ctx(ctx).With().Str("component", "realtime_broker").Logger()

	for {
		select {
		case <-ctx.Done():
			logger.Info().Msg("broker_shutdown")
			return
		default:
		}

		// Build XREAD args. Redis expects all stream keys followed by
		// the matching last-id-per-key list.
		streams := make([]string, 0, len(b.cfg.StreamKeys)*2)
		streams = append(streams, b.cfg.StreamKeys...)
		for _, k := range b.cfg.StreamKeys {
			streams = append(streams, b.cursor[k])
		}

		res, err := b.cfg.Redis.XRead(ctx, &redis.XReadArgs{
			Streams: streams,
			Block:   time.Duration(b.cfg.BlockMs) * time.Millisecond,
			Count:   64,
		}).Result()
		if err != nil {
			if err == redis.Nil { // block timeout, no messages
				continue
			}
			// Likely transient (connection drop / context cancel mid-call).
			// Log + brief backoff so we don't hot-spin on persistent errors.
			logger.Warn().Err(err).Msg("xread_error")
			select {
			case <-ctx.Done():
				return
			case <-time.After(500 * time.Millisecond):
			}
			continue
		}

		for _, stream := range res {
			for _, msg := range stream.Messages {
				b.cursor[stream.Stream] = msg.ID
				ev, err := decodeXMessage(stream.Stream, msg)
				if err != nil {
					logger.Warn().Err(err).Str("stream", stream.Stream).Str("id", msg.ID).Msg("decode_failed")
					continue
				}
				b.dispatch(ev)
			}
		}
	}
}

// dispatch fans an event out to every matching subscriber. Iteration
// is read-locked so subscribe/unsubscribe doesn't block the broker.
func (b *Broker) dispatch(ev *Event) {
	b.mu.RLock()
	defer b.mu.RUnlock()

	for _, sub := range b.subs {
		if !sub.Filters.Match(ev) {
			continue
		}
		select {
		case sub.Events <- ev:
			b.eventsDispatched.Inc()
		default:
			// Non-blocking send — slow consumer. Drop, count it, move on.
			// The alternative (blocking) would let one stuck client wedge
			// the entire broker.
			b.eventsDroppedTotal.WithLabelValues("queue_full").Inc()
		}
	}
}

// decodeXMessage extracts the Event shape from a Redis stream message.
// The encoding is Atlas's DerivedPublisher envelope (see
// insight-atlas/atlas/streaming/publisher.py) — a flat hash with
// `payload` holding the JSON-encoded body.
func decodeXMessage(streamKey string, msg redis.XMessage) (*Event, error) {
	ev := &Event{
		EventID:    stringValue(msg.Values, "event_id"),
		MatchID:    stringValue(msg.Values, "match_id"),
		EventType:  stringValue(msg.Values, "event_type"),
		RegionCode: stringValue(msg.Values, "region_code"),
		TsIngest:   stringValue(msg.Values, "ts_ingest"),
		Stream:     streamKey,
	}
	// payload field holds opaque JSON. We re-emit it verbatim.
	if raw, ok := msg.Values["payload"]; ok {
		switch v := raw.(type) {
		case string:
			ev.Payload = []byte(v)
		case []byte:
			ev.Payload = v
		default:
			// Defensive — Redis go-redis library normally returns string.
			b, _ := json.Marshal(v)
			ev.Payload = b
		}
	}
	if ev.EventID == "" {
		// Fall back to the XMessage id when the publisher omitted one.
		ev.EventID = msg.ID
	}
	return ev, nil
}

func stringValue(m map[string]interface{}, key string) string {
	v, ok := m[key]
	if !ok {
		return ""
	}
	switch x := v.(type) {
	case string:
		return x
	case []byte:
		return string(x)
	case int64:
		return strconv.FormatInt(x, 10)
	default:
		return ""
	}
}
