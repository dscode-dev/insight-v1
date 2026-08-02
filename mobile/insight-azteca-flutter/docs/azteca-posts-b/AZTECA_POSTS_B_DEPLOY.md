# AZTECA-POSTS-B — Manual Deployment Runbook (USER-OPERATED)

The agent did NOT deploy. Cumulative version lineage preserved.

## Repos changed this sprint
- insight-social (feed self-post semantics) — **required**.
- insight-azteca-flutter (Activity real posts + reconciliation) — **required** (app build).
- insight-gateway — **NOT changed this sprint**, but its committed 0.1.14 (QUALITY-A avatar fix) is still
  undeployed; deploy it too (independent, carries the avatar 404→503 fix). **Never build a gateway image that
  drops `avatarStorageUnavailable`.**

## Migrations
**None** in this sprint (feed fix is code-only; no schema change; no media migration — GIF deferred).

## Build order + suggested tags
```
cd modules_v1
# Social — deployed 0.1.8 → next 0.1.9 (feed self-post fix)
docker build --platform linux/amd64 -f insight-social/Dockerfile  -t konohalabs/insight-social:0.1.9  .
docker push konohalabs/insight-social:0.1.9
# Gateway — deployed 0.1.13 → 0.1.14 (QUALITY-A avatar fix; unchanged by POSTS-B)
docker build --platform linux/amd64 -f insight-gateway/Dockerfile -t konohalabs/insight-gateway:0.1.14 .
docker push konohalabs/insight-gateway:0.1.14
# Flutter — app build
flutter build ipa --dart-define=ENVIRONMENT=production   # / appbundle
```

## Deploy order (GCloud VM instance-20260604-195317, compose /home/darlansimplicio/Insight)
1. Backup compose.
2. Bump insight-social → 0.1.9; `sudo docker compose up -d insight-social`.
3. Bump insight-gateway → 0.1.14; `sudo docker compose up -d insight-gateway`.
4. **nginx reload** (gateway recreated): `sudo docker exec insight-cloud-nginx nginx -s reload`.
5. Ship the Flutter app build.

## Health checks
- `/healthz` 200; social up; gateway logs `console_operations_routes_registered` + (avatar)
  `avatar_upload_route_registered_degraded_storage_unavailable` (until MinIO provisioned).

## Route smoke (read-only)
- `POST /v1/users/me/avatar` unauth → **401** (was 404) — confirms 0.1.14.
- Authenticated: create a post → it appears in `/v1/feed/global` (own post now returned) AND
  `/v1/users/{id}/posts`; open the app → post visible in Home feed AND Profile▸Atividades; survives refresh.

## Rollback
- Social → 0.1.8; Gateway → 0.1.13 (note: reverts the avatar 404→503 fix too). No migration rollback (none).

## Note
Avatar upload still requires MinIO provisioning (QUALITY-A infra follow-up) — independent of POSTS-B.
