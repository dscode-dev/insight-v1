# FEATURE-NOTIFICATIONS-V1 — DOMAIN STATUS

| Capacidade | Status atual | Ação NOTIFICATIONS-V1 |
|---|---|---|
| Domínio Notification | ABSENT | Criar no Social (autoridade) |
| Persistência (tabela + índices) | ABSENT | Migration aditiva (keyset index; dedup unique) |
| proto | ABSENT | Criar notification.proto (aditivo; buf breaking PASS) |
| ListNotifications (cursor) | ABSENT | Keyset (created_at,id) DESC; sem offset/N+1 |
| UnreadCount | CLIENT-DERIVED (badge simulado) | RPC real + rota Gateway; badge consome |
| MarkRead (per-item) | ABSENT | PATCH /notifications/{id}/read |
| MarkAllRead | ORPHAN (POST inexistente) | PATCH /notifications/read-all |
| Dedup | ABSENT | Chave (user_id, dedup_key) UNIQUE — 1 evento = 1 notificação |
| Tipos de evento | CLIENT-ONLY, desalinhado | NotificationType canônico no Social; Gateway mapeia p/ DTO |
| Priority | ABSENT | NotificationPriority no domínio |
| Deep links | ABSENT | Gateway-built (validado no cliente) |
| Capabilities | ABSENT | Gateway retorna |
| Realtime | FOUNDATION only | V1 refresh controlado; arquitetura pronta p/ SSE |
| Tela / Badge (UI) | MOCK, gated-off | Promover a real; badge do Gateway |

## Fonte dos eventos (produção real, sem fabricar)
- **Community Join** → `community_members` insert (Communities V1).
- **Discussion Reply** → resposta em discussion (Discussions).
- **Mention** → menção em post/comment/discussion.
- **Reaction** → reação em post/discussion (Sprint B reactions).
- **System** → emitido pela plataforma (broadcast/operacional).
- **Invitation / Community Accepted** → SEM domínio de origem na V1 → ausentes (documentado).

## Como as notificações são produzidas (decisão de arquitetura a validar no Stage 1)
Duas abordagens possíveis (a decidir no Stage 1, sem implementar agora):
1. **Escrita direta no ponto do evento** (ex.: ao dar Join, o Social insere uma notificação para o alvo).
   Simples, síncrono, transacional.
2. **Outbox/derivação** (evento → tabela outbox → worker cria notificações). Mais desacoplado, prepara SSE.
Recomendação preliminar: começar com (1) para os eventos já existentes no Social (Join/Reply/Reaction/Mention),
mantendo a interface de criação isolada para migrar a (2)/SSE depois sem quebrar contrato.

## Riscos
- Não fabricar tipos sem origem real (Invitation).
- Badge/unread devem ser SEMPRE do Gateway (fim da dedução no cliente).
- Dedup obrigatório para não duplicar (ex.: múltiplas reações não devem gerar N notificações idênticas).
