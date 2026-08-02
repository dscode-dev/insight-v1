# CONSOLE-SOCIAL-B — User-Operated Deployment Runbook

**DO NOT auto-executed by the agent.** The user performs deployment. This sprint changes ALL THREE
repos and adds ONE additive Social migration.

## 1. Repositories changed
insight-social, insight-gateway, insight-console.

## 2. Services changed
- insight-social: agent publication gate + agent-state endpoints + migration 00009 + metric.
- insight-gateway: operator command plane (13 endpoints) + enforcement-state read + gap-closing
  (like/follow/boost/save gate, post-detail filter) + moderation.Service extensions.
- insight-console: enforcement adapter/BFF (13 command routes + 1 read) + capabilities + intervention UX.

## 3. Migration files
- `insight-social/migrations/00009_agent_enforcement.sql` (additive: agent_profiles.deactivated_at/
  deactivated_reason columns + agent_state_events table + index). Backward-compatible; existing rows
  default active with NULL provenance. **No Gateway migration** (reuses Store-A moderation tables).

## 4. Exact migration order
Social migrations run via the existing goose `migrate` service before starting insight-social 0.1.x.
00009 depends only on 00005 (agent_profiles). No data backfill.

## 5. Compatibility window
- 00009 is additive → safe to apply BEFORE the new social image (old image ignores new columns/table).
- Gateway↔Social: the new gateway calls Social's new `POST /console/social/agents/{id}/{deactivate,
  reactivate}` — deploy social FIRST (or together). Old gateway + new social = harmless (endpoint unused).
- Console→Gateway: new console command routes call new gateway endpoints — deploy gateway before/with console.

## 6. Recommended deployment order
migrate(social 00009) → insight-social → insight-gateway → insight-console.

## 7. Build commands
```
cd modules_v1
docker build --platform linux/amd64 -f insight-social/Dockerfile   -t konohalabs/insight-social:<tag>   .
docker build --platform linux/amd64 -f insight-gateway/Dockerfile  -t konohalabs/insight-gateway:<tag>  .
docker build --platform linux/amd64 -f insight-console/Dockerfile  -t konohalabs/insight-console:<tag>  insight-console
```

## 8. Image tag recommendations (based on actual history; SOCIAL-A2 may or may not be deployed)
> **CASE A — SOCIAL-A2 already deployed** (live = social 0.1.7 / gateway 0.1.12 / console 0.3.21):
>   next = **social 0.1.8 / gateway 0.1.13 / console 0.3.22**.  Rollback = 0.1.7 / 0.1.12 / 0.3.21.
>
> **CASE B — A2 NOT yet deployed, ship A2+B together** (live = social 0.1.6 / gateway 0.1.11 / console
>   0.3.20): next = **social 0.1.7 / gateway 0.1.12 / console 0.3.21**.  Rollback = 0.1.6 / 0.1.11 / 0.3.20.
>
> Verify the live tags before tagging: `docker compose images` on each host. Do not guess live state.

## 9. Push
```
docker push konohalabs/insight-social:<tag>
docker push konohalabs/insight-gateway:<tag>
docker push konohalabs/insight-console:<tag>   # Robozão is registry-pull (slow link)
```

## 10. Google Cloud (VM instance-20260604-195317, compose /home/darlansimplicio/Insight)
1. Transfer social+gateway images (push+pull or save|scp|load).
2. Backup compose. Bump insight-social + insight-gateway tags.
3. `sudo docker compose up -d migrate` (applies social 00009) → confirm exit 0.
4. `sudo docker compose up -d insight-social insight-gateway`.
5. **nginx reload** (gateway recreated ⇒ re-resolve upstream): `sudo docker exec insight-cloud-nginx nginx -s reload`.

## 11. Robozão Console (ssh ninja@insight-robozao.konohalabs.lab, compose /home/insight/compose)
`docker pull konohalabs/insight-console:<tag>` → backup compose → bump `console` tag →
`docker compose up -d console`.

## 12. Health checks
- social `/healthz` 200; log `http_listen`; migrate log shows `00009` applied.
- gateway `/healthz` 200; log `console_operations_routes_registered`; restarts 0.
- console health=healthy, "Ready".

## 13. Log checks
gateway/social/console for panics/errors; confirm `moderation_routes_registered` +
`console_operations_routes_registered`.

## 14. Edge reload
Only if the gateway container was recreated (step 10.5). Console (Robozão) has its own nginx/basePath;
reload only if the console container name/upstream changed (normally not needed for a tag bump).

## 15. Rollback image references
CASE A: social 0.1.7 / gateway 0.1.12 / console 0.3.21. CASE B: social 0.1.6 / gateway 0.1.11 / console 0.3.20.

## 16. Migration rollback limitations
00009 is additive; `goose down` drops agent_state_events + the two columns (loses agent enforcement
HISTORY only — no user/content/report data). Prefer leaving 00009 applied on rollback (old images ignore it).

## 17. Cross-version compatibility notes
- Old gateway + new social: agent-state endpoints unused; publication gate active (safe — only blocks
  already-deactivated agents, of which there are none until an operator acts).
- New gateway + old social: agent commands 502 (endpoint missing) until social updated; user/content/
  report commands work (Gateway-owned). Deploy social first to avoid this.
- New console + old gateway: command routes 404 upstream → surfaced as honest errors (no fake success).
