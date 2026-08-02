# AZTECA-PROFILE-B — Stage 0 Baseline

Verified against real code (schema is authoritative). Repos: azteca-flutter, insight-social, insight-gateway.

## Decisive schema finding — what the backend ACTUALLY models
`users` columns (migrations 00001/00003/00008): `id, username, display_name, initials, accent_color,
reputation, tier, created_at, avatar_url, avatar_updated_at`. **No `bio`, no `location`, no `favorite_team`,
no per-user `role` column.** (`bio` exists only on `agent_profiles`, not `users`.)

The sports-profile handler (`sports_profile.go`) is already honest: `role` = always `"supporter"` (V1
default, not per-user persisted), `location`/`favorite_team` = `null` ("not modelled yet → null … never
fabricated"). Counts (followers/following/communities/posts/signals) are real subqueries over
`relationships`, `community_members`, `posts`, `signals`.

## Editable-field matrix
| Field | Owner | Modeled | Readable | Writable(pre) | Writable(now) | Class | V1 |
|---|---|---|---|---|---|---|---|
| display_name | Social users | ✓ | ✓ | ✗ | **✓ (this sprint)** | CORE_IDENTITY | EDIT |
| username | Social users | ✓ | ✓ | ✗ | ✗ | CORE_IDENTITY | DEFER (deep-link/uniqueness safety) |
| avatar | Social + storage | ✓ | ✓ | ✓ (upload) | ✓ (upload) | CORE_IDENTITY | EDIT (in-form action) |
| accent_color | Social users | ✓ | ✓ | gRPC only (not gw-exposed) | ✗ | CORE_IDENTITY | DEFER (needs picker UI) |
| bio | — | ✗ | ✗ | ✗ | ✗ | OUT_OF_SCOPE | DEFER (unmodeled) |
| location | — | ✗ | null | ✗ | ✗ | OUT_OF_SCOPE | DEFER (unmodeled) |
| favorite_team | — | ✗ | null | ✗ | ✗ | OUT_OF_SCOPE | DEFER (unmodeled; needs canonical team relation) |
| role | — (const) | ✗ | "supporter" | ✗ | ✗ | SPORTS_IDENTITY | DEFER (not persisted) |
| reputation/level/tier | Social | ✓ | ✓ | ✗ | ✗ | DERIVED_METRIC | NEVER editable |
| followers/following/communities/posts/signals | projections | ✓ | ✓ | ✗ | ✗ | RELATIONSHIP/PROJECTION | NEVER editable |

## Edit button (the product problem)
`profile_screen.dart` `OwnerProfileActions(onEdit: _pickAndUpload)` → the Edit button opened the AVATAR
PICKER directly. **Fixed this sprint** → opens the real Edit Profile screen.

## Existing write surface
`UpdateAvatar` (gRPC + gateway `/v1/users/me/avatar`), `UpdateAccent` (gRPC, NOT gateway-exposed),
preferences `GET/PUT /v1/users/me/preferences`. **No display_name write anywhere** → added.

## Preserved prior fixes (verified present)
Gateway QUALITY-A avatar fix (`avatarStorageUnavailable`, always-registered route, 503) committed = 0.1.14.
Social POSTS-B feed self-post fix present = 0.1.9. Both untouched; this sprint is additive/cumulative.
