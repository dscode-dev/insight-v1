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
| **pgvector** | ~~vetores históricos **aprovados** para retrieval~~ · **SUPERSEDIDO pelo ADR-0048** | ~~k-NN sobre corpus estável~~ |
| **ClickHouse** | eventos, snapshots temporais, ticks de odds, histórico de inteligência | append massivo, varredura analítica |
| **Redis** | estado quente ao vivo, janelas móveis, Streams, inteligência materializada | leitura/escrita quente, TTL |
| **S3/MinIO** | bruto imutável, canônico, datasets reconstruíveis | escrita única, leitura rara |

> **NOTA DE SUPERSESSÃO (PR-06.4).** A linha do `pgvector` descrevia a
> intenção desta fase, e ela foi TESTADA e não confirmada. O PR-06.4 mediu o
> `CandidateUniverse` real (~47 candidatos), o teto de recall do proxy e o ponto
> de virada do planejador, e concluiu que a busca aproximada não se justifica na
> escala atual. O ADR-0048 registra a decisão e o gatilho de reavaliação; o
> ADR-0047 registra o que ficou no lugar — uma projeção EXATA em PostgreSQL.
>
> A decisão original não está apagada: ela era razoável com a informação
> daquele momento, e foi a medição que a superou.

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

