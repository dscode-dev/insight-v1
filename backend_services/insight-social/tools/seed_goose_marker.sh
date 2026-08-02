#!/usr/bin/env bash
# seed_goose_marker.sh — cutover plaza-py alembic → insight-social goose.
#
# Run ONCE per environment, immediately before flipping the Strangler
# flag for the first social.v1 endpoint from plaza-py to social-go.
#
# Semantics:
#   1. Asserts the schema looks like plaza-py rev 20260522_0001 (the
#      `users` + `signals` tables exist with their expected columns).
#      If the assertion fails the script bails — we never want to
#      seed a marker against an unfamiliar schema.
#   2. Creates goose_db_version if missing.
#   3. Marks `00001_init.sql` as applied (version_id=1) — but only if
#      not already there. Re-runnable safely.
#   4. Drops alembic_version. plaza-py is frozen from this point.
#
# Usage:
#   DATABASE_URL=postgres://... ./tools/seed_goose_marker.sh
#
# Same shape as insight-gateway/tools/seed_goose_marker.sh — kept
# in sync intentionally so the SRE runbook is one script per service.
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is required (the insight_social DB)}"

PSQL_BIN="${PSQL_BIN:-psql}"
if ! command -v "$PSQL_BIN" >/dev/null 2>&1; then
    echo "error: $PSQL_BIN not on PATH" >&2
    exit 1
fi

echo "[cutover] verifying plaza-py schema is present..."
read -r -d '' VERIFY_SQL <<'SQL' || true
SELECT 1
FROM information_schema.columns
WHERE table_schema = current_schema()
  AND table_name = 'users'
  AND column_name = 'reputation';
SQL
if ! "$PSQL_BIN" "$DATABASE_URL" -At -c "$VERIFY_SQL" | grep -q '^1$'; then
    echo "error: expected plaza-py users.reputation column not found." >&2
    echo "       Refusing to seed goose marker against unknown schema." >&2
    exit 2
fi

read -r -d '' VERIFY_SIGNALS_SQL <<'SQL' || true
SELECT 1
FROM information_schema.columns
WHERE table_schema = current_schema()
  AND table_name = 'signals'
  AND column_name = 'weight_multiplier';
SQL
if ! "$PSQL_BIN" "$DATABASE_URL" -At -c "$VERIFY_SIGNALS_SQL" | grep -q '^1$'; then
    echo "error: expected plaza-py signals.weight_multiplier column not found." >&2
    exit 2
fi

echo "[cutover] schema OK. ensuring goose_db_version table..."
read -r -d '' CREATE_GOOSE_SQL <<'SQL' || true
CREATE TABLE IF NOT EXISTS goose_db_version (
    id          SERIAL PRIMARY KEY,
    version_id  BIGINT      NOT NULL,
    is_applied  BOOLEAN     NOT NULL,
    tstamp      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
SQL
"$PSQL_BIN" "$DATABASE_URL" -c "$CREATE_GOOSE_SQL" >/dev/null

echo "[cutover] seeding 00001_init marker if absent..."
read -r -d '' SEED_SQL <<'SQL' || true
INSERT INTO goose_db_version (version_id, is_applied)
SELECT 1, TRUE
WHERE NOT EXISTS (
    SELECT 1 FROM goose_db_version WHERE version_id = 1 AND is_applied = TRUE
);
-- goose expects a baseline row at version 0 too (created automatically
-- on first `goose status`, but seeding here keeps idempotency tight).
INSERT INTO goose_db_version (version_id, is_applied)
SELECT 0, TRUE
WHERE NOT EXISTS (
    SELECT 1 FROM goose_db_version WHERE version_id = 0
);
SQL
"$PSQL_BIN" "$DATABASE_URL" -c "$SEED_SQL" >/dev/null

echo "[cutover] dropping alembic_version (plaza-py is frozen now)..."
"$PSQL_BIN" "$DATABASE_URL" -c "DROP TABLE IF EXISTS alembic_version;" >/dev/null

echo "[cutover] done. goose now owns insight_social migrations."
echo "         next steps:"
echo "           - run \`make db-status\` to confirm version 1 applied"
echo "           - flip Strangler flag for the first social.v1 endpoint"
