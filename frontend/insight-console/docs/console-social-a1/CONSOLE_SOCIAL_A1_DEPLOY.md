# CONSOLE-SOCIAL-A1 — Deployment Record

## Images (built linux/amd64)
| Service | Tag | Digest | Rollback |
|---------|-----|--------|----------|
| insight-social | 0.1.6 | (loaded via save/load) | 0.1.5 `ea7690ced9fe` |
| insight-gateway | 0.1.11 | sha256 pushed | 0.1.10 `482a0ff38ca3` |
| insight-console | 0.3.20 | sha256:4e9b472f1703c32c431fdb7ea7fb2afca18adeba46d729fede37956f88bf6962 | 0.3.19 |

## Google Cloud (VM instance-20260604-195317, compose /home/darlansimplicio/Insight)
- social 0.1.6 + gateway 0.1.11: `docker save`→`gcloud scp`→`docker load`; compose tags bumped
  (backup docker-compose.yml.pre-social-a1); `docker compose up -d insight-social insight-gateway`;
  nginx `-s reload` (gateway recreate → re-resolve upstream). Both running, **restarts=0**. No
  migration (read-only). DB/volumes preserved. Gateway `SOCIAL_HTTP_BASE_URL` default resolves.

## Robozão (compose /home/insight/compose, service `console`)
- console 0.3.20: pushed to konohalabs registry → `docker pull` → compose tag bump (backup
  .pre-social-a1) → `docker compose up -d console`. Running, **health=healthy, restarts=0**, "Ready".

## Verification
Gateway `console_operations_routes_registered`; social `http_listen :8080`; app edge + auth unaffected.
Atlas 1.0.0 untouched; execution_enabled false; no unrelated services restarted.
