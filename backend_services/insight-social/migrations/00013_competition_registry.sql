-- +goose Up
-- +goose StatementBegin
--
-- COMPETITION-REGISTRY-V1 — competitions become a registry, not a lookup list.
--
-- The platform rule this encodes, as the owner stated it:
--
--     "Campeonatos devem ser totalmente cadastrados e configurados a partir
--      do insight-console. Não podem existir em todo o Insight se não
--      estiverem devidamente cadastrados e configurados."
--
-- Today the opposite holds. `posts` has no competition column at all — not a
-- foreign key, not a slug, not even a metadata convention (the 14 existing
-- posts carry only `kind`, `publication_type`, `smoke`). And `visibility`
-- already accepts the value 'competition', which is checked but means
-- nothing: a post can declare competition scope with no competition attached.
--
-- Three changes, in the order they depend on each other.
--

-- ---------------------------------------------------------------------------
-- 1. Finish what migration 00006 declared.
--
-- 00006 wrote: "Canonical domain column is `active`. Legacy `is_active` is
-- read only during [migration]" — backfilled `active` from `is_active` once,
-- and left both columns standing. Every reader since uses `active`;
-- `is_active` has had no writer and no reader, so it holds whatever it held
-- in 2026 and would silently disagree the moment a CRUD endpoint writes one
-- and not the other. This migration adds that endpoint, so the ambiguity has
-- to go first.
--
-- Reconciled rather than assumed: the six current rows agree, but a DROP that
-- would discard a disagreement should say so out loud.
DO $$
DECLARE divergent INT;
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'competitions' AND column_name = 'is_active'
    ) THEN
        EXECUTE 'SELECT count(*) FROM competitions WHERE active IS DISTINCT FROM is_active'
            INTO divergent;
        IF divergent > 0 THEN
            RAISE WARNING 'competitions: % linha(s) com active <> is_active; mantendo active (canonica)', divergent;
        END IF;
    END IF;
END $$;

ALTER TABLE competitions DROP COLUMN IF EXISTS is_active;

-- ---------------------------------------------------------------------------
-- 2. Registry fields.
--
-- `logo_url` is NOT a duplicate of `icon`. `icon` holds an emoji — 🏆, ⚽,
-- 🇧🇷 — which the mobile client renders inline in the rail. A logo is an
-- image the client fetches. Optional: a competition is registrable before
-- anyone has produced artwork for it, and a NULL says "no logo yet" where an
-- empty string would look like a broken URL.
ALTER TABLE competitions ADD COLUMN IF NOT EXISTS logo_url TEXT;

-- Who last changed the registry and when. A CRUD surface without this cannot
-- answer "why did this competition disappear from the app yesterday".
ALTER TABLE competitions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE competitions ADD COLUMN IF NOT EXISTS updated_by TEXT;

-- ---------------------------------------------------------------------------
-- 3. Make the rule an invariant, not a convention.
--
-- ON DELETE RESTRICT, never CASCADE: deleting a competition must not silently
-- delete the conversation that happened inside it. An operator who wants a
-- competition gone deactivates it (`active = FALSE`), which hides it without
-- destroying history. RESTRICT turns "this competition still has posts" into
-- an error the console can show, instead of a number that quietly drops.
ALTER TABLE posts ADD COLUMN IF NOT EXISTS competition_id UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'posts_competition_id_fkey'
    ) THEN
        ALTER TABLE posts
            ADD CONSTRAINT posts_competition_id_fkey
            FOREIGN KEY (competition_id) REFERENCES competitions(id) ON DELETE RESTRICT;
    END IF;
END $$;

-- The half that was missing. `visibility = 'competition'` has been accepted
-- since 00001 with nothing to name the competition; this makes the pair
-- inseparable. A public or private post may still carry a competition — that
-- is how a public post reaches a competition's rail — but a
-- competition-scoped post without one is now unrepresentable.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'posts_competition_scope_check'
    ) THEN
        ALTER TABLE posts
            ADD CONSTRAINT posts_competition_scope_check
            CHECK (visibility <> 'competition' OR competition_id IS NOT NULL);
    END IF;
END $$;

-- The feed's access pattern: one competition, newest first, live posts only.
-- Partial on deleted_at for the same reason ix_posts_public_created is.
CREATE INDEX IF NOT EXISTS ix_posts_competition_created
    ON posts (competition_id, created_at DESC)
    WHERE deleted_at IS NULL;

-- ---------------------------------------------------------------------------
-- 4. Seed the five competitions the platform ships with.
--
-- ON CONFLICT DO NOTHING, keyed on the natural key: these rows already exist
-- on the deployed database, edited by hand. A seed that overwrote them would
-- undo an operator's work on every redeploy — the migration's job is to
-- guarantee they EXIST, not to dictate what they say.
--
-- `id` is left to the default so a fresh database and the deployed one do not
-- end up with different primary keys for the same competition; the slug is
-- what anything outside this table refers to.
INSERT INTO competitions (slug, name, short_name, sport, region, country, continent, type, icon, featured, priority, display_order, active)
VALUES
    ('champions-league', 'Champions League', 'UCL',     'football', 'Europa',         NULL,        'Europa',         'cup',    '⚽', FALSE, 10, 10, TRUE),
    ('premier-league',   'Premier League',   'EPL',     'football', 'Europa',         'Inglaterra','Europa',         'league', '🏴', FALSE, 20, 20, TRUE),
    ('laliga',           'LaLiga',           'LaLiga',  'football', 'Europa',         'Espanha',   'Europa',         'league', '🇪🇸', FALSE, 21, 21, TRUE),
    ('brasileirao',      'Brasileirão',      'BR',      'football', 'América do Sul', 'Brasil',    'América do Sul', 'league', '🇧🇷', FALSE, 30, 30, TRUE),
    ('libertadores',     'Libertadores',     'Liberta', 'football', 'América do Sul', NULL,        'América do Sul', 'cup',    '🌎', FALSE, 31, 31, TRUE)
ON CONFLICT (slug) DO NOTHING;

-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
--
-- The seed is not removed: by the time anyone rolls back, those rows may hold
-- operator edits and may be referenced by posts. Dropping the FK and the
-- column is enough to undo what this migration constrained.
DROP INDEX IF EXISTS ix_posts_competition_created;
ALTER TABLE posts DROP CONSTRAINT IF EXISTS posts_competition_scope_check;
ALTER TABLE posts DROP CONSTRAINT IF EXISTS posts_competition_id_fkey;
ALTER TABLE posts DROP COLUMN IF EXISTS competition_id;

ALTER TABLE competitions DROP COLUMN IF EXISTS updated_by;
ALTER TABLE competitions DROP COLUMN IF EXISTS updated_at;
ALTER TABLE competitions DROP COLUMN IF EXISTS logo_url;

-- Restored as a copy of the canonical column, which is the only truthful
-- value available — the pre-migration contents are not recoverable.
ALTER TABLE competitions ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
UPDATE competitions SET is_active = active;
-- +goose StatementEnd
