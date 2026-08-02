# FEATURE-COMMUNITIES-V1 — Deploy Runbook (USER-OPERATED)

Agent NÃO faz deploy nem aplica migration. Cumulativo — preserva SEARCH-V1 e fixes anteriores.

## Repos alterados
- **insight-social**: migration 00011 + roles/owner + ListMembers/GetStats/GetMembership.
- **insight-gateway**: pacote `communitybff` (orchestrator) + rotas.
- **insight-azteca-flutter**: feature `features/hub/community/` + CommunityDetailScreen evoluída.
- **insight-protos**: `community.proto` (aditivo; stubs gitignored, path-replace).

## Linhagem de versões (confirmar working-tree antes de taguear)
Code-ready anterior (SEARCH-V1): social 0.1.11 / gateway 0.1.16. Communities soma por cima →
**proposto: social 0.1.12 / gateway 0.1.17** + build Flutter. Operador confirma a realidade do repo antes de
fixar as tags.

## Build
```
cd modules_v1
docker build --platform linux/amd64 -f insight-social/Dockerfile  -t konohalabs/insight-social:0.1.12 .
docker build --platform linux/amd64 -f insight-gateway/Dockerfile -t konohalabs/insight-gateway:0.1.17 .
docker push konohalabs/insight-social:0.1.12
docker push konohalabs/insight-gateway:0.1.17
flutter build ipa --dart-define=ENVIRONMENT=production   # / appbundle
```
Nota proto: stubs consumidos por path-replace; CI/build gera via buf (buf.gen.local.yaml). Local:
`protoc-gen-go@v1.34.2 + protoc-gen-go-grpc@v1.5.1 + buf` (ver STAGE1/2 evidence).

## Ordem de deploy (ver Operational Readiness)
1. **Migration 00011**: `sudo docker compose up -d migrate` → confirmar exit 0 + log aplica 00011.
2. **Social** → 0.1.12; `sudo docker compose up -d insight-social`.
3. **Gateway** → 0.1.17; `sudo docker compose up -d insight-gateway`.
4. **nginx reload**: `sudo docker exec insight-cloud-nginx nginx -s reload`.
5. **App Flutter**.

## Health checks
- migrate log: 00011 aplicada.
- social `/healthz` 200.
- gateway `/healthz` 200; log `community_routes_registered`; restarts 0.
- `GET /v1/hub/communities/{id}` (authed) → agregado com capabilities.

## Rollback
social→imagem anterior (manter 00011), gateway→0.1.16, app→build anterior. `goose down` só se necessário.

## Preservar (nunca regredir em rebuilds)
SEARCH-V1 (social 0.1.11/gateway 0.1.16), avatar 503, feed self-post, PATCH profile. As tags 0.1.12/0.1.17
são supersets cumulativos.
