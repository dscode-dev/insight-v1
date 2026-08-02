# CONSOLE-SECURITY-A1 — Deployment Record

## Gateway (Google Cloud) — DEPLOYED
- **Image:** `konohalabs/insight-gateway:0.1.10` — built locally `--platform linux/amd64`
  (`sha256:0d321b46bc71…`, bundles migration 00007). Transferred via `docker save|gzip` → `gcloud
  compute scp` → `docker load` (VM image id `5ec087105e7b`). Registry-independent (push not required).
- **Compose:** `/home/darlansimplicio/Insight/docker-compose.yml` (backup `docker-compose.yml.pre-a1`);
  gateway + gateway-migrate tags bumped 0.1.9 → 0.1.10.
- **Migration:** `gateway-migrate` (goose) → `OK 00007_operator_audit_canonical.sql`, "successfully
  migrated database to version: 7", exit 0. **52 pre-existing audit rows preserved**; 8 canonical
  columns + idempotency unique index verified.
- **Service token:** `CONSOLE_SERVICE_TOKEN` was **absent** in the cloud gateway `.env` (root cause of
  a 503 admin surface). Set = the Console's `ADMIN_API_INTERNAL_TOKEN` (64 chars) via a stdin-piped
  temp file (secret never in any command/output); `.env` backup `.env.pre-a1`.
- **State:** `insight-gateway` running, **restarts=0**, `console_operations_routes_registered`,
  `http_listen :8080`, no errors. nginx reloaded (fixed transient stale-upstream 404 after container
  recreate).
- **Rollback:** redeploy `konohalabs/insight-gateway:0.1.9` (image `4b1a5e8e5392`, still on VM) +
  restore `.pre-a1` files.

## Console (Robozão) — DEPLOYED
- **Image:** `konohalabs/insight-console:0.3.19` (`sha256:ec32812…`, linux/amd64, 161 MB). Transferred
  `docker save|gzip | ssh 'gunzip|docker load'`. Prior `0.3.18` retained for rollback.
- **Change:** durable audit factory default = `GatewayAuditRepository` (no silent memory fallback);
  Explorer operator-bound adapter; moderation fail-closed on non-durable audit intent.
- **Deploy:** recreate `insight-console` via its compose; verify health + audit read route.
- **Rollback:** redeploy `0.3.18`.

## Restrictions honored
Atlas 1.0.0 untouched. No executor, `execution_enabled=false`. No unrelated services deployed.
Additive migration only; no audit history destroyed. Registry not required (save/load).
