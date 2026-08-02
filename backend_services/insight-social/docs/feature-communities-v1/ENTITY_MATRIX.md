# FEATURE-COMMUNITIES-V1 — ENTITY MATRIX

| Entidade / Conceito | Existe? | Onde | Observações |
|---|---|---|---|
| Community | ✅ | social domain + DB `communities` | id/slug/name/topic/kind/competition_id/accent/member_count/active_now/created_at |
| Community.kind | ✅ | topic \| competition | competition auto-sync NÃO implementado |
| CommunityMember | ✅ | DB `community_members` | user_id, community_id, **is_moderator**, joined_at, UNIQUE(user,community) |
| Membership Join | ✅ | social svc + gRPC | **não exposto no gateway** |
| Membership Leave | ✅ | social svc + gRPC | **não exposto no gateway** |
| Owner / Ownership | ❌ | — | não há owner_user_id nem criador rastreado |
| Admin role | ❌ | — | inexistente (só is_moderator) |
| Moderator role | ✅ (parcial) | is_moderator bool | sem RPC de listagem/promoção |
| Pending membership | ❌ | — | toda adesão é imediata |
| Private community | ❌ | — | não há visibilidade/privacidade |
| Approval flow | ❌ | — | — |
| Invitation | ❌ | — | — |
| Members listing | ❌ | — | sem ListMembers RPC; Flutter consome `members` que o gateway não envia |
| Community Feed (posts) | ❌ | posts sem community_id | conteúdo atual = discussions (domínio distinto) |
| Discussions | ✅ | domain/discussion + DB | ListForCommunity, thread, messages |
| Stats | ✅ (mínimo) | member_count, active_now | contadores na row; sem stats ricas |
| Counters (member_count/active_now) | ✅ | community row | manutenção verificar (quem incrementa) |
| Deep link /hub/community/{id} | ✅ | azteca router + Search | canônico |
| Capabilities (community) | ❌ | — | a criar no gateway (Stage 2) |
| Cache / correlation / rate-limit (community) | ❌ | — | a criar no gateway (Stage 2) |

## Legenda de decisão
- **REUSE**: Community, Membership Join/Leave, Discussions, Deep link.
- **BUILD (real)**: expor join/leave no gateway; members projection real; stats DTO; capabilities.
- **DESIGN DECISION**: Community Feed — (a) adicionar `posts.community_id` + índice, ou (b) manter
  discussions como feed oficial. Recomendação preliminar: (a) aditivo, preservando discussions.
- **DOCUMENT-AS-ABSENT (nunca inventar)**: Owner, Admin, Private, Pending, Approval, Invitation.
