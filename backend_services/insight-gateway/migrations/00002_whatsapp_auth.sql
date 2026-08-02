-- 00002_whatsapp_auth — WhatsApp-style OTP auth.
--
-- Ports atrium-py alembic revision 20260528_0002_whatsapp_auth.
--
-- Up:
--   * Drops password_hash + failed_logins_since from auth_credentials.
--   * Adds phone_e164 (unique, indexed) as the durable identifier.
--   * Creates auth_otp_challenges for short-lived OTP rows.
--
-- TRUNCATE in the up path is intentional and matches the alembic
-- revision: the column flip from optional password to required phone
-- can't backfill safely for existing rows. V1 is pre-launch — any data
-- there is throwaway. NEVER replay this migration against populated
-- production data; the goose marker prevents that by recording it as
-- already applied.

-- +goose Up
-- +goose StatementBegin
TRUNCATE TABLE auth_credentials;

ALTER TABLE auth_credentials DROP COLUMN IF EXISTS password_hash;
ALTER TABLE auth_credentials DROP COLUMN IF EXISTS failed_logins_since;

ALTER TABLE auth_credentials
    ADD COLUMN phone_e164 VARCHAR(20) NOT NULL;

ALTER TABLE auth_credentials
    ADD CONSTRAINT uq_auth_credentials_phone_e164 UNIQUE (phone_e164);

CREATE INDEX IF NOT EXISTS ix_auth_credentials_phone_e164
    ON auth_credentials (phone_e164);

CREATE TABLE IF NOT EXISTS auth_otp_challenges (
    id                  UUID PRIMARY KEY,
    phone_e164          VARCHAR(20) NOT NULL,
    code_hash           VARCHAR(128) NOT NULL,
    provider            VARCHAR(32) NOT NULL,
    provider_message_id VARCHAR(128),
    attempts            INTEGER NOT NULL DEFAULT 0,
    max_attempts        INTEGER NOT NULL DEFAULT 5,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMPTZ NOT NULL,
    consumed_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_auth_otp_challenges_phone_e164
    ON auth_otp_challenges (phone_e164);
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP INDEX IF EXISTS ix_auth_otp_challenges_phone_e164;
DROP TABLE IF EXISTS auth_otp_challenges;

DROP INDEX IF EXISTS ix_auth_credentials_phone_e164;
ALTER TABLE auth_credentials DROP CONSTRAINT IF EXISTS uq_auth_credentials_phone_e164;
ALTER TABLE auth_credentials DROP COLUMN IF EXISTS phone_e164;

ALTER TABLE auth_credentials
    ADD COLUMN password_hash VARCHAR(256) NOT NULL DEFAULT '';
ALTER TABLE auth_credentials
    ADD COLUMN failed_logins_since INTEGER NOT NULL DEFAULT 0;
-- +goose StatementEnd
