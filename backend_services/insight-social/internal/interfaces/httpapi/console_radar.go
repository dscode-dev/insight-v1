package httpapi

// Radar source registry — the console's write surface over `radar_sources`.
//
// Same shape and same guard as the competition registry: Social is the source
// of truth, the Control Plane is the only caller, writes carry a named
// operator. What is different here is the credential.
//
// THE API KEY IS WRITE-ONLY. `radarColumns` does not include `api_key`, so no
// read path can return it even by accident — a future handler that selects
// those columns gets the hint, not the secret. A management screen that echoes
// a key back turns every console session, log line and screenshot into a place
// the credential can leak from, and the operator who typed it already has it.
// What they need to see is WHICH key is set, which is what `api_key_hint` is.

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Note the absence of api_key. That absence is the security property.
const radarColumns = `id::text, slug, name, kind, base_url,
	api_key_hint, requires_key, config, poll_seconds, active,
	last_success_at, last_error_at, last_error,
	created_at, updated_at, updated_by`

type radarSource struct {
	ID          string          `json:"id"`
	Slug        string          `json:"slug"`
	Name        string          `json:"name"`
	Kind        string          `json:"kind"`
	BaseURL     string          `json:"base_url"`
	APIKeyHint  *string         `json:"api_key_hint"`
	RequiresKey bool            `json:"requires_key"`
	Config      json.RawMessage `json:"config"`
	PollSeconds int             `json:"poll_seconds"`
	Active      bool            `json:"active"`

	LastSuccessAt *time.Time `json:"last_success_at"`
	LastErrorAt   *time.Time `json:"last_error_at"`
	LastError     *string    `json:"last_error"`

	CreatedAt time.Time  `json:"created_at"`
	UpdatedAt time.Time  `json:"updated_at"`
	UpdatedBy *string    `json:"updated_by"`
	ItemCount int        `json:"item_count"`
	// Derived, so the console can render "chave configurada" without the key.
	HasAPIKey bool `json:"has_api_key"`
}

var radarKinds = map[string]bool{
	"live_matches": true, "scores": true, "news": true,
	"odds": true, "other": true,
}

func scanRadar(row pgx.Row, s *radarSource, withCount bool) error {
	targets := []any{
		&s.ID, &s.Slug, &s.Name, &s.Kind, &s.BaseURL,
		&s.APIKeyHint, &s.RequiresKey, &s.Config, &s.PollSeconds, &s.Active,
		&s.LastSuccessAt, &s.LastErrorAt, &s.LastError,
		&s.CreatedAt, &s.UpdatedAt, &s.UpdatedBy,
	}
	if withCount {
		targets = append(targets, &s.ItemCount)
	}
	if err := row.Scan(targets...); err != nil {
		return err
	}
	s.HasAPIKey = s.APIKeyHint != nil && *s.APIKeyHint != ""
	return nil
}

// ConsoleRadarSourcesList — GET /console/social/radar/sources
func ConsoleRadarSourcesList(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		rows, err := pool.Query(r.Context(), `
			SELECT `+radarColumns+`,
			       (SELECT count(*) FROM radar_items i WHERE i.source_id = s.id)
			  FROM radar_sources s
			 ORDER BY active DESC, name ASC`)
		if err != nil {
			slog.Error("console_radar_query_failed", "error", err.Error())
			writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "query_failed"})
			return
		}
		defer rows.Close()

		out := make([]radarSource, 0, 8)
		for rows.Next() {
			var s radarSource
			if err := scanRadar(rows, &s, true); err != nil {
				slog.Error("console_radar_scan_failed", "error", err.Error())
				writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "scan_failed"})
				return
			}
			out = append(out, s)
		}
		if rows.Err() != nil {
			slog.Error("console_radar_rows_failed", "error", rows.Err().Error())
			writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "scan_failed"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"sources": out, "count": len(out)})
	}
}

type radarInput struct {
	Slug        *string          `json:"slug"`
	Name        *string          `json:"name"`
	Kind        *string          `json:"kind"`
	BaseURL     *string          `json:"base_url"`
	APIKey      *string          `json:"api_key"`
	RequiresKey *bool            `json:"requires_key"`
	Config      *json.RawMessage `json:"config"`
	PollSeconds *int             `json:"poll_seconds"`
	Active      *bool            `json:"active"`
}

func (in radarInput) validate(creating bool) string {
	if creating {
		for label, value := range map[string]*string{
			"slug": in.Slug, "name": in.Name, "kind": in.Kind, "base_url": in.BaseURL,
		} {
			if value == nil || strings.TrimSpace(*value) == "" {
				return label + "_required"
			}
		}
	}
	if in.Slug != nil && !slugPattern.MatchString(strings.TrimSpace(*in.Slug)) {
		return "slug_invalid: use minusculas, numeros e hifen"
	}
	if in.Kind != nil && !radarKinds[strings.TrimSpace(*in.Kind)] {
		return "kind_invalid: live_matches, scores, news, odds ou other"
	}
	// A provider reached over plain HTTP would carry the API key in the clear
	// on every poll, several times an hour, forever.
	if in.BaseURL != nil {
		url := strings.TrimSpace(*in.BaseURL)
		if url != "" && !strings.HasPrefix(url, "https://") {
			return "base_url_invalid: use https:// (a chave viaja em cada poll)"
		}
	}
	if in.PollSeconds != nil && (*in.PollSeconds < 10 || *in.PollSeconds > 86400) {
		return "poll_seconds_invalid: 10..86400"
	}
	if in.Config != nil && !json.Valid(*in.Config) {
		return "config_invalid: json malformado"
	}
	return ""
}

// The last four characters. Enough to recognise which key is configured,
// not enough to reconstruct it.
func keyHint(key string) *string {
	trimmed := strings.TrimSpace(key)
	if trimmed == "" {
		return nil
	}
	if len(trimmed) > 4 {
		trimmed = trimmed[len(trimmed)-4:]
	}
	return &trimmed
}

// ConsoleRadarSourceCreate — POST /console/social/radar/sources
func ConsoleRadarSourceCreate(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var in radarInput
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 32<<10)).Decode(&in); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "invalid_json"})
			return
		}
		if problem := in.validate(true); problem != "" {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": problem})
			return
		}
		operator, _ := OperatorFromContext(r.Context())

		var key *string
		var hint *string
		if in.APIKey != nil && strings.TrimSpace(*in.APIKey) != "" {
			trimmed := strings.TrimSpace(*in.APIKey)
			key = &trimmed
			hint = keyHint(trimmed)
		}

		var s radarSource
		row := pool.QueryRow(r.Context(), `
			INSERT INTO radar_sources
			  (slug, name, kind, base_url, api_key, api_key_hint,
			   requires_key, config, poll_seconds, active, updated_by)
			VALUES ($1::varchar, $2::varchar, $3::varchar, $4::text,
			        $5::text, $6::varchar,
			        COALESCE($7::boolean, TRUE),
			        COALESCE($8::jsonb, '{}'::jsonb),
			        COALESCE($9::integer, 300),
			        COALESCE($10::boolean, FALSE),
			        $11::text)
			RETURNING `+radarColumns,
			strings.TrimSpace(*in.Slug), strings.TrimSpace(*in.Name),
			strings.TrimSpace(*in.Kind), strings.TrimSpace(*in.BaseURL),
			key, hint, in.RequiresKey, in.Config, in.PollSeconds, in.Active,
			nullableOperator(operator),
		)
		if scanErr := scanRadar(row, &s, false); scanErr != nil {
			var pgErr *pgconn.PgError
			if errors.As(scanErr, &pgErr) {
				switch {
				case pgErr.Code == "23505":
					writeJSON(w, http.StatusConflict,
						map[string]any{"detail": "slug_already_exists", "slug": *in.Slug})
					return
				case pgErr.ConstraintName == "radar_sources_key_when_required_check":
					// The database refusing to activate a source that needs a
					// key and has none. Surfaced as the actionable sentence
					// rather than a constraint name.
					writeJSON(w, http.StatusBadRequest, map[string]any{
						"detail": "api_key_required_to_activate",
						"hint":   "cadastre inativa, adicione a chave e ative depois",
					})
					return
				}
			}
			slog.Error("console_radar_insert_failed", "error", scanErr.Error())
			writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "insert_failed"})
			return
		}
		writeJSON(w, http.StatusCreated, s)
	}
}

// ConsoleRadarSourceUpdate — PATCH /console/social/radar/sources/{id}
//
// The key is updated only when the caller sends one. An omitted `api_key`
// keeps the stored value — which is what lets the console edit a source's
// name without having to re-type its credential, and without the client
// needing to read the key back in order to send it again.
func ConsoleRadarSourceUpdate(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id := strings.TrimSpace(r.PathValue("id"))
		if id == "" {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "id_required"})
			return
		}
		var in radarInput
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 32<<10)).Decode(&in); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "invalid_json"})
			return
		}
		if problem := in.validate(false); problem != "" {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": problem})
			return
		}
		operator, _ := OperatorFromContext(r.Context())

		var key, hint *string
		if in.APIKey != nil {
			trimmed := strings.TrimSpace(*in.APIKey)
			if trimmed == "" {
				// An explicit empty string is how a key is REMOVED. Distinct
				// from omitting the field, which keeps it — without the
				// distinction there would be no way to unset a credential.
				empty := ""
				key, hint = &empty, nil
			} else {
				key, hint = &trimmed, keyHint(trimmed)
			}
		}

		var s radarSource
		row := pool.QueryRow(r.Context(), `
			UPDATE radar_sources SET
			   slug         = COALESCE($2::varchar, slug),
			   name         = COALESCE($3::varchar, name),
			   kind         = COALESCE($4::varchar, kind),
			   base_url     = COALESCE($5::text, base_url),
			   api_key      = CASE WHEN $6::text IS NULL THEN api_key
			                       WHEN $6::text = '' THEN NULL
			                       ELSE $6::text END,
			   api_key_hint = CASE WHEN $6::text IS NULL THEN api_key_hint
			                       WHEN $6::text = '' THEN NULL
			                       ELSE $7::varchar END,
			   requires_key = COALESCE($8::boolean, requires_key),
			   config       = COALESCE($9::jsonb, config),
			   poll_seconds = COALESCE($10::integer, poll_seconds),
			   active       = COALESCE($11::boolean, active),
			   updated_at   = NOW(),
			   updated_by   = COALESCE($12::text, updated_by)
			 WHERE id = $1::uuid
			RETURNING `+radarColumns,
			id, trimmedOrNil(in.Slug), trimmedOrNil(in.Name), trimmedOrNil(in.Kind),
			trimmedOrNil(in.BaseURL), key, hint, in.RequiresKey, in.Config,
			in.PollSeconds, in.Active, nullableOperator(operator),
		)
		if scanErr := scanRadar(row, &s, false); scanErr != nil {
			if errors.Is(scanErr, pgx.ErrNoRows) {
				writeJSON(w, http.StatusNotFound, map[string]any{"detail": "source_not_found"})
				return
			}
			var pgErr *pgconn.PgError
			if errors.As(scanErr, &pgErr) {
				switch {
				case pgErr.Code == "23505":
					writeJSON(w, http.StatusConflict, map[string]any{"detail": "slug_already_exists"})
					return
				case pgErr.ConstraintName == "radar_sources_key_when_required_check":
					writeJSON(w, http.StatusBadRequest, map[string]any{
						"detail": "api_key_required_to_activate",
						"hint":   "adicione api_key na mesma chamada que ativa a fonte",
					})
					return
				}
			}
			slog.Error("console_radar_update_failed", "error", scanErr.Error())
			writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "update_failed"})
			return
		}
		writeJSON(w, http.StatusOK, s)
	}
}

// ConsoleRadarSourceDelete — DELETE /console/social/radar/sources/{id}
//
// Cascades to the source's items, unlike competitions. A radar item is
// content fetched FROM the source; with the source gone it has no provenance
// and nothing can refresh it. Deactivating (`active: false`) stops the polling
// and keeps what was collected.
func ConsoleRadarSourceDelete(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id := strings.TrimSpace(r.PathValue("id"))
		if id == "" {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "id_required"})
			return
		}
		var items int
		_ = pool.QueryRow(r.Context(),
			`SELECT count(*) FROM radar_items WHERE source_id = $1::uuid`, id).Scan(&items)

		tag, err := pool.Exec(r.Context(), `DELETE FROM radar_sources WHERE id = $1::uuid`, id)
		if err != nil {
			slog.Error("console_radar_delete_failed", "error", err.Error())
			writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "delete_failed"})
			return
		}
		if tag.RowsAffected() == 0 {
			writeJSON(w, http.StatusNotFound, map[string]any{"detail": "source_not_found"})
			return
		}
		// How much went with it, so the console can say so rather than the
		// operator discovering it from an emptier Radar.
		writeJSON(w, http.StatusOK, map[string]any{"deleted": true, "items_removed": items})
	}
}
