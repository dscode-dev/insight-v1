# CONSOLE-FOUNDATION-A — Live Dual-Environment Validation (read-only)

Performed read-only against both production environments. No mutations, no restarts, no Atlas
replay submits, no Social writes, no DB changes.

## Robozão (SSH)
- `docker ps` = **exactly** the registry's `robozao` services (9): insight-atlas 1.0.0, console
  0.3.18, explorer 0.0.20, nexus 0.0.2, robozao-gateway 0.0.2, sport-hub 0.0.3, postgres
  (pgvector/pg16), redis 7.4, qwen/ollama. **Registry topology matches live reality.**
- **Atlas adapter target** `GET /health` → `{"service":"atlas","status":"healthy"}` — parsed by
  `AtlasAdapter` to `health:"healthy"`. Atlas **1.0.0 unmodified** (read-only).
- **Explorer adapter target** `GET /health` → `{"status":"ok","service":"insight-explorer",
  "version":"0.0.2",...}` — parsed by `ExplorerAdapter` (`mapHealth("ok")→healthy`, version surfaced).
- robozao-gateway container present (operations protocol target).

## Google Cloud (gcloud + public edge)
- `docker ps` (VM `instance-20260604-195317`) = **exactly** the registry's `google-cloud` services
  (7): insight-gateway 0.1.9, social 0.1.5, anvil 0.1.0, cloud-postgres/redis/clickhouse, cloud-nginx.
  **Registry topology matches live reality.**
- **Gateway adapter target** existence (read-only, unauth): `GET /healthz` → **200** (reachable);
  `GET /v1/console/platform/health` → **401** (route exists + gated, not 404);
  `GET /v1/console/admin/users` → **401**. The adapter targets a real, auth-gated endpoint and no
  data is returned unauthenticated.

## Degradation tolerance
- Nexus has no `NEXUS_API_BASE_URL` in the current deploy ⇒ registry reports `configured:false`; the
  snapshot reports Nexus honestly (unknown), **not** a fake healthy — matching the "optional source
  unavailable without collapse" requirement. Unit tests additionally prove one timeout / one 503
  yields honest partial state with the rest intact.

## Secrets check
No secrets appear in any browser-visible response: public registry models and the snapshot omit
endpoints/tokens (unit-tested); unauth gateway probes return 401, never data.

**Live verdict:** registry topology matches both live environments; adapters read real, responding,
correctly-gated endpoints; Atlas remains frozen/unmodified; partial degradation is honest.
