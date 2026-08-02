# AZTECA-QUALITY-A — Avatar End-to-End Forensic Trace

## ROOT CAUSE: **OBJECT_STORAGE_CONFIGURATION_FAILURE** (C)
Proven with live, read-only evidence. Object storage (MinIO) is **not provisioned** in the deployed Cloud
environment and the Gateway has no `MINIO_ENDPOINT`, so by the current Gateway design the avatar route is
silently de-registered and the (correct) Flutter client receives a **404** — indistinguishable to the user
from "this feature doesn't exist."

## Chain classification
| Step | Result | Evidence |
|---|---|---|
| Flutter Edit/Avatar action → picker → preview → confirm | PASS | `profile_screen.dart` state machine (ready/uploading/error), buttons disabled while busy (no dup submit) |
| Image validation (mime allow-list) | PASS | `avatar_service.dart` jpeg/png/webp; `MediaType.parse` |
| Multipart request (field `file`, content-type) | PASS | `MultipartFile.fromFile` + `FormData{'file':…}` → `POST /v1/users/me/avatar` |
| Auth header | PASS | `_AuthInterceptor` attaches Bearer |
| Response DTO parse (`avatar_url`) | PASS (code) | parses + rejects empty |
| **Gateway route registration** | **FAIL** | Live: `POST/GET /v1/users/me/avatar` → **404** while control `/v1/users/me/preferences` → **401** (proves not an edge artifact; route genuinely unregistered). Gateway healthy (healthz 200). |
| avatarStore initialization | **NOT REACHED** | `main.go`: block runs only `if settings.MinioEndpoint != ""`. Read-only SSH: gateway container has **no `MINIO_*` env**; **no `avatar_store_*` startup log** (block skipped entirely). |
| MinIO / object storage | **FAIL (absent)** | Read-only SSH `docker ps`: **no minio/s3/storage container** on the instance. |
| Object write → Social UpdateAvatar → avatar_updated_at → versioned URL | NOT REACHED | upstream of the missing route |
| Provider invalidation / cache eviction | PASS (code) | `evictAvatarFromCache` + `authProvider.updateAvatar` + invalidate profile/feed/sports-profile |

## Why the client is NOT at fault
The request construction, mime, auth, and DTO handling are all correct. The 404 is produced by the Gateway
before any handler runs, because the route does not exist in the deployed binary's routing table.

## Live probe method (safe, non-mutating)
- Unauthenticated `POST/GET /v1/users/me/avatar` → 404 (no body, no auth, no state change).
- Control unauthenticated `GET /v1/users/me/preferences` → 401 (a known auth-gated route) — proves the
  edge/proxy passes through and auth-gated routes return 401, so the avatar 404 = genuine route absence.
- Read-only SSH (`gcloud compute ssh`): `docker ps` (no MinIO), `docker inspect` env NAMES (no MINIO_*),
  `docker logs` (no avatar_store events). No values printed; nothing mutated.

## Deployed versions
Gateway `konohalabs/insight-gateway:0.1.13`; Social `konohalabs/insight-social:0.1.8`; both up ~6h; instance
`instance-20260604-195317` (us-central1-c).
