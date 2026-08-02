# FEATURE-NOTIFICATIONS-V1 — Stage 0.5 UX PRESERVATION (obrigatório)

Aprendizado SEARCH/COMMUNITIES: integrar à experiência aprovada, nunca substituir/simplificar/redesenhar.
Esta análise precede QUALQUER alteração de tela.

## Quais telas serão alteradas?
- `features/notifications/notifications_screen.dart` — **evoluída** (dados reais + paginação cursor + scroll
  infinito + pull-to-refresh + marcar-lida por item + estados completos). MESMA rota `/notifications`.
- `widgets/notifications_action.dart` (badge do sino) — **fonte do unread muda** para o Gateway
  (unread-count), preservando 100% o visual (sino + badge "9+").
- `providers/notifications_provider.dart` / `services/notifications_service.dart` — reescrever a camada de
  dados (list cursor + unread-count + per-item read + read-all) contra o contrato real. Sem impacto visual.

## Quais layouts aprovados serão preservados?
- Tela: AppBar "Notificações" + ação "Marcar lidas"; lista de linhas com **ícone em quadrado tingido por
  tipo** + título (negrito se não-lido) + tempo relativo + corpo + **tint de fundo em não-lidos**;
  empty/error/feature-unavailable states. Tudo preservado.
- Badge: sino no AppBar da Home com contador "9+" (cor confidenceLow, borda). Preservado.
- Design System: ícone+cor+texto por tipo já existe (`_icon()`/`_accent()`) — evoluir o mapa para os tipos
  canônicos da V1 mantendo a linguagem visual.

## Existe risco de substituir alguma tela? 
SIM se criarmos uma "nova" NotificationCenterScreen. **PROIBIDO** — a tela existente É o Notification Center;
evoluir no mesmo arquivo/rota.

## Existe risco de simplificar UX?
SIM — tentação de trocar a lista rica por algo genérico ao migrar para dados reais. Preservar linhas,
tints e ícones por tipo.

## Existe risco de regressão visual?
SIM (médio) — reescrever a camada de dados + adicionar paginação/refresh pode alterar o comportamento de
scroll/estados. Mitigação: manter a composição de `_NotificationRow`, apenas trocar a fonte de dados e
adicionar scroll infinito + pull-to-refresh sem mexer no visual da linha.

## Riscos específicos e mitigação
| Necessidade V1 | Risco (proibido) | Integração aprovada |
|---|---|---|
| Dados reais | trocar tela por lista genérica | manter `_NotificationRow`; só troca a fonte |
| Paginação/scroll infinito | recarregar tudo (rebuild completo) | cursor + append incremental + keepAlive |
| Pull-to-refresh | novo layout | RefreshIndicator sobre a MESMA lista |
| Marcar lida (per-item) | novo fluxo/tela | tap na linha → PATCH read + atualização otimista da linha |
| Badge do Gateway | manter dedução no cliente | `unreadCountProvider` passa a ler o unread-count do Gateway |
| Tipos canônicos V1 | inventar ícones/cores fora do DS | estender `_icon()/_accent()` no mesmo padrão |
| Realtime | polling agressivo | refresh controlado (on-open + pull-to-refresh); SSE no futuro |

## Compatibilidade transversal
Não alterar Search, Communities, Feed, Atlas, Profile, navegação. O badge vive no AppBar da Home (e onde já
aparece) — nenhuma mudança de navegação. `feature_gate` (`flagNotificationsV1`) permanece o interruptor;
ligado só quando o backend real existir.

## Decisão
PROSSEGUIR para Stage 1 com o compromisso: Notification Center e badge são EVOLUÍDOS in-place; unread/badge
passam a vir do Gateway; nenhuma tela nova substitui a aprovada; nenhum dado fabricado.
