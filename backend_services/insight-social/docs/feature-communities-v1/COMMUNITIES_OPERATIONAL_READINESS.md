# FEATURE-COMMUNITIES-V1 — Operational Readiness

## Ordem de deploy (obrigatória)
1. **Migration 00011** (Social DB) — aditiva; ver Migration Safety.
2. **Social** (imagem com roles/owner + ListMembers/GetStats/GetMembership).
3. **Gateway** (imagem com communitybff orchestrator).
4. **App Flutter** (feature de comunidade).

Racional: cada camada depende da anterior. O Gateway chama RPCs Social novos (2→3); o App chama rotas Gateway
novas (3→4); as rotas Social dependem das colunas da migration (1→2).

## Dependências entre serviços
- Gateway `communitybff` → Social gRPC (`Community.GetStats/GetMembership/ListMembers/Join/Leave/Get`,
  `Discussion.ListForCommunity`). Social indisponível → detalhe 502/504 (tratado).
- Social → Postgres (migration 00011 aplicada). Sem a migration, `GetStats`/`role` falham.
- Atlas: NÃO envolvido.

## Pontos de rollback
- App → build anterior.
- Gateway → 0.1.16 (pré-communitybff); a rota antiga de detalhe volta (community+discussions).
- Social → imagem anterior; **manter 00011 aplicada** (imagens antigas ignoram coluna/tabela novas).
- Migration → `goose down` só se necessário (remove role/owner/índices; is_moderator e dados preservados).

## Impacto de indisponibilidade PARCIAL
- **GetStats fora** → detalhe volta `partial=true` + `failed_sections:["stats"]`; contadores degradam ao core
  (member/online da própria community); role_counts/discussion_count zeram. Tela NÃO cai.
- **GetMembership fora** → `partial` + viewer tratado como not_member (best-effort); capabilities conservadoras.
- **Members/Discussions fora** → a respectiva aba mostra estado de erro com retry; header e demais abas seguem.
- **Community core (Get) fora** → é o único erro "duro" → 404/502 no detalhe (correto: sem comunidade não há tela).

## Rollout gradual — comportamento cruzado (CRÍTICO)
### Gateway atualizado ANTES do App (App antigo + Gateway novo)
- App antigo chama `GET /v1/hub/communities/{id}` e recebe o AGREGADO novo (sem `members`/`discussions`).
  O modelo antigo exigia `members` → **parse falha** → tela de detalhe do App antigo fica indisponível.
- **MAS**: esse App antigo JÁ estava quebrado em produção nessa tela (bug do `members` — nunca funcionou em
  modo gateway). Ou seja: **não há regressão de funcionalidade real** — um contrato quebrado é substituído por
  um correto. As demais telas do App antigo (Hub bundle, feed, search, perfil) seguem intactas.
- Recomendação: publicar o App novo junto/logo após o Gateway para restaurar a tela de detalhe.

### App atualizado ANTES do Gateway (App novo + Gateway antigo)
- App novo chama `GET /v1/hub/communities/{id}` e recebe o shape ANTIGO (`{community, discussions}`). O novo
  `CommunityDetail.fromJson` **aplica default a toda chave ausente** (contadores→0, capabilities→false,
  viewer_role→none, membership_status→not_member) → **NÃO quebra**; renderiza um detalhe degradado (sem
  contadores/ações, aba Administração oculta pois canViewAdminPanel=false).
- App novo chama `/members`, `/discussions`, `/join`, `/membership` → Gateway antigo responde 404 → essas abas
  mostram **estado de erro com retry** (falha isolada, não derruba a tela).
- Resultado: **degrada com segurança, sem crash.** Restaura ao subir o Gateway novo.

Conclusão: ambas as ordens são tolerantes (sem crash). A ordem canônica (Gateway antes do App) minimiza a
janela degradada.

## Observabilidade no deploy
- Gateway log `community_routes_registered`.
- Métricas: `community_requests_total{endpoint}`, `community_latency_seconds`, `community_cache_events_total`,
  `community_partial_responses_total`, `community_upstream_timeouts_total`, `community_rate_limited_total`.
- Alertas sugeridos: subida de `partial_responses` (Social/stats instável) e de `upstream_timeouts`.
