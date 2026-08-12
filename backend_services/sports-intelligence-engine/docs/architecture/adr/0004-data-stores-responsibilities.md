# ADR-0004 — Responsabilidade de cada armazenamento

**Status:** aceito · **Data:** 2026-08-12

## Contexto

Cinco tecnologias, e sem fronteira escrita elas convergem para "o banco
principal" — que fica lento por servir a todos os padrões de acesso ao mesmo
tempo.

## Decisão

| Armazenamento | Responsabilidade | Padrão de acesso |
|---|---|---|
| **PostgreSQL** | metadados, entidades, identidades, datasets, mappings, usuários, estado transacional | leitura por chave, escrita transacional |
| **pgvector** | vetores históricos **aprovados** para retrieval | k-NN sobre corpus estável |
| **ClickHouse** | eventos, snapshots temporais, ticks de odds, histórico de inteligência | append massivo, varredura analítica |
| **Redis** | estado quente ao vivo, janelas móveis, Streams, inteligência materializada | leitura/escrita quente, TTL |
| **S3/MinIO** | bruto imutável, canônico, datasets reconstruíveis | escrita única, leitura rara |

**Duas regras que atravessam a tabela:**

1. O bruto é **imutável**. `ObjectStorePort` não tem `delete`.
2. ClickHouse é **append-only**. Snapshot corrigido é linha nova com versão
   maior; a antiga permanece como registro do que se sabia antes.

## Consequências

**Ganhamos:** cada armazenamento serve o padrão para o qual foi escolhido, e a
pergunta "onde isso mora" tem resposta única.

**Pagamos:** consistência entre eles é eventual e precisa ser desenhada. E
cinco tecnologias é cinco coisas para operar.

## Alternativas consideradas

**Só PostgreSQL.** Rejeitado: varredura analítica sobre bilhões de ticks e
k-NN sobre milhões de vetores no mesmo banco que serve leitura transacional
degrada os três.

**Só ClickHouse.** Rejeitado: transação e restrição de unicidade são o que
sustenta idempotência, e ClickHouse não é a ferramenta para isso.

