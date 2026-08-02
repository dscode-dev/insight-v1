# FEATURE-COMMUNITIES-V1 — Stage 0 AUDIT (read-only, no code)

Método oficial (pós SEARCH-V1): AUDIT → UX PRESERVATION → SOCIAL → GATEWAY → AZTECA → VALIDAÇÃO →
DEPLOY(manual) → SMOKE → CERTIFICAÇÃO. Communities já EXISTE parcialmente — esta vertical EVOLUI o domínio
oficial, não cria V2.

## insight-social (o que existe)
- **Domínio** `internal/domain/community/`: `Community` (id, slug, name, topic, kind{topic|competition},
  competitionID?, accentColor, memberCount, activeNow, createdAt) + `Membership` (UserID, CommunityID,
  JoinedAt, **IsModerator bool**). Kind, Sort (NEWEST/HOT/POPULAR), errors.
- **Repository** (interface): Insert, GetByID, GetBySlug, List(keyset, só NEWEST pagina), ListForUser,
  **AddMember**, **RemoveMember**. Implementado em `postgres/communityrepo/`.
- **Application** `application/community/service.go`: List, ListForUser, Get, CreateTopic, **Join**, **Leave**.
- **gRPC** `interfaces/grpc/community.go`: List, ListForUser, Get, Join, Leave (CreateTopic no proto, sem
  handler exposto). Proto `social/v1/community.proto` idem.
- **Schema** (`00001_init.sql`): `communities` + `community_members` (UNIQUE(user_id,community_id),
  is_moderator, joined_at; índice só em community_id). `discussions` referencia community_id.

## insight-gateway (o que existe)
- Só **2 rotas**: `GET /v1/hub/bundle` (segment mine|hot|fresh) e `GET /v1/hub/communities/{id}`
  (NativeFlagged, fallback legacy BFF). Handlers em `internal/interfaces/http/social/hub.go`.
- `GetCommunityDetail` compõe **community + discussions** (NÃO posts, NÃO members, NÃO stats).
- DTOs `HubCommunity` (id, slug, name, topic, kind, accentColor, memberCount) + `HubDiscussion`.
- **NÃO existe**: join/leave, members, admins, moderators, stats, community post-feed, capabilities,
  cache dedicado, correlation-id, rate-limit, canonical errors para community.

## insight-azteca-flutter (o que existe — APROVADO)
- `features/hub/`: **HubScreen** (lista + segmentos hot/fresh/mine + tipsters + discussions),
  **CommunityDetailScreen** (AppBar nome + header card + **3 tabs Discussões/Sinais/Membros**),
  DiscussionThreadScreen. Widgets: community_tile, discussion_row, hub_segments, hub_skeleton, tipster_tile.
- Rota `/hub/community/:communityId` (bate com o deep_link do Search).
- `HubService`: **GatewayHubService** (live) vs **MockHubService** (mock; default do app = gateway).
- Model `models/hub.dart` (freezed): Community(handle, activeMembers, description?), CommunityMember
  (roleLabel), CommunityDetail{community, discussions, **members**}.

## Bugs / gaps críticos encontrados
1. **BUG LATENTE (live)**: `CommunityDetail.fromJson` exige `members` (List não-nula, sem default), mas o
   gateway `CommunityDetailResponse` **não envia `members`** → parse lança em modo gateway. A aba Membros só
   funciona em MOCK. → CONTRACT_MISSING (members projection) + correção Flutter necessária.
2. **Sem owner/admin**: só `is_moderator` bool. Não há owner_user_id nem papel admin. "Admins" e "Ownership"
   NÃO existem no domínio.
3. **Community feed de posts NÃO existe**: `posts` não tem `community_id`. O conteúdo da comunidade hoje são
   `discussions` (domínio separado). "Reutilizar posts" exige linkage inexistente → decisão de design.
4. **Join/Leave existem no social/gRPC mas NÃO no gateway** → Azteca não consegue entrar/sair.
5. **Sem members listing RPC**: `CommunityMember` existe como mensagem, mas não há `ListMembers`.
6. **Aba "Sinais"** do detail é PLACEHOLDER; aba Membros é mock-only.
7. Membership só pública/aberta: sem pending/private/approval/invitation.
8. **Atlas**: não envolvido — permanece congelado.

## Conclusão do Stage 0
O domínio tem uma base sólida de leitura/adesão no social, mas o **gateway expõe pouco** e o **Flutter tem
telas aprovadas parcialmente mock**. A vertical deve: expor join/leave/members/stats via gateway
(orchestrator), decidir o modelo de feed (posts-com-community vs discussions), preencher members com dados
reais, e corrigir o bug de contrato — **sem redesenhar HubScreen/CommunityDetailScreen** (Stage 0.5).

---
## DECISÕES ARQUITETURAIS (Stage 0.5 — aprovadas pelo usuário)
1. **Community Feed = Discussions** (ver ADR-0001). Posts continuam GLOBAL-only; sem posts.community_id, sem
   migration de unificação, sem mistura de timelines. Discussions ganham componentes visuais PRÓPRIOS
   (respostas/participantes/atividade/status), não reaproveitam cards de Post.
2. **Papéis: adicionar owner/admin ao domínio** (Opção 2). Migration ADITIVA: `communities.owner_user_id` +
   `community_members.role` (owner|admin|moderator|member), backfill a partir de is_moderator (mod) e do
   criador quando conhecido. A aba **Administração** passa a ser aplicável.
3. **Tela de comunidade** reorganizada em abas: **Sobre · Discussões · Membros · Estatísticas ·
   Administração**. Substitui a estrutura anterior (Discussões/Sinais/Membros) — mudança de UX AUTORIZADA e
   justificada pelo usuário (a aba "Sinais" placeholder sai; entram Sobre/Estatísticas/Administração reais).
