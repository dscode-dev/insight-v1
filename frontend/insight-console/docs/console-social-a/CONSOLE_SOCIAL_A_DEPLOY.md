# CONSOLE-SOCIAL-A — Deployment (Stage 26)

**Status: NOT EXECUTED this phase.** CONSOLE-SOCIAL-A delivered the mandatory forensic audit +
architecture design (Stages 0-3, 16-23 design). No production service code was changed, so there is
nothing to build/push/deploy in this phase — and per the sprint's own rule, deployment without real
implementation would be fabrication.

## Deploy plan for the implementation phase (grounded in the audit)
1. **Phase 1 (gateway-only, low risk):** add `/v1/console/social/{overview,users,agents}` BFF over
   existing social gRPC → build `insight-gateway:0.1.11` → `docker save`/`gcloud scp`/`load` on the
   cloud VM → recreate (rollback 0.1.10). No social change, no migration.
2. **Phase 2 (social + gateway):** add social admin read endpoints (`posts/comments/activity/boosts/
   investigation/timeline` projections) → build `insight-social:0.1.6` (+ additive index migration if
   EXPLAIN warrants) → deploy to cloud (preserve DB/volumes; `social-migrate` one-shot) → gateway
   proxy → verify health/restarts.
3. **Console:** build `insight-console:0.3.20` → push to `konohalabs` registry → `docker pull` +
   compose recreate on Robozão (compose `/home/insight/compose`, service `console`, no sudo needed;
   registry pull required — the direct link is ~12 KB/s). Rollback 0.3.19.

Current baseline (unchanged): gateway 0.1.10, social 0.1.5, console 0.3.19, atlas 1.0.0 FROZEN.
