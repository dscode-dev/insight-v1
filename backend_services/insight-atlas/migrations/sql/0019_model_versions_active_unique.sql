-- Database-level backstop for ModelRegistry.promote()'s race window.
--
-- Context: promote() archives the previous `active` version then sets
-- the target `active` in two separate statements — under READ
-- COMMITTED, two concurrent promote() calls for the SAME family could
-- both believe they're the only active one and leave TWO `active` rows,
-- which then makes ModelRegistry.get_active()'s `.scalar_one_or_none()`
-- raise `MultipleResultsFound` at inference load time. `atlas/registry/
-- repo.py::promote()` now serializes via `pg_advisory_xact_lock` per
-- family (the actual fix); this partial unique index is the backstop —
-- if that lock is ever bypassed or a future code path writes `active`
-- directly, the SECOND commit fails loudly with a clear constraint
-- violation instead of silently corrupting which model is "the" active
-- one for a family.
--
-- Safe on an existing database: at most one `active` row per family is
-- already the intended invariant everywhere in the codebase, so no
-- current data should violate this (if it does, the ticket is real and
-- this migration is supposed to surface it, not hide it).
--
-- Idempotent: guarded so re-running on an already-migrated database is
-- a no-op.

CREATE UNIQUE INDEX IF NOT EXISTS ux_model_versions_one_active_per_family
    ON atlas.model_versions (family)
    WHERE stage = 'active';

-- Rollback:
--
-- BEGIN;
-- DROP INDEX IF EXISTS atlas.ux_model_versions_one_active_per_family;
-- COMMIT;
