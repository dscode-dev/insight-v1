# AZTECA-IDENTITY-B — Stage 0: Identity Audit

## Existing endpoints (reused/enriched — no duplicates created)
- `GET /v1/users/{id}` (gateway → social gRPC GetUser) — basic identity.
- `POST /v1/users/me/avatar` (gateway MinIO `avatarstore` + social `UpdateAvatar`) — upload.
- `GET/PUT /v1/users/me/preferences` (social) — remote settings.
- `POST/DELETE /v1/follow/{id}` (social `relationships`) — graph.
- Stats already existed only piecemeal: `userrepo.Stats` (signals/communities) + `profileBundle`.

## Schema facts used
- `users(reputation, accent_color, avatar_url, …)` — **no updated timestamp** for the avatar.
- `relationships(actor_id, target_id, kind='follow')` → followers (target) / following (actor).
- `community_members(user_id)` → communities; `posts(author_id, author_type='user', deleted_at)` → posts;
  `signals(author_id)` → signals.

## Decisions (prefer enrichment over new APIs; proto regen unavailable → HTTP-proxy)
1. **Versioned avatar**: add `users.avatar_updated_at`; append `?v=<epoch>` to `avatar_url` at the read
   sources (`userrepo` GetByID/List + UpdateAvatar RETURNING, `feedrepo` author avatar, new endpoint).
   NULL-guarded so legacy rows + tests keep the bare URL. Stamp it in `UpdateAvatar`.
2. **Enriched profile**: ONE new social HTTP read `GET /users/{id}/sports-profile` returning identity +
   grouped `stats{followers,following,communities,posts,signals}` + versioned avatar + `role`. This
   ENRICHES the profile contract (single payload) — not a duplicate statistics API. Gateway proxies it
   at `GET /v1/users/{userId}/sports-profile`. (gRPC User proto can't be extended — buf unavailable —
   so the HTTP-proxy pattern is used, consistent with competitions/save/boost.)
3. location/favorite_team stay **null** (not modelled) — never fabricated.
4. Settings: theme + image cache = LOCAL; preferences (notifications/language) = REMOTE. Kept separate.
