package httpapi

// Competition registry — the console's write surface over `competitions`.
//
// Social is the source of truth. The Control Plane (insight-console-api) is
// the only caller, and it reaches these routes with SOCIAL_OPS_TOKEN plus the
// operator who asked; everything else in the platform reads competitions from
// here rather than keeping its own list.
//
// WHY WRITES LIVE HERE AND NOT IN THE GATEWAY. The Gateway is an edge for the
// mobile app. A registry edited by operators is not app traffic, and routing
// it through the app's edge would put administrative writes behind the same
// rate limits, the same token audience and the same public hostname as a feed
// request.
//
// DEACTIVATION IS NOT DELETION. `active = FALSE` removes a competition from
// the app without destroying the conversation that happened inside it. Actual
// deletion is possible only while no post references the competition — the
// foreign key is ON DELETE RESTRICT, and the 409 below is that constraint
// surfaced as something the console can explain instead of a 500.

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"regexp"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Slug is the platform-wide identifier for a competition: it appears in the
// app, in Explorer's collection config and in Atlas's competition_key. Bound
// to a shape that survives all three — no spaces, no case, no punctuation
// beyond the hyphen.
var slugPattern = regexp.MustCompile(`^[a-z0-9]+(-[a-z0-9]+)*$`)

const competitionColumns = `id::text, slug, name, short_name, sport, region,
	country, continent, type, icon, logo_url, accent_color,
	featured, priority, display_order, active,
	created_at, updated_at, updated_by`

type competitionRecord struct {
	ID           string  `json:"id"`
	Slug         string  `json:"slug"`
	Name         string  `json:"name"`
	ShortName    string  `json:"short_name"`
	Sport        string  `json:"sport"`
	Region       string  `json:"region"`
	Country      *string `json:"country"`
	Continent    *string `json:"continent"`
	Type         *string `json:"type"`
	Icon         *string `json:"icon"`
	LogoURL      *string `json:"logo_url"`
	AccentColor  string  `json:"accent_color"`
	Featured     bool    `json:"featured"`
	Priority     int     `json:"priority"`
	DisplayOrder int     `json:"display_order"`
	Active       bool    `json:"active"`
	// time.Time, not string: created_at/updated_at are timestamptz, and pgx
	// will not scan those into a string — it fails at runtime, on a path the
	// validation tests never touch because they never open a connection.
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
	UpdatedBy *string   `json:"updated_by"`
	PostCount int       `json:"post_count"`
}

// ConsoleCompetitionsList — GET /console/social/competitions
//
// Returns inactive competitions too, and the post count with each one. The
// console is where an operator decides whether a competition may be
// deactivated or removed, and both answers depend on what is attached to it —
// a list that hid inactive rows would make a deactivated competition look
// deleted.
func ConsoleCompetitionsList(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		rows, err := pool.Query(r.Context(), `
			SELECT `+competitionColumns+`,
			       (SELECT count(*) FROM posts p
			         WHERE p.competition_id = c.id AND p.deleted_at IS NULL)
			  FROM competitions c
			 ORDER BY featured DESC, priority ASC, display_order ASC, name ASC`)
		if err != nil {
			slog.Error("console_competitions_query_failed", "error", err.Error())
			writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "query_failed"})
			return
		}
		defer rows.Close()

		out := make([]competitionRecord, 0, 16)
		for rows.Next() {
			var c competitionRecord
			if err := rows.Scan(
				&c.ID, &c.Slug, &c.Name, &c.ShortName, &c.Sport, &c.Region,
				&c.Country, &c.Continent, &c.Type, &c.Icon, &c.LogoURL,
				&c.AccentColor, &c.Featured, &c.Priority, &c.DisplayOrder,
				&c.Active, &c.CreatedAt, &c.UpdatedAt, &c.UpdatedBy, &c.PostCount,
			); err != nil {
				writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "scan_failed"})
				return
			}
			out = append(out, c)
		}
		if rows.Err() != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "scan_failed"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"competitions": out, "count": len(out)})
	}
}

type competitionInput struct {
	Slug         *string `json:"slug"`
	Name         *string `json:"name"`
	ShortName    *string `json:"short_name"`
	Sport        *string `json:"sport"`
	Region       *string `json:"region"`
	Country      *string `json:"country"`
	Continent    *string `json:"continent"`
	Type         *string `json:"type"`
	Icon         *string `json:"icon"`
	LogoURL      *string `json:"logo_url"`
	AccentColor  *string `json:"accent_color"`
	Featured     *bool   `json:"featured"`
	Priority     *int    `json:"priority"`
	DisplayOrder *int    `json:"display_order"`
	Active       *bool   `json:"active"`
}

// Pointers throughout so PATCH can distinguish "field omitted" from "field set
// to empty". Without that, a console form that submits only the name would
// blank every other field.

func (in competitionInput) validate(creating bool) string {
	if creating {
		if in.Slug == nil || strings.TrimSpace(*in.Slug) == "" {
			return "slug_required"
		}
		if in.Name == nil || strings.TrimSpace(*in.Name) == "" {
			return "name_required"
		}
	}
	if in.Slug != nil && !slugPattern.MatchString(strings.TrimSpace(*in.Slug)) {
		return "slug_invalid: use minusculas, numeros e hifen (ex.: premier-league)"
	}
	if in.AccentColor != nil {
		colour := strings.TrimSpace(*in.AccentColor)
		if colour != "" && !regexp.MustCompile(`^#[0-9a-fA-F]{6}$`).MatchString(colour) {
			return "accent_color_invalid: use #RRGGBB"
		}
	}
	// A logo is optional, but a value that is present must be fetchable by the
	// app. Anything else renders as a broken image with no error anywhere.
	if in.LogoURL != nil {
		url := strings.TrimSpace(*in.LogoURL)
		if url != "" && !strings.HasPrefix(url, "https://") {
			return "logo_url_invalid: use https://"
		}
	}
	return ""
}

// ConsoleCompetitionCreate — POST /console/social/competitions
func ConsoleCompetitionCreate(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var in competitionInput
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16<<10)).Decode(&in); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "invalid_json"})
			return
		}
		if problem := in.validate(true); problem != "" {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": problem})
			return
		}
		operator, _ := OperatorFromContext(r.Context())

		var c competitionRecord
		err := pool.QueryRow(r.Context(), `
			INSERT INTO competitions
			  (slug, name, short_name, sport, region, country, continent, type,
			   icon, logo_url, accent_color, featured, priority, display_order,
			   active, updated_by)
			-- Every parameter is cast explicitly. Postgres infers a
			-- parameter's type from its first use, and $2 appears both as
			-- the name column (varchar(120)) and inside LEFT() (text):
			--   ERROR: inconsistent types deduced for parameter $2
			--   DETAIL: text versus character varying
			-- Casting removes the inference entirely rather than depending on
			-- the order the planner happens to visit the uses in.
			VALUES ($1::varchar, $2::varchar,
			        COALESCE($3::varchar, LEFT($2::text, 32)::varchar),
			        COALESCE($4::varchar, 'football'),
			        COALESCE($5::varchar, ''),
			        $6::text, $7::text, $8::text, $9::text, $10::text,
			        COALESCE($11::varchar, '#5BA8FF'),
			        COALESCE($12::boolean, FALSE),
			        COALESCE($13::integer, 100), COALESCE($14::integer, 100),
			        COALESCE($15::boolean, TRUE), $16::text)
			RETURNING `+competitionColumns,
			strings.TrimSpace(*in.Slug), strings.TrimSpace(*in.Name),
			in.ShortName, in.Sport, in.Region, in.Country, in.Continent, in.Type,
			in.Icon, in.LogoURL, in.AccentColor, in.Featured, in.Priority,
			in.DisplayOrder, in.Active, nullableOperator(operator),
		).Scan(
			&c.ID, &c.Slug, &c.Name, &c.ShortName, &c.Sport, &c.Region,
			&c.Country, &c.Continent, &c.Type, &c.Icon, &c.LogoURL,
			&c.AccentColor, &c.Featured, &c.Priority, &c.DisplayOrder,
			&c.Active, &c.CreatedAt, &c.UpdatedAt, &c.UpdatedBy,
		)
		if err != nil {
			// 23505 is the slug's UNIQUE. Reported as a conflict on a named
			// field, because "already exists" and "server error" ask the
			// operator to do completely different things.
			var pgErr *pgconn.PgError
			if errors.As(err, &pgErr) && pgErr.Code == "23505" {
				writeJSON(w, http.StatusConflict,
					map[string]any{"detail": "slug_already_exists", "slug": *in.Slug})
				return
			}
			slog.Error("console_competition_insert_failed", "error", err.Error())
			writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "insert_failed"})
			return
		}
		writeJSON(w, http.StatusCreated, c)
	}
}

// ConsoleCompetitionUpdate — PATCH /console/social/competitions/{id}
//
// Partial by construction: every column is updated to COALESCE($n, column),
// so an omitted field keeps its stored value. The alternative — read, merge in
// Go, write back — loses any concurrent edit between the read and the write.
func ConsoleCompetitionUpdate(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id := strings.TrimSpace(r.PathValue("id"))
		if id == "" {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "id_required"})
			return
		}
		var in competitionInput
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16<<10)).Decode(&in); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "invalid_json"})
			return
		}
		if problem := in.validate(false); problem != "" {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": problem})
			return
		}
		operator, _ := OperatorFromContext(r.Context())

		var c competitionRecord
		err := pool.QueryRow(r.Context(), `
			UPDATE competitions SET
			   slug          = COALESCE($2::varchar, slug),
			   name          = COALESCE($3::varchar, name),
			   short_name    = COALESCE($4::varchar, short_name),
			   sport         = COALESCE($5::varchar, sport),
			   region        = COALESCE($6::varchar, region),
			   country       = COALESCE($7::text, country),
			   continent     = COALESCE($8::text, continent),
			   type          = COALESCE($9::text, type),
			   icon          = COALESCE($10::text, icon),
			   logo_url      = COALESCE($11::text, logo_url),
			   accent_color  = COALESCE($12::varchar, accent_color),
			   featured      = COALESCE($13::boolean, featured),
			   priority      = COALESCE($14::integer, priority),
			   display_order = COALESCE($15::integer, display_order),
			   active        = COALESCE($16::boolean, active),
			   updated_at    = NOW(),
			   updated_by    = COALESCE($17::text, updated_by)
			 WHERE id = $1::uuid
			RETURNING `+competitionColumns,
			id, trimmedOrNil(in.Slug), trimmedOrNil(in.Name), in.ShortName,
			in.Sport, in.Region, in.Country, in.Continent, in.Type, in.Icon,
			in.LogoURL, in.AccentColor, in.Featured, in.Priority,
			in.DisplayOrder, in.Active, nullableOperator(operator),
		).Scan(
			&c.ID, &c.Slug, &c.Name, &c.ShortName, &c.Sport, &c.Region,
			&c.Country, &c.Continent, &c.Type, &c.Icon, &c.LogoURL,
			&c.AccentColor, &c.Featured, &c.Priority, &c.DisplayOrder,
			&c.Active, &c.CreatedAt, &c.UpdatedAt, &c.UpdatedBy,
		)
		if errors.Is(err, pgx.ErrNoRows) {
			writeJSON(w, http.StatusNotFound, map[string]any{"detail": "competition_not_found"})
			return
		}
		if err != nil {
			var pgErr *pgconn.PgError
			if errors.As(err, &pgErr) && pgErr.Code == "23505" {
				writeJSON(w, http.StatusConflict, map[string]any{"detail": "slug_already_exists"})
				return
			}
			slog.Error("console_competition_update_failed", "error", err.Error())
			writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "update_failed"})
			return
		}
		writeJSON(w, http.StatusOK, c)
	}
}

// ConsoleCompetitionDelete — DELETE /console/social/competitions/{id}
//
// Only succeeds while nothing references the competition. The foreign key is
// ON DELETE RESTRICT, so this is Postgres's answer rendered as a 409 with the
// count that explains it — the operator's next step is to deactivate instead,
// and the reply says how many posts are in the way.
func ConsoleCompetitionDelete(pool *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id := strings.TrimSpace(r.PathValue("id"))
		if id == "" {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "id_required"})
			return
		}
		tag, err := pool.Exec(r.Context(), `DELETE FROM competitions WHERE id = $1::uuid`, id)
		if err != nil {
			var pgErr *pgconn.PgError
			if errors.As(err, &pgErr) && pgErr.Code == "23503" {
				var posts int
				_ = pool.QueryRow(r.Context(),
					`SELECT count(*) FROM posts WHERE competition_id = $1::uuid`, id).Scan(&posts)
				writeJSON(w, http.StatusConflict, map[string]any{
					"detail":     "competition_in_use",
					"post_count": posts,
					"hint":       "desative (active=false) em vez de remover; o historico permanece",
				})
				return
			}
			writeJSON(w, http.StatusInternalServerError, map[string]any{"detail": "delete_failed"})
			return
		}
		if tag.RowsAffected() == 0 {
			writeJSON(w, http.StatusNotFound, map[string]any{"detail": "competition_not_found"})
			return
		}
		w.WriteHeader(http.StatusNoContent)
	}
}

func trimmedOrNil(value *string) *string {
	if value == nil {
		return nil
	}
	trimmed := strings.TrimSpace(*value)
	if trimmed == "" {
		return nil
	}
	return &trimmed
}

// The operator is already required by RequireConsoleToken on write routes;
// this keeps `updated_by` NULL rather than empty if that ever changes, so the
// column means "unknown" instead of "someone with a blank name".
func nullableOperator(operator ConsoleOperator) *string {
	name := strings.TrimSpace(operator.Username)
	if name == "" {
		name = strings.TrimSpace(operator.ID)
	}
	if name == "" {
		return nil
	}
	return &name
}
