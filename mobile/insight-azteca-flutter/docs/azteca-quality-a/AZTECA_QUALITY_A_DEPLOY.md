# AZTECA-QUALITY-A — Manual Deployment Runbook (USER-OPERATED)

The agent did NOT deploy. Two independent tracks: Flutter (app build) and Gateway (backend, optional but
recommended to fix the avatar 404→503 semantics). **The avatar feature also requires provisioning MinIO —
a separate infra step the agent cannot and did not perform.**

## Track A — Flutter app (required)
- Repo: insight-azteca-flutter. No backend dependency. No migration.
- Changes: theme persistence, legal→AllBlue-Labs (+version 1.2), avatar error UX, test baseline.
- Build (example): `flutter build ipa --dart-define=ENVIRONMENT=production` / `flutter build appbundle …`.
- Store: confirm **publisher = AllBlue-Labs** in App Store Connect / Play Console listing. The Terms/Privacy
  version bump (1.2) re-triggers EULA acceptance at register — expected.
- Rollback: previous app build/version.

## Track B — Gateway avatar-route fix (recommended)
- Repo: insight-gateway. **No migration.** Change: `POST /v1/users/me/avatar` now ALWAYS registered; returns
  503 `CAPABILITY_UNAVAILABLE` when object storage is unavailable (instead of a silent 404).
- Current deployed tag: `konohalabs/insight-gateway:0.1.13` → build **0.1.14**.
```
cd modules_v1
docker build --platform linux/amd64 -f insight-gateway/Dockerfile -t konohalabs/insight-gateway:0.1.14 .
docker push konohalabs/insight-gateway:0.1.14
```
- Deploy (GCloud VM instance-20260604-195317, compose /home/darlansimplicio/Insight): backup compose → bump
  insight-gateway tag → `sudo docker compose up -d insight-gateway` → **nginx reload**
  `sudo docker exec insight-cloud-nginx nginx -s reload`.
- Health: `/healthz` 200; log `avatar_upload_route_registered_degraded_storage_unavailable` (until MinIO is
  wired) OR `avatar_upload_route_registered` (once MinIO is wired).
- Smoke: unauth `POST /v1/users/me/avatar` → **401** (was 404); authed w/o MinIO → **503**
  `avatar_storage_unavailable`; the Flutter app shows "Envio de foto indisponível no momento."
- Rollback: redeploy `konohalabs/insight-gateway:0.1.13`.

## Track C — Provision object storage (required to make avatar upload actually work; infra)
Root cause of avatar failure = **no MinIO deployed + no MINIO_ENDPOINT**. To enable uploads:
1. Deploy a MinIO (or S3-compatible) service reachable from the Gateway.
2. Set Gateway env: `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY_ID`, `MINIO_SECRET_ACCESS_KEY`, `MINIO_BUCKET`,
   `MINIO_USE_SSL`, `MINIO_PUBLIC_BASE_URL`, `AVATAR_MAX_BYTES`.
3. Recreate insight-gateway → confirm log `avatar_store_ready` + route returns 401 (unauth) / works (authed).
This is a deliberate infra decision for the operator; the agent only diagnosed it.

## Deployment order
Track A (app) is independent. Track B before/independent of C. Full avatar functionality needs B + C.

## Migration rollback
None — no migration in this sprint.
