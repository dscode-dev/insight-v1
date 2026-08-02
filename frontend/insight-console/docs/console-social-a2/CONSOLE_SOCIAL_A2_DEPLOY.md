# CONSOLE-SOCIAL-A2 — User-Operated Deployment Runbook

**DO NOT auto-executed by the agent.** The user runs these. Additive, read-only, no migrations.

## 1. Services changed
insight-social (7 read handlers), insight-gateway (7 proxy routes + no signature change), insight-console
(adapters/services/BFF/UI/nav/caps).

## 2. Repos changed
insight-social, insight-gateway, insight-console.

## 3-4. Migrations
**NONE.** No schema change. No migration order.

## 5-7. Build / suggested tags / push (current deployed → next)
- insight-social 0.1.6 → **0.1.7**
- insight-gateway 0.1.11 → **0.1.12**
- insight-console 0.3.20 → **0.3.21**
```
cd modules_v1
docker build --platform linux/amd64 -f insight-social/Dockerfile   -t konohalabs/insight-social:0.1.7  .
docker build --platform linux/amd64 -f insight-gateway/Dockerfile  -t konohalabs/insight-gateway:0.1.12 .
docker build --platform linux/amd64 -f insight-console/Dockerfile  -t konohalabs/insight-console:0.3.21 insight-console
# console via registry (Robozão link is slow); cloud via save/load or push:
docker push konohalabs/insight-console:0.3.21
```

## 8. Google Cloud (VM instance-20260604-195317, compose /home/darlansimplicio/Insight)
Transfer social+gateway (docker save|gcloud scp|docker load OR push+pull). Bump compose tags
(insight-social→0.1.7, insight-gateway→0.1.12; backup compose first). Recreate:
`sudo docker compose up -d insight-social insight-gateway`. Then **nginx reload**
`sudo docker exec insight-cloud-nginx nginx -s reload` (gateway recreate → re-resolve upstream).

## 9. Robozão (compose /home/insight/compose, service `console`)
`docker pull konohalabs/insight-console:0.3.21` → bump tag (backup compose) →
`docker compose up -d console`.

## 10-12. Health / edge / logs
- `/healthz`→200; social `http_listen :8080`; gateway `console_operations_routes_registered`;
  console health=healthy, "Ready". restarts must be 0.
- nginx reload only if gateway container was recreated.
- Check gateway/social/console logs for errors/panics.

## 13-14. Rollback
Redeploy insight-social 0.1.6, insight-gateway 0.1.11, insight-console 0.3.20 (restore compose
backups). **No migration rollback needed** (no migration was applied).

## 15. Post-deploy smoke
Run CONSOLE_SOCIAL_A2_SMOKE.md.
