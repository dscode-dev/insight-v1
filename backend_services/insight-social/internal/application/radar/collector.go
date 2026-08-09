// Package radar polls the registered sources and stores what they return.
//
// The registry is generic by instruction — api-key, names, configs, any
// provider — so the collector cannot contain a single provider's shape. What
// it contains instead is a small mapping language, stored per source in
// `config`, that says where the items are in the response and which field of
// each item means what:
//
//	{
//	  "path":       "/fixtures?live=all",
//	  "auth":       {"in": "header", "name": "x-apisports-key"},
//	  "items_path": "response",
//	  "fields": {
//	    "external_id": "fixture.id",
//	    "title":       "teams.home.name",
//	    "summary":     "league.name",
//	    "occurred_at": "fixture.date"
//	  }
//	}
//
// WHY A MAPPING AND NOT A PLUGIN PER PROVIDER. A plugin per provider means a
// deploy to add a subscription, which defeats the point of registering sources
// from the console. The mapping covers the shape every JSON API shares — a
// list of objects with fields at known paths — and a provider that does not
// fit is registered as `other` and handled deliberately, rather than every
// provider needing code.
//
// FAILURE IS RECORDED, NEVER FATAL. One source returning 500 must not stop the
// others, and the reason has to survive: `last_error` is what an operator
// reads when Radar is empty and nobody knows why.
package radar

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

type Collector struct {
	pool   *pgxpool.Pool
	client *http.Client
	// How often to LOOK for due sources. Not how often a source is polled —
	// that is each source's own poll_seconds. A tick that finds nothing due
	// costs one indexed query.
	tick time.Duration
}

func NewCollector(pool *pgxpool.Pool) *Collector {
	return &Collector{
		pool: pool,
		client: &http.Client{
			// A provider that hangs must not hold a slot forever; the next
			// tick will try again.
			Timeout: 20 * time.Second,
		},
		tick: 30 * time.Second,
	}
}

// Run blocks until ctx is cancelled.
func (c *Collector) Run(ctx context.Context) {
	ticker := time.NewTicker(c.tick)
	defer ticker.Stop()
	slog.Info("radar_collector_started", "tick_seconds", c.tick.Seconds())

	for {
		select {
		case <-ctx.Done():
			slog.Info("radar_collector_stopped")
			return
		case <-ticker.C:
			c.pollDue(ctx)
		}
	}
}

type dueSource struct {
	ID      string
	Slug    string
	Kind    string
	BaseURL string
	APIKey  *string
	Config  []byte
}

// A source is due when it has never been attempted, or when its interval has
// elapsed since the last attempt — success or failure alike. Using only
// last_success_at would make a permanently failing source retry on every tick.
const dueQuery = `
SELECT id::text, slug, kind, base_url, api_key, config
  FROM radar_sources
 WHERE active
   AND (
     (last_success_at IS NULL AND last_error_at IS NULL)
     OR GREATEST(COALESCE(last_success_at, 'epoch'::timestamptz),
                 COALESCE(last_error_at,   'epoch'::timestamptz))
        < NOW() - make_interval(secs => poll_seconds)
   )
 ORDER BY GREATEST(COALESCE(last_success_at, 'epoch'::timestamptz),
                   COALESCE(last_error_at,   'epoch'::timestamptz)) ASC
 LIMIT 10`

func (c *Collector) pollDue(ctx context.Context) {
	rows, err := c.pool.Query(ctx, dueQuery)
	if err != nil {
		slog.Error("radar_due_query_failed", "error", err.Error())
		return
	}
	var due []dueSource
	for rows.Next() {
		var s dueSource
		if err := rows.Scan(&s.ID, &s.Slug, &s.Kind, &s.BaseURL, &s.APIKey, &s.Config); err != nil {
			slog.Error("radar_due_scan_failed", "error", err.Error())
			continue
		}
		due = append(due, s)
	}
	rows.Close()

	// Collected before fetching: holding rows open across network calls would
	// keep a pool connection for the duration of every provider's latency.
	for _, source := range due {
		c.collect(ctx, source)
	}
}

func (c *Collector) collect(ctx context.Context, s dueSource) {
	stored, err := c.fetchAndStore(ctx, s)
	if err != nil {
		// Truncated: a provider that returns an HTML error page would
		// otherwise put the whole page in a column an operator reads.
		message := err.Error()
		if len(message) > 500 {
			message = message[:500]
		}
		if _, uerr := c.pool.Exec(ctx,
			`UPDATE radar_sources SET last_error_at = NOW(), last_error = $2 WHERE id = $1::uuid`,
			s.ID, message); uerr != nil {
			slog.Error("radar_error_write_failed", "source", s.Slug, "error", uerr.Error())
		}
		slog.Warn("radar_poll_failed", "source", s.Slug, "error", message)
		return
	}

	// last_error is cleared on success. Leaving a stale error beside a working
	// source is how an operator concludes something is broken when it is not.
	if _, err := c.pool.Exec(ctx,
		`UPDATE radar_sources SET last_success_at = NOW(), last_error = NULL WHERE id = $1::uuid`,
		s.ID); err != nil {
		slog.Error("radar_success_write_failed", "source", s.Slug, "error", err.Error())
	}
	slog.Info("radar_poll_ok", "source", s.Slug, "stored", stored)
}

type sourceConfig struct {
	Path      string            `json:"path"`
	ItemsPath string            `json:"items_path"`
	Fields    map[string]string `json:"fields"`
	Auth      struct {
		In   string `json:"in"`   // "header" | "query"
		Name string `json:"name"` // header or parameter name
	} `json:"auth"`
	// Extra query parameters the provider needs (competition ids, language).
	Query map[string]string `json:"query"`
}

func (c *Collector) fetchAndStore(ctx context.Context, s dueSource) (int, error) {
	var cfg sourceConfig
	if len(s.Config) > 0 {
		if err := json.Unmarshal(s.Config, &cfg); err != nil {
			return 0, fmt.Errorf("config invalido: %w", err)
		}
	}
	if cfg.ItemsPath == "" || len(cfg.Fields) == 0 {
		// Named precisely: this is a registry mistake, not a provider outage,
		// and the two lead an operator to look in different places.
		return 0, fmt.Errorf("config incompleto: items_path e fields sao obrigatorios")
	}
	if cfg.Fields["external_id"] == "" {
		// Without it every poll inserts the same items again — the unique key
		// exists precisely to prevent that.
		return 0, fmt.Errorf("config incompleto: fields.external_id e obrigatorio")
	}

	endpoint := strings.TrimRight(s.BaseURL, "/") + "/" + strings.TrimLeft(cfg.Path, "/")
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return 0, fmt.Errorf("url invalida: %w", err)
	}

	query := request.URL.Query()
	for key, value := range cfg.Query {
		query.Set(key, value)
	}
	if s.APIKey != nil && *s.APIKey != "" {
		switch strings.ToLower(cfg.Auth.In) {
		case "query":
			query.Set(cfg.Auth.Name, *s.APIKey)
		default: // header is the default; a key in the URL ends up in logs
			name := cfg.Auth.Name
			if name == "" {
				name = "Authorization"
			}
			request.Header.Set(name, *s.APIKey)
		}
	}
	request.URL.RawQuery = query.Encode()
	request.Header.Set("Accept", "application/json")

	response, err := c.client.Do(request)
	if err != nil {
		return 0, fmt.Errorf("requisicao falhou: %w", err)
	}
	defer response.Body.Close()

	// Bounded: a provider returning a huge document must not be able to
	// exhaust memory on this host.
	body, err := io.ReadAll(io.LimitReader(response.Body, 8<<20))
	if err != nil {
		return 0, fmt.Errorf("leitura falhou: %w", err)
	}
	if response.StatusCode >= 400 {
		snippet := string(body)
		if len(snippet) > 200 {
			snippet = snippet[:200]
		}
		return 0, fmt.Errorf("http_%d: %s", response.StatusCode, snippet)
	}

	var document any
	if err := json.Unmarshal(body, &document); err != nil {
		return 0, fmt.Errorf("resposta nao e json: %w", err)
	}

	items, ok := dig(document, cfg.ItemsPath).([]any)
	if !ok {
		return 0, fmt.Errorf("items_path %q nao aponta para uma lista", cfg.ItemsPath)
	}

	stored := 0
	for _, raw := range items {
		item, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		externalID := asString(dig(item, cfg.Fields["external_id"]))
		title := asString(dig(item, cfg.Fields["title"]))
		if externalID == "" || title == "" {
			// Skipped rather than stored blank: an item with no id cannot be
			// deduplicated and one with no title renders as an empty row.
			continue
		}
		occurred := asTime(dig(item, cfg.Fields["occurred_at"]))

		payload, _ := json.Marshal(item)
		if _, err := c.pool.Exec(ctx, `
			INSERT INTO radar_items
			  (source_id, external_id, kind, title, summary, url, image_url, payload, occurred_at)
			VALUES ($1::uuid, $2, $3, $4, NULLIF($5,''), NULLIF($6,''), NULLIF($7,''), $8::jsonb, $9)
			ON CONFLICT (source_id, external_id) DO UPDATE
			   SET title = EXCLUDED.title, summary = EXCLUDED.summary,
			       url = EXCLUDED.url, image_url = EXCLUDED.image_url,
			       payload = EXCLUDED.payload, occurred_at = EXCLUDED.occurred_at,
			       fetched_at = NOW()`,
			s.ID, externalID, s.Kind, title,
			asString(dig(item, cfg.Fields["summary"])),
			asString(dig(item, cfg.Fields["url"])),
			asString(dig(item, cfg.Fields["image_url"])),
			payload, occurred,
		); err != nil {
			// One bad item does not fail the poll: the rest of the batch is
			// still worth storing, and the source is not broken.
			slog.Warn("radar_item_store_failed", "source", s.Slug,
				"external_id", externalID, "error", err.Error())
			continue
		}
		stored++
	}
	return stored, nil
}

// dig walks a dotted path — "fixture.id", "teams.home.name" — returning nil
// when any step is missing. Deliberately not JSONPath: the expressive half of
// JSONPath (filters, wildcards, recursion) is where a config becomes a program
// nobody can predict the cost of.
func dig(document any, path string) any {
	if path == "" {
		return nil
	}
	current := document
	for _, segment := range strings.Split(path, ".") {
		object, ok := current.(map[string]any)
		if !ok {
			return nil
		}
		current, ok = object[segment]
		if !ok {
			return nil
		}
	}
	return current
}

func asString(value any) string {
	switch typed := value.(type) {
	case string:
		return typed
	case float64:
		// JSON numbers arrive as float64; an id of 12345 must not become
		// "12345.000000", which would never match on the next poll and would
		// insert a duplicate every time.
		if typed == float64(int64(typed)) {
			return strconv.FormatInt(int64(typed), 10)
		}
		return strconv.FormatFloat(typed, 'f', -1, 64)
	case bool:
		return strconv.FormatBool(typed)
	case nil:
		return ""
	default:
		return ""
	}
}

// asTime falls back to NOW when the provider gives no usable timestamp.
// The alternative — refusing the item — would drop real content over a
// formatting difference, and `fetched_at` still records when we saw it.
func asTime(value any) time.Time {
	text := asString(value)
	if text == "" {
		return time.Now().UTC()
	}
	for _, layout := range []string{
		time.RFC3339, "2006-01-02T15:04:05Z0700", "2006-01-02 15:04:05",
		"2006-01-02", time.RFC1123Z, time.RFC1123,
	} {
		if parsed, err := time.Parse(layout, text); err == nil {
			return parsed.UTC()
		}
	}
	// Unix seconds, which several sports APIs use.
	if seconds, err := strconv.ParseInt(text, 10, 64); err == nil && seconds > 1_000_000_000 {
		return time.Unix(seconds, 0).UTC()
	}
	return time.Now().UTC()
}
