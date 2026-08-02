# FEATURE-COMMUNITIES-V1 — CONTRACT MATRIX (Gateway público ↔ Social ↔ Flutter)

Boundary: Flutter → **Gateway (único contrato público)** → Social gRPC. Atlas fora.

## Rotas gateway HOJE
| Método | Rota | Social RPC | Retorno | Consumidor Flutter |
|---|---|---|---|---|
| GET | /v1/hub/bundle?segment= | Community.List/ListForUser + Discussion + tipsters | HubBundle | HubScreen |
| GET | /v1/hub/communities/{id} | Community.Get + Discussion.ListForCommunity | community+discussions | CommunityDetailScreen |

## Rotas gateway A CRIAR (Stage 2)
| Método | Rota (proposta) | Social RPC | Notas |
|---|---|---|---|
| POST | /v1/hub/communities/{id}/join | Community.Join (user_id server-derived via X-User-Id) | idempotente; retorna membership + counts |
| DELETE | /v1/hub/communities/{id}/membership | Community.Leave | idempotente |
| GET | /v1/hub/communities/{id}/members | **ListMembers (novo RPC)** | keyset; is_moderator flag; sem admins (inexistente) |
| GET | /v1/hub/communities/{id}/stats | derivar de Community + counts | honesto: member_count/active_now |
| GET | /v1/hub/communities/capabilities | — | enabled/absent (posts_feed absent até decisão) |
| GET | /v1/hub/communities/{id}/feed | **decisão de design** | posts.community_id OU discussions |

## Lacunas de contrato (CONTRACT_MISSING)
1. `members` — Flutter exige, gateway não envia (BUG). Corrigir contrato + modelo.
2. ListMembers — RPC inexistente no social.
3. join/leave — existem no social, não no gateway.
4. community feed de posts — sem linkage posts↔community.
5. capabilities/stats — inexistentes.

## Invariantes a preservar
- Identidade do viewer sempre server-derived (X-User-Id), nunca do corpo do cliente.
- Gateway define DTO canônico (sem vazar shapes internos do social).
- Deep links construídos só pelo gateway; Flutter valida contra rotas reais (padrão SEARCH-V1).
- Moderação/visibilidade reaproveitando o lens do feed onde houver posts.

---
## STAGE 1 — decisões de contrato registradas (Social)
- **Members NÃO entram no detalhe da comunidade.** O bug latente (Flutter exigia `members` que o gateway não
  envia) será corrigido nos Stages 2/3 assim: o **detalhe** retorna CONTADORES (member_count/active_now e
  contagem por papel) e no máximo um **preview explicitamente contratado**; a **aba Membros** consome o
  endpoint paginado próprio (`ListMembers`). Nada de lista completa de membros no detalhe (payload/paginação).
- **ListMembers (novo, Social)**: `rpc ListMembers(ListCommunityMembersRequest) → ListCommunityMembersResponse`.
  Keyset determinístico (role priority ASC → joined_at ASC → user_id ASC), sem offset, sem N+1 (JOIN users).
  Retorna `CommunityMemberProfile` (só campos públicos). Filtro opcional `role` = projeção owner/admin/mod na
  MESMA query (sem 3 RPCs paralelos).
- **owner_user_id** em Community (opcional; ausente = OWNER_UNASSIGNED). **role** em CommunityMember (fonte de
  verdade); **is_moderator** mantido derivado (compat), remoção futura.
- **CreateTopic** ganha `owner_user_id` (obrigatório; gateway deriva do X-User-Id, nunca do cliente).
