# AZTECA-QUALITY-A — Stage 0 Baseline Revalidation

Audit hypotheses (AZTECA-V1-AUDIT-A) checked against current code + live env.

| Audit finding | Status | Evidence |
|---|---|---|
| 6 failing tests (stale nav + feed harness) | **CONFIRMED** | Live run: api_client env default, widget_test/home_screen/launch_flow assert `FloatingBottomNav` (0 found). |
| Production nav = FixedBottomNav | **CONFIRMED** | `shell.dart:84` mounts `FixedBottomNav`; `FloatingBottomNav` widget orphaned (only tests referenced it). |
| Theme session-only (not persisted) | **CONFIRMED** | `settings_provider.dart` was a bare `StateProvider<ThemeMode>` w/ "Not yet persisted" comment. |
| Local persistence facility exists | **CONFIRMED** | `flutter_secure_storage` (TokenStorage, ComposerDraftStore) — reused; no new dependency. |
| Legal org = KonohaLabs (user-facing) | **CONFIRMED** | `legal.dart:99,122` (liability, data controller) + `settings_screen.dart:255` (About). |
| Avatar client correct | **CONFIRMED** | `avatar_service.dart`: multipart field `file`, mime allow-list, auth via interceptor, parses `{avatar_url}`. |
| Gateway avatar route conditionally registered | **CONFIRMED + DEEPENED** | `main.go`: registered only `if avatarStore != nil` (nil when MINIO_ENDPOINT empty / init / bucket fail). |
| Avatar failure = operational/backend | **CONFIRMED (proven root cause)** | Live: route 404 vs control 401; gateway has NO `MINIO_*` env; **no MinIO container deployed**. |
| IDENTITY-B deployed | **CONFIRMED** | Live: `/v1/users/{id}/sports-profile` → 401 (registered); DB has `avatar_updated_at`; social 0.1.8. |
| Edit Profile → avatar-only | **CONFIRMED (out of scope; POSTS-B/PROFILE-B)** | `profile_screen.dart:226` onEdit=_pickAndUpload. Not changed here. |

## Changed since audit
- Deployed versions are gateway **0.1.13** / social **0.1.8** (SOCIAL-A2 "CASE A" was deployed) — so this
  sprint's avatar Gateway fix lands as **gateway 0.1.14**.

## Unknown requiring live validation (resolved this sprint)
- Avatar root cause (config vs runtime): **RESOLVED** via read-only SSH — object storage not provisioned at all.
- IDENTITY-B field-level payload after avatar update: **BLOCKED_BY_ENVIRONMENT** (avatar upload impossible w/o MinIO) — documented manual smoke.

Deployment policy honored: only read-only probes/SSH/gcloud were used; nothing was mutated or deployed.
