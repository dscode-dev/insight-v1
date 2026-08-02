-- 00005_legal_acceptance — Gateway-Auth-B.1 legal acceptance persistence.
--
-- Adds separate Privacy and UGC policy versions plus a unified accepted_legal_at
-- timestamp. The legacy accepted_terms_at column is left in place for
-- non-breaking rollout and copied forward when present.

-- +goose Up
-- +goose StatementBegin
ALTER TABLE auth_credentials
    ADD COLUMN IF NOT EXISTS accepted_privacy_version VARCHAR(32);
ALTER TABLE auth_credentials
    ADD COLUMN IF NOT EXISTS accepted_ugc_policy_version VARCHAR(32);
ALTER TABLE auth_credentials
    ADD COLUMN IF NOT EXISTS accepted_legal_at TIMESTAMPTZ;

UPDATE auth_credentials
SET accepted_legal_at = accepted_terms_at
WHERE accepted_legal_at IS NULL
  AND accepted_terms_at IS NOT NULL;
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
ALTER TABLE auth_credentials DROP COLUMN IF EXISTS accepted_legal_at;
ALTER TABLE auth_credentials DROP COLUMN IF EXISTS accepted_ugc_policy_version;
ALTER TABLE auth_credentials DROP COLUMN IF EXISTS accepted_privacy_version;
-- +goose StatementEnd
