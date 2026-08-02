-- +goose Up
-- +goose StatementBegin
--
-- AZTECA-IDENTITY-B — versioned avatars.
--
-- The avatar object key is stable per user (avatars/<uuid>.<ext>), so a
-- re-upload returns the SAME URL and clients cache it forever. Recording WHEN
-- the avatar last changed lets every read append `?v=<epoch>` to the URL, so a
-- new upload yields a new URL → automatic cache invalidation everywhere
-- (feed / comments / replies / own + public profile), no app restart, no manual
-- refresh, and no duplicated uploads (the object key stays stable).
--
-- Nullable + no backfill: existing avatars have NULL avatar_updated_at, so reads
-- emit the bare URL (unchanged behaviour) until the next upload stamps it.
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_updated_at TIMESTAMPTZ;
-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
ALTER TABLE users DROP COLUMN IF EXISTS avatar_updated_at;
-- +goose StatementEnd
