# ADR-0001 — Dois domínios de conteúdo independentes (Posts × Discussions) na V1

Status: ACEITO (FEATURE-COMMUNITIES-V1). Data: 2026-07-17.

## Contexto
Posts não têm vínculo com comunidade (sem community_id). O conteúdo de comunidade hoje são Discussions
(domínio separado). Avaliou-se unificar (posts.community_id) ou manter separado.

## Decisão
Na V1 existem **dois domínios de conteúdo independentes e intencionais**:
- **Posts** = conteúdo GLOBAL da plataforma (timeline de descoberta/consumo rápido). Continua exclusivo do
  feed global.
- **Discussions** = conteúdo OFICIAL das comunidades (conversa coletiva, tipo fórum moderno). É o feed da
  comunidade.

NÃO implementar `posts.community_id`, NÃO criar migration de unificação, NÃO misturar os dois domínios na
mesma timeline. A separação é refletida na arquitetura E na experiência (componentes visuais próprios para
Discussions — respostas, participantes, atividade recente, status — não reaproveitar os cards de Post).

A tela de comunidade tem navegação própria (abas): **Sobre · Discussões · Membros · Estatísticas ·
Administração (quando aplicável)**. Discussões consome exclusivamente Discussions; o feed global consome
exclusivamente Posts.

## Consequências
- Preserva consistência do domínio atual; reduz risco estrutural na reta final da V1.
- "Posts da comunidade" não existe como tal na V1 (documentado, não mascarado).

## Evolução futura (V2 — fora do escopo)
ADR futura avaliará unificar o modelo editorial: Post único com escopo (GLOBAL|COMMUNITY) + community_id,
substituindo Discussions. Nenhuma implementação disso na V1.
