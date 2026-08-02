-- +goose Up
-- +goose StatementBegin
--
-- FEATURE-COMMUNITIES-V1 Stage 1 — canonical community roles + ownership.
--
-- Additive and safe. Introduces:
--   * communities.owner_user_id  — explicit owner reference + fast lookup.
--     NULLABLE during the compatibility phase: legacy communities (and
--     competition communities) have no deterministic creator on record, so
--     they are classified OWNER_UNASSIGNED and left NULL. NEW topic
--     communities are created with a non-NULL owner + an OWNER membership in
--     the SAME transaction (enforced in the repository, not here).
--   * community_members.role — the SOURCE OF TRUTH for authorization and
--     presentation (owner | admin | moderator | member).
--
-- is_moderator is DELIBERATELY KEPT for wire/back-compat. It is backfilled
-- and stays in sync (role in {moderator,admin,owner} => is_moderator=true),
-- but callers must stop treating it as the source of truth. Its removal is
-- future work, only after Social + Gateway + Azteca all read `role`.
--
-- Owner uniqueness is enforced structurally by a PARTIAL UNIQUE INDEX:
-- at most one OWNER membership per community. The owner_user_id column is
-- kept consistent with that single OWNER row inside the write transactions.

-- ---- ownership reference on the community ----
ALTER TABLE communities
    ADD COLUMN IF NOT EXISTS owner_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL;

-- ---- canonical role on the membership ----
ALTER TABLE community_members
    ADD COLUMN IF NOT EXISTS role VARCHAR(16) NOT NULL DEFAULT 'member'
        CHECK (role IN ('owner', 'admin', 'moderator', 'member'));

-- Deterministic backfill: existing moderators become MODERATOR; everyone
-- else stays MEMBER. No community gains an owner here — there is no
-- deterministic creator on legacy rows (choosing the first member/moderator
-- would be arbitrary and is explicitly disallowed). Owners are assigned
-- operationally (see OWNER_UNASSIGNED strategy in the migration doc).
UPDATE community_members SET role = 'moderator' WHERE is_moderator = TRUE AND role = 'member';

-- At most ONE owner per community (structural guarantee).
CREATE UNIQUE INDEX IF NOT EXISTS ux_community_members_one_owner
    ON community_members (community_id)
    WHERE role = 'owner';

-- Members listing keyset support: ORDER BY role-priority, joined_at, user_id.
-- (role priority is computed in SQL; this index accelerates the per-community
-- scan + the joined_at/user_id tiebreak.)
CREATE INDEX IF NOT EXISTS ix_community_members_listing
    ON community_members (community_id, joined_at, user_id);

-- Fast "is this user the owner / find the owner" lookups.
CREATE INDEX IF NOT EXISTS ix_communities_owner_user_id
    ON communities (owner_user_id) WHERE owner_user_id IS NOT NULL;
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP INDEX IF EXISTS ix_communities_owner_user_id;
DROP INDEX IF EXISTS ix_community_members_listing;
DROP INDEX IF EXISTS ux_community_members_one_owner;
ALTER TABLE community_members DROP COLUMN IF EXISTS role;
ALTER TABLE communities DROP COLUMN IF EXISTS owner_user_id;
-- +goose StatementEnd
