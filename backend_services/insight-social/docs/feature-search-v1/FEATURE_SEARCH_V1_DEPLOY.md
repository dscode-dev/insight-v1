# FEATURE-SEARCH-V1 — Manual Deployment Runbook (USER-OPERATED)

Agent did NOT deploy. This is the full vertical (Stage 1 social + Stage 2 gateway + Stage 3 Flutter).
Cumulative — preserves every prior fix (QUALITY-A avatar 503, POSTS-B feed, PROFILE-B PATCH, INSIGHTS-A).

## Repos changed
- **insight-social**: migration 00010 + search domain/repo/service/handlers + routes.
- **insight-gateway**: `searchbff` Search Orchestrator + `/v1/search/*` routes.
- **insight-azteca-flutter**: Search Hub (app build).

## Working-tree reality (confirmed)
- Deployed: **gateway 0.1.13 / social 0.1.8**.
- Code-ready cumulative: **social 0.1.11** (0.1.10 PROFILE-B + Stage 1 search) ·
  **gateway 0.1.16** (0.1.15 PROFILE-B + Stage 2 orchestrator) · Flutter Search Hub build.

## Migration (Social 00010) — PRECONDITION
`00010_search.sql` runs `CREATE EXTENSION IF NOT EXISTS pg_trgm` (TRUSTED extension; the DB owner
`insight` can create it on PG≥13). It also adds a STORED generated `posts.search_tsv` (tsvector, GIN) +
trigram GIN indexes + `search_history`. **If the cluster forbids pg_trgm, goose aborts loudly** — verify
the role can create the extension before deploying (it can in the current Cloud topology).

## Build + tags
```
cd modules_v1
docker build --platform linux/amd64 -f insight-social/Dockerfile  -t konohalabs/insight-social:0.1.11 .
docker build --platform linux/amd64 -f insight-gateway/Dockerfile -t konohalabs/insight-gateway:0.1.16 .
docker push konohalabs/insight-social:0.1.11
docker push konohalabs/insight-gateway:0.1.16
flutter build ipa --dart-define=ENVIRONMENT=production   # / appbundle
```

## Deploy ORDER (matches the vertical dependency chain)
1. **Migration**: `sudo docker compose up -d migrate` (applies 00010) → confirm exit 0 + log shows 00010.
2. **Social** → `konohalabs/insight-social:0.1.11`; `sudo docker compose up -d insight-social`.
3. **Gateway** → `konohalabs/insight-gateway:0.1.16`; `sudo docker compose up -d insight-gateway`.
4. **nginx reload**: `sudo docker exec insight-cloud-nginx nginx -s reload`.
5. **Flutter** app build.

## Health checks
- social `/healthz` 200; migrate log 00010 applied.
- gateway `/healthz` 200; log `search_routes_registered`; restarts 0.
- `GET /v1/search/capabilities` (authed) → 200 with enabled[6] + blocked{teams,players} + trending UNAVAILABLE.

## Rollback
social → 0.1.8, gateway → 0.1.13, previous app build. Migration rollback: `goose down` drops search_history +
search_tsv + trigram indexes (search stops working; no other data lost). Prefer leaving 00010 applied if
rolling back only the app (older images ignore the new column/table).

## Preserve
Never build images dropping: avatarStorageUnavailable (gateway), feed self-post fix / PATCH profile (social).
0.1.16 / 0.1.11 are cumulative supersets (grep-confirmed present).
