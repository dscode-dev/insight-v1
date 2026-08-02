# FEATURE-COMMUNITIES-V1 — Post-Deploy Smoke (operator-run)

Autenticado como usuário real. $B=gateway base, $TOK=access token. Não logar segredos.

## Banco (Social host)
1. Colunas: `\d+ communities` mostra `owner_user_id`; `\d+ community_members` mostra `role` (+ is_moderator).
2. Índices: `\di ux_community_members_one_owner` · `ix_community_members_listing` · `ix_communities_owner_user_id`.
3. Backfill: `SELECT role,count(*) FROM community_members GROUP BY role;` → moderadores = antigos is_moderator.
4. OWNER_UNASSIGNED: `SELECT count(*) FROM communities WHERE owner_user_id IS NULL;` (legadas = sem owner, ok).

## API (curl via Gateway)
5. Detalhe agregado: `curl $B/v1/hub/communities/{id} -H "Authorization: Bearer $TOK"` →
   header + member_count/discussion_count/online_count + role_counts + viewer_role + membership_status +
   capabilities. **Sem** array `members`/`discussions`.
6. Membros: `.../{id}/members?limit=5` → lista paginada (next_cursor); `?role=admin` → só admins (mesmo endpoint).
7. Discussões: `.../{id}/discussions?limit=5` → feed de Discussions (nunca Posts).
8. Join: `curl -X POST .../{id}/join …` → membership_status=member + member_count+1 + capabilities atualizadas.
9. Leave: `curl -X DELETE .../{id}/membership …` → not_member. Owner → **409** (não pode sair).
10. Partial: derrube a projeção de stats (ou simule) → detalhe `partial:true` + `failed_sections:["stats"]`,
    tela não cai.
11. Rate limit: >60 leituras/10s no mesmo usuário → 429.
12. Deep links: cards trazem `/hub/community/{id}`, `/users/{id}`, `/discussion/{id}`.

## App
13. Abrir uma comunidade → header card aprovado + abas Sobre/Discussões/Membros/Estatísticas.
14. Membro/admin/owner: aba **Administração** aparece só quando permitido (can_view_admin_panel).
15. **Owner NÃO vê botão Sair**; não-membro vê **Entrar**; membro vê **Sair**.
16. Entrar → otimista (UI muda na hora) + confirma; forçar erro → **rollback**.
17. Membros: scroll infinito, filtro por role, sem duplicatas; empty/erro com retry.
18. Discussões: card próprio (respostas/reações/atividade) — NÃO é card de Post.
19. Trocar de aba → estado preservado, header não recarrega.
20. Tap em membro → abre perfil; tap em comunidade a partir do Search → abre este detalhe.
21. Offline/timeout → estados corretos por seção; a tela inteira não falha.
22. Dark/light mode + texto ampliado → identidade preservada.

## Preservação (não-regressão)
23. Explore, Feed Global, Perfil, Hub bundle, Atlas — inalterados.
