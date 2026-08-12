# Código aposentado

O que está aqui **não é referência para o Atlas novo**. Foi movido para cá em
12/08/2026, quando a decisão foi reescrever do zero, e permanece apenas como
registro do que existiu.

## insight-atlas (v1 antiga)

Motor de inteligência anterior. Aposentado por complexidade acumulada: 37
dimensões vetoriais das quais 14 eram constantes, duas regras de identidade
que nunca podiam concordar, um portão de detector que media dispersão de
distância sob o nome de "concordância entre vizinhos", e pacotes inteiros que
nada importava.

O que ele **mediu** e vale como conhecimento — não como código:

- as lentes funcionam onde o mercado separa as partidas, e a ordem é exata:
  Premier League (desvio 0,196) +12,7% sobre a taxa base; La Liga (0,173)
  +9,4%; Brasileirão (0,138) +0,8%; Argentina (0,122) −0,8%;
- ler mais colunas de mercado (over/under, handicap, dispersão entre casas)
  não moveu nenhuma lente de forma conclusiva;
- contexto de tabela — posição e o que está em jogo — foi a única dimensão
  nova que virou ganho conclusivo, e só na Europa;
- filtrar por concordância de desfecho contra a taxa base seleciona de fato:
  o que passa acerta +21,3 pontos na Premier League e +8,2 no Brasileirão,
  contra +12,7 e +0,8 sem filtro;
- fusos de fonte pública mentem por omissão (football-data publica tudo em
  hora do Reino Unido, inclusive arquivos sul-americanos);
- resolução de clube por subconjunto de tokens funde clubes de continentes
  diferentes em silêncio (`Arsenal Sarandi` → Arsenal FC, 352 partidas).

## insight-anvil

Aposentado antes, sem substituto planejado.

## A superfície de integração que o Atlas novo terá de atender

Registrada aqui porque é o único acoplamento que sobrevive à reescrita:

| quem | o que espera |
|---|---|
| `insight-gateway` | envelope do publisher em hash plano (`internal/realtime/broker.go`) |
| `insight-sport-hub` | os valores de `SourceType` espelhados byte a byte (`internal/domain/source/source_type.go`) |
| `insight-console-api` | os prefixos `/atlas/*`, `/v1/intake/*`, `/v1/query/*`, `/v1/internal/intelligence/*` (`src/data-intelligence/path-policy.ts`) |
| `docker-compose.yml` | nome de serviço, healthcheck e variáveis de ambiente |

Nenhum desses contratos precisa ser preservado tal como está — precisam ser
**renegociados explicitamente** quando o Atlas novo chegar a eles.
