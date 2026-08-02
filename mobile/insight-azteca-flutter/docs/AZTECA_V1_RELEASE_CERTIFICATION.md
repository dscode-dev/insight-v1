# Azteca V1 — Certificação de release

Um build só pode ser candidato à V1 quando o workflow
`v1-mobile-certification` estiver verde e os smokes abaixo tiverem evidência em
Android e iOS físicos.

## Configuração bloqueada

- `ENVIRONMENT=production`
- `API_MODE=gateway`
- `ENABLE_DEMO_MODE=false`
- `API_BASE_URL=https://insight-api.konohalabs.com.br`
- nenhum segredo ou endpoint interno no app

`StartupDiagnostics` rejeita mock, demo, HTTP, localhost, Social V1 desligado e host
que não seja o Gateway oficial.

## Matriz de smoke

| Jornada | Android | iOS | Evidência |
|---|---|---|---|
| cold start, onboarding e OTP | pendente | pendente | vídeo + logs sem PII |
| refresh expirado e novo login | pendente | pendente | request IDs |
| feed, post, comentário e reação | pendente | pendente | IDs persistidos |
| comunidade, busca e perfil | pendente | pendente | screenshots + IDs |
| notificações e reconnect SSE | pendente | pendente | timeline de eventos |
| live/radar indisponível | pendente | pendente | estado honesto, sem fixture |
| upload de avatar/mídia | pendente | pendente | URL persistida |
| offline → online/background | pendente | pendente | logs de reconnect |

## Gates de store

- assinatura, version/build number e bundle IDs;
- privacy disclosures e permissões;
- política/termos e contato de suporte;
- ícones, screenshots e textos;
- acessibilidade com leitor de tela e escala de fonte;
- crash-free smoke e consumo aceitável de rede/bateria.

O documento registra evidência, não substitui o teste em dispositivo. A conclusão de
V1-007 exige preencher a matriz com links para artefatos do release candidate.
