# AZTECA-PROFILE-B — Manual Deployment Runbook (USER-OPERATED)

Agent did NOT deploy. Cumulative — preserves QUALITY-A avatar fix + POSTS-B feed fix.

## Repos changed
- insight-social (PATCH /users/me/profile handler + route) — required.
- insight-gateway (PATCH /v1/users/me proxy) — required.
- insight-azteca-flutter (Edit Profile + reconciliation + completeness) — app build.

## Migrations
**None** (display_name column already exists; no schema change).

## Build + tags (cumulative)
```
cd modules_v1
# Social 0.1.8 deployed → 0.1.10 (POSTS-B feed fix + PROFILE-B PATCH handler)
docker build --platform linux/amd64 -f insight-social/Dockerfile  -t konohalabs/insight-social:0.1.10 .
# Gateway 0.1.13 deployed → 0.1.15 (QUALITY-A avatar 503 + PROFILE-B PATCH proxy)
docker build --platform linux/amd64 -f insight-gateway/Dockerfile -t konohalabs/insight-gateway:0.1.15 .
docker push konohalabs/insight-social:0.1.10
docker push konohalabs/insight-gateway:0.1.15
flutter build ipa --dart-define=ENVIRONMENT=production   # / appbundle
```

## Deploy order (GCloud VM instance-20260604-195317, compose /home/darlansimplicio/Insight)
1. Backup compose. 2. Bump social → 0.1.10; `sudo docker compose up -d insight-social`.
3. Bump gateway → 0.1.15; `sudo docker compose up -d insight-gateway`.
4. **nginx reload**: `sudo docker exec insight-cloud-nginx nginx -s reload`. 5. Ship the app build.

## Health + smoke
- `/healthz` 200. Gateway logs: `avatar_upload_route_registered_degraded_storage_unavailable` (MinIO absent),
  route registration log.
- `PATCH /v1/users/me` unauth → **401** (was 405) confirms the new route is live.
- Authenticated (test account): `PATCH /v1/users/me {"display_name":"New Name"}` → 200 echo; then
  `GET /v1/users/{id}/sports-profile` shows the new name; app profile header + feed author label update.
- `POST /v1/users/me/avatar` unauth → 401 (QUALITY-A live); avatar upload still needs MinIO provisioning.

## Rollback
social → 0.1.8, gateway → 0.1.13 (note: reverts avatar 503 + feed fix + PATCH). No migration rollback (none).

## Preserve
Never build a gateway image missing `avatarStorageUnavailable`, or a social image missing the feed self-post
fix. 0.1.15 / 0.1.10 are cumulative supersets.
