# FEATURE-COMMUNITIES-V1 — Public API (Gateway contract)

Boundary: Flutter → **Gateway (contrato público, DTOs próprios)** → Social gRPC. Nada de social.v1 vaza.
Todas as rotas exigem auth; o **viewer é a identidade verificada da sessão** (authmw), nunca do corpo.

## Matriz de endpoints (Community Orchestrator)
| Método | Rota | Retorno | Notas |
|---|---|---|---|
| GET | `/v1/hub/communities/{id}` | `Detail` (agregado) | fan-out Get+GetStats+GetMembership; partial honesto; SEM arrays |
| GET | `/v1/hub/communities/{id}/members` | `MembersPage` | keyset cursor; `?role=owner\|admin\|moderator\|member` projeção |
| GET | `/v1/hub/communities/{id}/discussions` | `DiscussionsPage` | feed da comunidade — **Discussions apenas** (ADR-0001) |
| POST | `/v1/hub/communities/{id}/join` | `MembershipResult` | user = sessão; devolve estado+capabilities |
| DELETE | `/v1/hub/communities/{id}/membership` | `MembershipResult` | leave; owner bloqueado (409) |

## Detail (agregado — NUNCA espelho do Social)
Campos: id, slug, name, description, avatar_url, banner_url (vazios honestos — comunidades não têm mídia no
domínio), accent_color, kind, **privacy="public"** (único valor V1), deep_link, **member_count**,
**discussion_count**, **online_count**, **role_counts{owner,admin,moderator,member}**, **viewer_role**,
**membership_status**, owner_assigned, **capabilities{...}**, partial + failed_sections.
- Header renderizável sem chamadas extras (nome, descrição, accent, contadores, viewer_role, membership).
- **Sem arrays** de membros/admins/moderadores (vêm de `/members` paginado).

## Capabilities (autorização centralizada no Gateway)
`can_join, can_leave, can_create_discussion, can_delete_discussion, can_manage_members, can_invite_members,
can_manage_settings, can_view_admin_panel`. O cliente só renderiza; enforcement final no domínio Social.
Regra-chave: **owner → can_leave=false** (transferência de ownership é capability ausente na V1).

## Partial / Timeout / Cache / Correlation / Rate limit
- **Partial**: falha de stats/membership → `partial=true` + `failed_sections`; o **core** (community) falho é
  erro (404). Membership NotFound = `not_member` (normal, não partial).
- **Timeout**: contexto por request (4s); DeadlineExceeded → 504 `community_upstream_timeout` + métrica.
- **Cache**: StatsCache por **community_id** (projeção user-independent); viewer_role/capabilities NUNCA
  cacheados; invalidado em join/leave.
- **Correlation**: contexto de entrada propaga a MESMA correlation id no fan-out; disconnect/timeout cancela
  todas as chamadas upstream (WaitGroup join, sem órfãs).
- **Rate limit**: 60 leituras/10s por usuário → 429 `community_rate_limited`.
- **Métricas Prometheus** (registry compartilhado): community_requests_total{endpoint},
  community_latency_seconds, community_cache_events_total{result}, community_partial_responses_total,
  community_upstream_timeouts_total{endpoint}, community_rate_limited_total.

## Deep links (Gateway constrói; Flutter só valida+navega)
community `/hub/community/{id}` · user `/users/{id}` · discussion `/discussion/{id}`.

## Editorial (ADR-0001) preservado
Feed da comunidade = Discussions. Nenhum feed híbrido, nenhum Post agregado no detalhe.
