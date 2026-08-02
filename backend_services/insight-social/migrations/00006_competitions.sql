-- 00006_competitions — Featured Competitions Rail (AZTECA-HOME-A).
--
-- insight-social is the source of truth for the competitions shown in the
-- Azteca Home "Featured Competitions Rail". The backend owns priorities,
-- ordering and the `featured` flag; the client never decides them.

-- +goose Up
-- +goose StatementBegin
CREATE TABLE IF NOT EXISTS competitions (
    id            TEXT PRIMARY KEY,           -- stable slug-like id
    name          TEXT NOT NULL,
    slug          TEXT NOT NULL UNIQUE,
    country       TEXT,
    continent     TEXT,
    type          TEXT,                       -- league | cup | international
    featured      BOOLEAN NOT NULL DEFAULT FALSE,
    priority      INTEGER NOT NULL DEFAULT 100,
    display_order INTEGER NOT NULL DEFAULT 100,
    icon          TEXT,
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Backward compatibility:
-- 00001_init created a previous `competitions` table with UUID `id` and
-- `is_active`. AZTECA-HOME-A introduced the rail columns and canonical
-- `active`. Production may already have either shape, so this migration must
-- evolve the table in place and preserve every existing row.
ALTER TABLE competitions ADD COLUMN IF NOT EXISTS country TEXT;
ALTER TABLE competitions ADD COLUMN IF NOT EXISTS continent TEXT;
ALTER TABLE competitions ADD COLUMN IF NOT EXISTS type TEXT;
ALTER TABLE competitions ADD COLUMN IF NOT EXISTS featured BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE competitions ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 100;
ALTER TABLE competitions ADD COLUMN IF NOT EXISTS display_order INTEGER NOT NULL DEFAULT 100;
ALTER TABLE competitions ADD COLUMN IF NOT EXISTS icon TEXT;
ALTER TABLE competitions ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE competitions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Canonical domain column is `active`. Legacy `is_active` is read only during
-- migration backfill and remains available for old FKs/code until a later,
-- explicit cleanup migration.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = 'competitions'
           AND column_name = 'is_active'
    ) THEN
        UPDATE competitions
           SET active = is_active
         WHERE active IS DISTINCT FROM is_active;
    END IF;
END $$;

-- Preserve legacy rows while populating rail metadata when obvious legacy
-- fields exist.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'competitions' AND column_name = 'region'
    ) THEN
        UPDATE competitions
           SET country = COALESCE(country, region),
               continent = COALESCE(continent, region)
         WHERE country IS NULL OR continent IS NULL;
    END IF;
END $$;

-- Ordering index: featured first, then priority, display_order, name.
DROP INDEX IF EXISTS ix_competitions_rail;
CREATE INDEX IF NOT EXISTS ix_competitions_rail
    ON competitions (featured DESC, priority ASC, display_order ASC, name ASC)
    WHERE active = TRUE;

-- Initial competitions (backend-owned; NOT hardcoded in Flutter). Copa do
-- Mundo is the first FEATURED competition. ON CONFLICT keeps re-runs idempotent
-- without clobbering operator edits to priority/featured.
DO $$
DECLARE
    id_type TEXT;
BEGIN
    SELECT data_type
      INTO id_type
      FROM information_schema.columns
     WHERE table_name = 'competitions'
       AND column_name = 'id';

    IF id_type = 'uuid' THEN
        INSERT INTO competitions
            (id, name, slug, short_name, sport, region, accent_color, country, continent, type, featured, priority, display_order, icon, active)
        VALUES
            ('00000000-0000-4000-8000-000000000001'::uuid, 'Copa do Mundo',    'copa-do-mundo',    'World Cup', 'football', 'Mundo',          '#5BA8FF', NULL,        'Mundo',          'international', TRUE,  1,  1,  '🏆', TRUE),
            ('00000000-0000-4000-8000-000000000002'::uuid, 'Champions League', 'champions-league', 'UCL',       'football', 'Europa',         '#5BA8FF', NULL,        'Europa',         'cup',          FALSE, 10, 10, '⚽', TRUE),
            ('00000000-0000-4000-8000-000000000003'::uuid, 'Premier League',   'premier-league',   'EPL',       'football', 'Europa',         '#5BA8FF', 'Inglaterra','Europa',         'league',       FALSE, 20, 20, '🏴', TRUE),
            ('00000000-0000-4000-8000-000000000004'::uuid, 'LaLiga',           'laliga',           'LaLiga',    'football', 'Europa',         '#5BA8FF', 'Espanha',   'Europa',         'league',       FALSE, 21, 21, '🇪🇸', TRUE),
            ('00000000-0000-4000-8000-000000000005'::uuid, 'Brasileirão',      'brasileirao',      'BR',        'football', 'América do Sul', '#5BA8FF', 'Brasil',    'América do Sul', 'league',       FALSE, 30, 30, '🇧🇷', TRUE),
            ('00000000-0000-4000-8000-000000000006'::uuid, 'Libertadores',     'libertadores',     'Liberta',   'football', 'América do Sul', '#5BA8FF', NULL,        'América do Sul', 'cup',          FALSE, 31, 31, '🌎', TRUE)
        ON CONFLICT (slug) DO UPDATE SET
            country = COALESCE(competitions.country, EXCLUDED.country),
            continent = COALESCE(competitions.continent, EXCLUDED.continent),
            type = COALESCE(competitions.type, EXCLUDED.type),
            featured = competitions.featured,
            priority = competitions.priority,
            display_order = competitions.display_order,
            icon = COALESCE(competitions.icon, EXCLUDED.icon),
            active = competitions.active,
            updated_at = now();
    ELSE
        INSERT INTO competitions
            (id, name, slug, country, continent, type, featured, priority, display_order, icon, active)
        VALUES
            ('world_cup',       'Copa do Mundo',    'copa-do-mundo',    NULL,        'Mundo',          'international', TRUE,  1,  1,  '🏆', TRUE),
            ('champions_league','Champions League', 'champions-league', NULL,        'Europa',         'cup',          FALSE, 10, 10, '⚽', TRUE),
            ('premier_league',  'Premier League',   'premier-league',   'Inglaterra','Europa',         'league',       FALSE, 20, 20, '🏴', TRUE),
            ('laliga',          'LaLiga',           'laliga',           'Espanha',   'Europa',         'league',       FALSE, 21, 21, '🇪🇸', TRUE),
            ('brasileirao',     'Brasileirão',      'brasileirao',      'Brasil',    'América do Sul', 'league',       FALSE, 30, 30, '🇧🇷', TRUE),
            ('libertadores',    'Libertadores',     'libertadores',     NULL,        'América do Sul', 'cup',          FALSE, 31, 31, '🌎', TRUE)
        ON CONFLICT (slug) DO UPDATE SET
            country = COALESCE(competitions.country, EXCLUDED.country),
            continent = COALESCE(competitions.continent, EXCLUDED.continent),
            type = COALESCE(competitions.type, EXCLUDED.type),
            featured = competitions.featured,
            priority = competitions.priority,
            display_order = competitions.display_order,
            icon = COALESCE(competitions.icon, EXCLUDED.icon),
            active = competitions.active,
            updated_at = now();
    END IF;
END $$;
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP INDEX IF EXISTS ix_competitions_rail;
-- Do not drop `competitions`: the table may predate this rail migration
-- (00001_init) and is referenced by matches/communities.
-- +goose StatementEnd
