#!/bin/sh
# Idempotent super-admin seed (ML-C Step 0). Runs automatically on first
# Postgres init. The password is read from $SUPER_ADMIN_PASSWORD (env, from
# .env) and stored ONLY as a bcrypt hash via pgcrypto crypt()/gen_salt('bf').
# The plaintext is never written to disk or to any report.
set -eu

: "${SUPER_ADMIN_USERNAME:=superadmin}"
: "${SUPER_ADMIN_EMAIL:=admin@insight.local}"
: "${SUPER_ADMIN_PASSWORD:?SUPER_ADMIN_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 \
  --set=super_admin_username="$SUPER_ADMIN_USERNAME" \
  --set=super_admin_email="$SUPER_ADMIN_EMAIL" \
  --set=super_admin_password="$SUPER_ADMIN_PASSWORD" \
  --username "$POSTGRES_USER" \
  --dbname gateway <<'SQL'
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS operators (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username      TEXT UNIQUE NOT NULL,
  email         TEXT UNIQUE NOT NULL,
  role          TEXT NOT NULL DEFAULT 'operator',
  password_hash TEXT NOT NULL,
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Idempotent and synchronizing: re-running with a rotated .env password
-- updates the stored hash so operator credentials do not drift.
INSERT INTO operators (username, email, role, password_hash, is_active, updated_at)
VALUES (
  :'super_admin_username',
  :'super_admin_email',
  'super_admin',
  crypt(:'super_admin_password', gen_salt('bf', 12)),
  TRUE,
  now()
)
ON CONFLICT (username) DO UPDATE SET
  email = EXCLUDED.email,
  role = 'super_admin',
  password_hash = EXCLUDED.password_hash,
  is_active = TRUE,
  updated_at = now();
SQL

echo "[seed] super_admin '${SUPER_ADMIN_USERNAME}' ensured (role=super_admin, password hash synchronized)"
