# AZTECA-IDENTITY-A — Smoke Test & Classification

## Classification: **PARTIAL**
Integration code is complete and `flutter analyze` is clean. No backend service changed, so **no
image build/deploy is required** (Stages 6–7 satisfied: Flutter-only; nothing to deploy). The
remaining items (Stage 5 production validation + Stage 8 on-device smoke) require running the app on a
device/emulator against the deployed Google Cloud gateway with real credentials — which cannot be
executed from this environment. Steps below are ready for the operator to run.

## What changed (Flutter-only, no backend)
- `core/avatar_cache.dart` — `evictAvatarFromCache(url)`: removes the stable avatar URL from the image
  cache so re-uploads fetch fresh bytes.
- `profile_screen.dart` upload success → evict(old+new) + `updateAvatar` + invalidate
  `profileBundleProvider` + `feedProvider`. Avatar now propagates to profile + feed with no restart;
  comments/replies re-resolve against the evicted cache on next open.
- `settings_screen.dart` — theme group labelled **local (device-only)**; notification/language remain
  **remote** (synced via `/v1/users/me/preferences`). Local vs remote no longer ambiguous.
- Unified model: `ProfileIdentity` (AZTECA-PROFILE-A) consumed by both own + public profiles;
  location/team/followers/following/communities are **nullable** (backend doesn't provide them) — not
  fabricated.

## Statically verified (this environment)
- [x] Domain ownership mapped; anvil excluded; no duplicate endpoints introduced.
- [x] Avatar endpoint `POST /v1/users/me/avatar` exists in gateway (MinIO `avatarstore` + social
      `UpdateAvatar`); registered when `MINIO_ENDPOINT` is configured.
- [x] `GET/PUT /v1/users/me/preferences` and `GET /v1/users/{id}` exist in the gateway.
- [x] `flutter analyze` — No issues found.

## Operator production smoke (run against https://insight-api.konohalabs.com.br — NOT localhost)
Backend reachability (curl, with a valid bearer token `$T`):
```
curl -s -H "Authorization: Bearer $T" https://insight-api.konohalabs.com.br/v1/users/me/preferences | jq .
curl -s -H "Authorization: Bearer $T" https://insight-api.konohalabs.com.br/v1/users/<id> | jq .
```
On-device (release build pointing at production):
1. Own Profile loads (avatar/name/@username/reputation/level).
2. **Avatar upload** → pick → preview → send. Avatar updates on the profile header immediately.
3. Navigate to Feed → your authored posts show the **new** avatar (no restart, no manual refresh).
4. Open a thread you commented on → your comment avatar is the new one.
5. Settings: toggle Push/E-mail, change Frequency + Language → re-open app → values **persisted**
   (remote). Change Theme → persists only on this device (local).
6. Public Profile (tap another user) → loads; Follow/Unfollow round-trips; stats shown.
7. App restart → all identity changes persisted.

## To reach READY
Run the operator smoke above against Google Cloud and confirm all 7 pass. (Optional durable backend
follow-ups, each requiring a deploy: a versioned avatar URL `?v=<updated_at>` so caches bust without
client eviction, and a social HTTP `followers/following/communities` count endpoint to light up the
currently-null Sports Identity metrics.)
