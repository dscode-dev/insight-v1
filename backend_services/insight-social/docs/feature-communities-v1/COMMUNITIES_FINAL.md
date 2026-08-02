# FEATURE-COMMUNITIES-V1 — Final Certification

## CLASSIFICAÇÃO FINAL
| Eixo | Nota |
|---|---|
| Arquitetura | **A** |
| Qualidade de Código | **A** |
| Segurança | **A-** |
| Escalabilidade | **A** |
| UX | **A** |
| Risco Operacional | **Baixo** |
| **Readiness** | **PRODUCTION READY** — aguardando apenas deploy manual + aplicação da migration 00011 |

CODE READINESS: **READY** · OPERATIONAL STATUS: **NOT_DEPLOYED — USER-OPERATED DEPLOYMENT REQUIRED**.
(Não promover a CERTIFIED READY antes do deploy + smoke operacional.)

## 1. Objetivo inicial
Transformar Communities em um domínio completo: descobrir, ver detalhe, entrar/sair, ver membros/admins/
moderadores, ver discussões e estatísticas reais, navegar entre usuários/discussões, deep links, capabilities,
paginação, offline, partial — tudo com **dados reais** (sem mocks/placeholders/"coming soon"), evoluindo o
domínio oficial (nunca V2 paralelo), Gateway como único contrato público, Atlas congelado, sem deploy.

## 2. Principais decisões arquiteturais
- **ADR-0001 — Posts × Discussions**: dois domínios editoriais independentes. Feed da comunidade = Discussions;
  timeline global = Posts. Sem `posts.community_id`, sem unificação (fica para ADR V2).
- **Papéis canônicos**: `CommunityRole` (OWNER/ADMIN/MODERATOR/MEMBER) é a fonte de verdade;
  `owner_user_id` é referência otimizada sincronizada com exatamente 1 OWNER (unique parcial + tx atômica).
  `is_moderator` mantido só por compat.
- **OWNER_UNASSIGNED**: comunidades legadas sem owner determinístico — nunca fabricar owner.
- **Gateway = Orchestrator**: detalhe é AGREGADO (fan-out paralelo, partial honesto), DTOs próprios (sem reuso
  de proto), capabilities explícitas como autorização da UI, deep links server-built, cache/timeout/rate-limit.
- **Azteca = integração**: CommunityDetailScreen evoluída (mesma rota, header aprovado), abas por capabilities,
  componente próprio de Discussion, join/leave otimista, UI nunca infere de role.

## 3. Mudanças realizadas
- Social: migration 00011 (aditiva); domínio de roles/owner + invariantes puras; repo InsertOwned atômico +
  ListMembers keyset + GetStats/GetMembership; service + gRPC. proto aditivo (buf breaking PASS).
- Gateway: pacote `communitybff` (dto/capabilities/client/aggregator/cache/metrics/handlers) + 5 rotas; correção
  do bug latente pelo contrato (detalhe = contadores, não array de membros).
- Azteca: feature `features/hub/community/` (models/service/state/widgets) + tela evoluída.
- Testes: Social 19 casos community, Gateway 12 casos communitybff, Azteca 10 casos (130 no total, verdes).

## 4. Mudanças deliberadamente adiadas (V2 — ver Tech Debt)
Transferência de ownership; endpoints administrativos de mutação; avatar/banner; enriquecimento de autor;
cleanup de órfãos; remoção de is_moderator; ADR de unificação editorial; StatsCache→Redis; discussion_count
materializado; atribuição de owner a OWNER_UNASSIGNED.

## 5. Riscos remanescentes
- SQL (tx/keyset/guards/stats) precisa de Postgres para prova de execução runtime (padrão do repo; coberto por
  lógica pura + serviço com fakes). Mitigado pelo SMOKE.
- Janela de rollout gradual: ambas as ordens (Gateway↔App) são tolerantes (sem crash); ordem canônica minimiza
  degradação. Ver Operational Readiness.
- Nenhum risco de perda de dados (migration aditiva; rollback preserva dados).

## 6. Justificativa das notas
- **Arquitetura A**: separação Social→Gateway→Azteca íntegra; orchestrator real; ADR editorial preservada.
- **Código A**: contratos próprios, invariantes no domínio+tx, testes por camada, aditivo/sem breaking.
- **Segurança A-**: identidade sempre server-derived (X-User-Id); authz no domínio + capabilities como projeção;
  perfis só campos públicos. (-) mutações administrativas ainda ausentes e SQL não exercitado em runtime.
- **Escalabilidade A**: keyset em tudo, sem N+1, cache isolável (Redis-ready), rate limit.
- **UX A**: identidade aprovada preservada, zero regressão, estados completos, capabilities-driven.
- **Risco Operacional Baixo**: aditivo, partial honesto, rollout tolerante, rollback seguro.

## 7. Documentação da vertical (insight-social/docs/feature-communities-v1/)
AUDIT · ENTITY_MATRIX · DOMAIN_STATUS · CONTRACT_MATRIX · UX_IMPACT · ADR-0001 · API ·
STAGE1/2/3_EVIDENCE · CONTRACT_COMPAT · MIGRATION_SAFETY · PERFORMANCE · UX_REGRESSION · TECH_DEBT_V2 ·
OPERATIONAL_READINESS · DEPLOY · SMOKE · FINAL.

## Encerramento
Com deploy manual + migration 00011 + smoke aprovado, a FEATURE-COMMUNITIES-V1 está pronta para integrar a
release da V1 sem dívida arquitetural significativa (dívida V2 catalogada e não-bloqueante).
