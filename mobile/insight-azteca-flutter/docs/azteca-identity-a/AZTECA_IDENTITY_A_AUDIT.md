# AZTECA-IDENTITY-A — Stage 0: Identity Domain Audit

## Service ownership (NO duplicate endpoints created)
| Capability        | Owner (data)            | Exposed by (BFF)                              | Endpoint |
|-------------------|-------------------------|----------------------------------------------|----------|
| Profile (user)    | **insight-social** (`user` svc) | gateway `GetUser`                    | `GET /v1/users/{id}` |
| Own identity      | **insight-social** + auth | gateway `/v1/profile/me/bundle` (flagged), auth | `GET /v1/profile/me/bundle` |
| Avatar upload     | **insight-gateway** (`avatarstore` → MinIO) + persists URL to **social** `UpdateAvatar` | gateway | `POST /v1/users/me/avatar` |
| User preferences  | **insight-social** (`preferences` svc/repo) | gateway proxy                 | `GET/PUT /v1/users/me/preferences` |
| Follows / counts  | **insight-social** (`relationshiprepo`) | gateway `follow/unfollow`         | `POST/DELETE /v1/follow/{id}` |
| Sports identity (location, favorite team, followers/following/communities counts) | **NOT MODELLED** anywhere yet | — | — |

## insight-anvil
**Not part of the Identity domain.** Anvil is the analytics worker (consumes Atlas derived events →
ClickHouse: market_snapshots / metric_ticks). The "identity/lineage" references are ClickHouse event
lineage columns, unrelated to user identity. No profile/avatar/preferences responsibilities. Excluded.

## Key findings
1. **Avatar object key is STABLE per user** (`avatars/<uuid>.<ext>`) → re-upload returns the SAME URL →
   Flutter's image cache served STALE bytes (no eviction existed anywhere). Root cause of "avatar
   doesn't update everywhere". Fix is **client-side** (cache eviction + targeted refresh) — no backend
   change, no deploy.
2. Feed already returns the live author avatar (`feedrepo`: `COALESCE(a.avatar, u.avatar_url)`), so once
   the cache is evicted + the feed refetches, the new avatar appears — no schema change needed.
3. Preferences (push/email/digest/locale) are **remote** (social, synced). Theme is **local**
   (`themeModeProvider`, device-only). Already separate data sources — clarified in the UI.
4. location / favorite team / followers / following / communities counts are **not in the backend**.
   Per spec they stay **nullable** in the unified model; not fabricated. (A future social HTTP count
   endpoint + a versioned avatar URL are the durable backend follow-ups — out of scope, would need deploy.)

## Conclusion
No duplicate endpoints needed. The Identity integration gap is **client-side** (avatar cache + refresh
propagation + unified model consumption). Backend ownership is correct and reused as-is.
