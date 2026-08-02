-- +goose Up
-- +goose StatementBegin
--
-- Sprint C — User avatar URL.
--
-- avatar_url stores the FULL URL of the uploaded image (e.g.
-- `https://cdn.insight.local/avatars/<user_id>.jpg`). The gateway is
-- responsible for the upload + URL minting; this column is only
-- read/written via User.UpdateAvatar.
--
-- Nullable: users without an uploaded avatar fall back to the
-- initials+accentColor rendering already in the Flutter InsightAvatar.

ALTER TABLE users ADD COLUMN avatar_url TEXT;
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
ALTER TABLE users DROP COLUMN IF EXISTS avatar_url;
-- +goose StatementEnd
