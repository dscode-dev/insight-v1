#!/usr/bin/env bash
#
# seed_goose_marker.sh — one-shot cutover script (Phase 4 / W1.2 pre-flight).
#
# Run this AFTER:
#   * atrium-py has stopped applying alembic migrations
#   * Postgres `insight_auth` has 20260522_0001_init + 20260528_0002_whatsapp_auth
#     applied via alembic.
#
# Run this BEFORE:
#   * insight-gateway starts with AUTO_APPLY_MIGRATIONS=true.
#
# What it does:
#   1. Creates the goose_db_version tracking table if missing.
#   2. Marks goose revisions 1 and 2 as already applied — so the
#      gateway's `goose up` is a no-op against this schema.
#   3. Drops alembic_version to prevent dual tracking.
#
# Idempotent — re-runs are no-ops. Safe to ship as a K8s Job.

set -euo pipefail

PG_URL="${DATABASE_URL:?DATABASE_URL must be set (postgresql://...)}"

# Verify the expected schema state before touching anything.
echo "▶ verifying schema preconditions..."
read -r -d '' PRECONDITION_SQL <<'SQL' || true
SELECT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'auth_credentials'
      AND column_name = 'phone_e164'
);
SQL

if ! psql "$PG_URL" -tA -c "$PRECONDITION_SQL" | grep -q '^t$'; then
    echo "✗ auth_credentials.phone_e164 column missing — schema isn't at the expected" >&2
    echo "  state. Apply alembic 20260528_0002_whatsapp_auth first, then re-run." >&2
    exit 2
fi

echo "✓ schema state verified."

echo "▶ seeding goose_db_version..."
psql "$PG_URL" <<'SQL'
BEGIN;

CREATE TABLE IF NOT EXISTS goose_db_version (
    id          SERIAL PRIMARY KEY,
    version_id  BIGINT NOT NULL,
    is_applied  BOOLEAN NOT NULL,
    tstamp      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- The 0 row is goose's bookkeeping baseline.
INSERT INTO goose_db_version (version_id, is_applied)
SELECT 0, true
WHERE NOT EXISTS (
    SELECT 1 FROM goose_db_version WHERE version_id = 0
);

-- Mark migrations 1 and 2 as applied — DO NOT re-run them; the
-- TRUNCATE in 00002 would wipe live data.
INSERT INTO goose_db_version (version_id, is_applied)
SELECT v.id, true
FROM (VALUES (1::bigint), (2::bigint)) AS v(id)
WHERE NOT EXISTS (
    SELECT 1 FROM goose_db_version WHERE version_id = v.id
);

-- Drop alembic_version to prevent confusion. Only atrium-py read this
-- table, and atrium-py is being retired during the Strangler cutover.
DROP TABLE IF EXISTS alembic_version;

COMMIT;
SQL

echo "✓ goose marker seeded. Gateway can now boot with AUTO_APPLY_MIGRATIONS=true."
echo "  Future migrations apply from id=3 onward."
