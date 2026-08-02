# AZTECA-QUALITY-A — Error Model & User-Facing Failure Review

Goal: verify V1-core failures are not silently swallowed and are surfaced honestly. No global redesign.

## Transport error model (real)
`gateway_client.dart`: every non-2xx → `GatewayException{statusCode, detail}` (`_ErrorMapper`); transport
failures → `NetworkException`; refresh exhaustion → `TokenRefreshFailedException` (clears session → login).
Idempotent GETs retry (3×, backoff); mutations never auto-retry (caller owns). `errors.dart` exposes
`isUnauthorized/isForbidden/isNotFound/isRateLimited` — a real taxonomy.

## Per-flow surfacing
| Flow | Surfaced? | Classification handled |
|---|---|---|
| Login / OTP | Yes | validation, auth, timeout (auth screens) |
| Token refresh | Yes | auth → session cleared → login redirect |
| Feed load | Yes | error state + retry; offline flagged (`NetworkException`) |
| Create post | Yes | composer pending → failure state (no premature success) |
| Comments/replies | Yes | thread provider error/rollback |
| Like/Save/Boost | Yes | optimistic + rollback (interaction providers) |
| Profile load | Yes | ErrorState + retry |
| **Avatar upload** | **Yes (hardened this sprint)** | invalid-image (415) / too-large (413) / **service-unavailable (503)** / **auth (401)** / timeout / network / legacy-404 — all distinct (`avatarUploadErrorMessage`) |
| Follow/unfollow | Yes | AlreadyExists treated as success (retry-friendly) |
| Preferences | Yes | settings error tile + retry |

## Avatar distinctions (Stage 7 requirement — met)
`avatarUploadErrorMessage` (now top-level + tested) maps: 415→"Formato não aceito", 413→"Imagem grande
demais", **503/avatar_storage_unavailable/capability_unavailable→"Envio de foto indisponível no momento"**,
401→"Sua sessão expirou", timeout→"Tempo esgotado", network→"Verifique sua conexão", legacy-404→transient.

## Leakage check (test-enforced)
`avatar_error_message_test.dart` asserts no message contains host/`minio`/`bucket`/`token`/`http`/`package:`
/stack. Backend 503 body is `{"detail":"avatar_storage_unavailable","code":"CAPABILITY_UNAVAILABLE"}` — no
infra detail. Legal/policy sheets contain no secrets.

## Verdict
No silent swallowing found in V1-core flows. The one gap (avatar not distinguishing service-unavailable) is
closed. Error taxonomy is honest and leak-free.
