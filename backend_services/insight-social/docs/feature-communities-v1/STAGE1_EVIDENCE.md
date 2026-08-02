# FEATURE-COMMUNITIES-V1 — Stage 1 (Social) Evidence

## Classificação honesta
| Eixo | Status |
|---|---|
| Proto/Contrato | READY (aditivo, buf lint limpo p/ community, buf breaking PASS) |
| Backend domínio | READY (invariantes puras testadas) |
| Backend persistência | CODE READY / **SQL needs-pg** (repo tx + keyset não roda sem Postgres; sem migration aplicada) |
| Testes | READY p/ domínio+serviço (34 casos community verdes); SQL-level documentado needs-pg |
| Deploy | NOT_DEPLOYED (nenhuma migration aplicada; sem deploy) |

## O que foi implementado (só Social + proto)
- **proto** `social/v1/community.proto` (aditivo): `CommunityRole{UNSPECIFIED,MEMBER,MODERATOR,ADMIN,OWNER}`;
  `Community.owner_user_id` (optional); `CommunityMember.role`; `CommunityMemberProfile`; `CreateTopic` ganha
  `owner_user_id`; RPC `ListMembers`. Regenerado via buf (stubs gitignored, consumidos por path-replace).
- **migration** `00011_community_roles.sql` (ADITIVA, NÃO aplicada): `communities.owner_user_id` nullable
  (OWNER_UNASSIGNED p/ legado/competição); `community_members.role` CHECK(owner|admin|moderator|member)
  DEFAULT member; backfill determinístico `is_moderator=true → moderator`; **partial-unique**
  `ux_community_members_one_owner` (≤1 owner por comunidade); índice keyset de membros; índice owner. Down
  reversível. is_moderator mantido (compat).
- **domain**: `role.go` (Role + Priority + LegacyIsModerator); `authz.go` (CanLeave, CanChangeRole,
  ReconcileJoinRole, TransferOwnership — invariantes puras); `members_cursor.go` (codec estável
  priority/joined_at/user_id); Community ganha `ownerUserID`+OwnerAssigned; Membership ganha Role; MemberProfile
  + MembersPage + ListMembersFilter.
- **repository**: `InsertOwned` (tx atômica: comunidade + membership OWNER + owner_user_id, member_count=1);
  `AddMember`/`RemoveMember` com role; RemoveMember bloqueia OWNER na MESMA statement (ErrOwnerCannotLeave) e é
  idempotente (ErrNotMember); `ListMembers` keyset JOIN users (limit+1, sem N+1).
- **service**: CreateTopic(ownerID) via InsertOwned; ListMembers(roleFilter,limit,cursor); Leave delega guard.
- **gRPC**: CreateTopic deriva owner; ListMembers handler; translators owner/role/memberProfile; erros mapeados
  (FailedPrecondition p/ owner-leave/immutable/role-denied; Unimplemented p/ transfer).

## Invariantes cobertas (testes verdes)
≤1 owner (partial-unique index + CanChangeRole bloqueia promover a owner); owner não sai sem transferência
(CanLeave + RemoveMember SQL); owner imutável a operações genéricas (CanChangeRole); admin não cria/rebaixa
admin nem toca owner; only-authorized role change; leave idempotente; join não sobrescreve role privilegiada
(unique → ErrAlreadyMember + ReconcileJoinRole); criação atômica de owner (service usa InsertOwned);
OWNER_UNASSIGNED legado (Reconstitute nil, sem owner fabricado); paginação keyset + ordenação estável (cursor
codec); is_moderator compat (LegacyIsModerator derivado).

## Riscos residuais
1. **SQL não exercitado sem Postgres**: tx atômica, guard de owner-leave e keyset JOIN precisam de pg para
   prova de execução (padrão do repo — search/atlas idem). Cobertura de lógica pura + serviço via fakes.
2. **OWNER_UNASSIGNED**: comunidades legadas ficam sem owner (nenhum criador determinístico). Estratégia
   operacional de atribuição = trabalho futuro documentado (não inventar owner).
3. **Transferência de ownership**: capability AUSENTE por design na V1 (protegida via bloqueio de saída do
   owner + ErrTransferUnsupported). Nenhuma UI/endpoint parcial.
4. **is_moderator**: mantido por compat; parar de ler como verdade; remoção futura pós Gateway+Azteca.
5. **Editorial**: feed = Discussions (ADR-0001); NENHUM posts.community_id, nenhuma unificação — inalterado.

## Validação executada
`go build ./...` OK · `go vet ./...` OK · `go test ./...` sem falhas (community: 34 casos verdes) ·
`git diff --check` limpo · gateway `go build ./...` OK (consome stubs regenerados). **NENHUM deploy, NENHUMA
migration aplicada.**
