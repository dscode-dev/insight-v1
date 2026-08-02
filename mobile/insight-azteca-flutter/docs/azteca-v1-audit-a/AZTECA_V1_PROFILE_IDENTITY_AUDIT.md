# AZTECA V1 — Profile & Identity Forensic Audit (Stage 3)

## Sports identity (REAL)
`sportsProfileProvider` → `social_service.sportsProfile` → `GET /v1/users/{id}/sports-profile` returns a
grouped payload (IDENTITY-B): identity, versioned avatar URL, role, reputation, level, and grouped stats
(followers/following/communities/posts/signals), favoriteTeam, location. Owner + public profile share the
same header/read model (`profile_screen.dart`, `user_profile_screen.dart`). Follow/unfollow real. This is
one of the most complete domains.

## ⚑ Avatar upload — failure boundary (do not guess)
Client path is CORRECT: `avatar_service.dart` → `POST /v1/users/me/avatar` multipart (mime allow-list
jpeg/png/webp) → expects `{avatar_url}` → persists on AuthUser → `avatar_cache.evictAvatarFromCache` +
provider invalidation. Versioned avatar URL (`?v=`) already threaded through feed/profile reads (IDENTITY-B).
**Failure boundary is server-side + environment-dependent:** the Gateway registers the avatar route
CONDITIONALLY — `insight-gateway/cmd/gateway/main.go:540` `if avatarStore != nil { … register POST
/v1/users/me/avatar }`. `avatarStore` is nil when `MINIO_ENDPOINT` is empty, or init fails, or the bucket
is unavailable (`main.go:193-214`, logs `avatar_store_init_failed_route_skipped` /
`avatar_store_bucket_unavailable_route_skipped`). ⇒ If the deployed Gateway lacks a healthy MinIO, the
route is **absent** and the Flutter POST returns 404 → the observed "avatar upload fails."
**Classification: UNKNOWN — REQUIRES LIVE VALIDATION of MinIO wiring in the deployed Gateway.** The exact
diagnostic: check for `avatar_upload_route_registered` in gateway logs; if absent, MinIO is the cause (infra,
not Flutter). No client change can fix a missing route. Secondary client hardening (later): surface a
precise "avatar service unavailable" message on 404 instead of a generic error.

## ⚑ Edit Profile misroute (CONFIRMED)
`profile_screen.dart:226` — `OwnerProfileActions(onEdit: _pickAndUpload, …)`. The "Editar perfil" button
(`profile_actions.dart:35-42`) calls `_pickAndUpload` = image picker + avatar upload. **There is NO profile
editing form.** Backend editable-field reality:
- Avatar: `POST /v1/users/me/avatar` (conditional).
- Preferences: `GET/PUT /v1/users/me/preferences` (locale/push/email/digest) — REAL.
- Accent color: social `UpdateAccent` exists (verify Gateway exposure).
- display_name / bio / favoriteTeam / location: **no `PATCH /v1/users/me` profile-edit contract found** →
  CLIENT+BACKEND MISSING for a full edit form. Contract boundary for AZTECA-PROFILE-B: add
  `PATCH /v1/users/me` (display_name, bio, favorite_team, location) + keep avatar as a sub-action; the Edit
  button must open a form, not the picker.

## Profile tabs (visual design accepted — audit content only)
- **Atividades** (`_ActivityTab`, `profile_screen.dart:112`/`291`) → `userPostsProvider` → `GET /v1/users/
  {id}/posts`. **REAL persisted posts** — the reliable recovery surface (independent of feed ranking). Only
  posts are backed; comments/replies/boosts/follows/joins as activity types have **no activity endpoint** →
  do NOT surface them until a real activity contract exists. V1: keep Atividades = posts (truthful).
- **Comunidades**: placeholder text "Comunidades que você segue aparecem aqui. Encontre uma na aba Hub."
  (`profile_screen.dart:120`). No membership retrieval; `hub_service` is mock. **SUPERFICIAL** — depends on
  AZTECA-COMMUNITIES-A backend (membership list). Keep honest-empty until then.
- **Estatísticas**: grouped stats from sports-profile (followers/following/communities/posts/signals +
  reputation + role). **REAL profile/social metrics.** These are NOT sports-intelligence metrics (no
  probabilities/trends here). `signals`/`communities` counts may be 0 until those domains exist — render
  honestly, never fabricate.

## Verdict
Profile/Identity is PARTIAL-strong: identity/stats/activity/public profile real; blockers are the Edit
misroute (needs a real edit contract+form) and the avatar route's MinIO dependency.
