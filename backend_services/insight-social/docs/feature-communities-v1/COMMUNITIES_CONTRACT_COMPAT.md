# FEATURE-COMMUNITIES-V1 — Contract Compatibility Report

Objetivo: provar que a vertical NÃO quebra contratos públicos. Todos os proto e DTO públicos evoluíram de
forma ADITIVA. `buf breaking --against HEAD` = PASS (nenhuma violação).

## Matriz de contratos

### social.v1 (proto interno Social↔Gateway) — TODOS ADITIVOS
| Contrato | Tipo | Situação |
|---|---|---|
| enum `CommunityRole` | **NOVO** | OWNER/ADMIN/MODERATOR/MEMBER/UNSPECIFIED |
| `Community.owner_user_id` (11, optional) | **NOVO campo** | aditivo; ausente = OWNER_UNASSIGNED |
| `CommunityMember.role` (5) | **NOVO campo** | aditivo; is_moderator (4) mantido |
| `CommunityMemberProfile` | **NOVO message** | usado por ListMembers |
| `CreateTopicCommunityRequest.owner_user_id` (5) | **NOVO campo** | aditivo (proto3 sem required) |
| `RoleCounts`, `CommunityStats` | **NOVO message** | usados por GetStats |
| `GetCommunityMembershipRequest`, `GetCommunityStatsRequest`, `ListCommunityMembersRequest/Response` | **NOVO message** | — |
| RPC `ListMembers`, `GetMembership`, `GetStats` | **NOVO RPC** | aditivo no CommunityService |
| RPCs existentes (List/Get/Join/Leave/CreateTopic/ListForUser) | inalterados na assinatura | Join/CreateTopic retornam campos novos (aditivos) |
| **Removidos** | — | **NENHUM** (buf breaking FIELD_NO_DELETE respeitado) |

### Gateway público (REST — contrato oficial do cliente)
| Rota | Tipo | Situação |
|---|---|---|
| `GET /v1/hub/communities/{id}` | **ALTERADO (shape)** | passou de `{community, discussions[]}` para o AGREGADO (header+counters+role_counts+viewer_role+membership_status+capabilities). Sem `members`/`discussions` embutidos |
| `GET /v1/hub/communities/{id}/members` | **NOVO** | paginado (cursor + ?role) |
| `GET /v1/hub/communities/{id}/discussions` | **NOVO** | feed (Discussions) |
| `POST /v1/hub/communities/{id}/join` | **NOVO** | — |
| `DELETE /v1/hub/communities/{id}/membership` | **NOVO** | — |
| `GET /v1/hub/bundle`, `GET /v1/discussions/*`, feed, search, profile | inalterados | fora do escopo |
| **Removidos** | — | **NENHUM** (a rota de detalhe manteve método+path; só o corpo evoluiu) |

Nota sobre a única mudança de shape (detalhe): o contrato ANTIGO de detalhe já era não-funcional em produção
(o modelo Flutter exigia `members`, que o Gateway nunca enviava → parse quebrava em modo gateway). A mudança
substitui um contrato quebrado por um agregado correto. Ver Operational Readiness para ordem de rollout.

### Flutter (após atualização dos modelos)
| Modelo | Situação |
|---|---|
| `CommunityDetail` (novo, features/hub/community) | **NOVO**; SEM `members` obrigatório (bug eliminado); todo campo ausente tem default (tolerante) |
| `CommunityCapabilities`, `RoleCounts`, `CommunityMember`, `CommunityDiscussion`, `MembersPage`, `DiscussionsPage`, `MembershipResult` | **NOVO** |
| `models/hub.dart` (`Community`/`Discussion`/`CommunityMember`/`CommunityDetail`, HubBundle) | **inalterado** — ainda usado pelo HubScreen (/v1/hub/bundle). O antigo `CommunityDetail` de hub.dart ficou órfão (não removido, sem quebra) |
| Search / Feed / Profile models | inalterados |

## Compatibilidade de parsing (tolerância a defaults)
`CommunityDetail.fromJson` e todos os sub-modelos aplicam default a CADA chave ausente (contadores→0,
capabilities→false, viewer_role→'none', membership_status→'not_member', listas→[]). Consequência: um App novo
apontado para um Gateway antigo NÃO quebra o parse (degrada). Ver Operational Readiness §gradual rollout.

## Conclusão
Contratos novos: vários (aditivos). Contratos alterados: 1 (shape do detalhe, substituindo contrato já
quebrado). Contratos removidos: **NENHUM**. `buf breaking` PASS. **Compatível.**
