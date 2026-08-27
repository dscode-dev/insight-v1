# `HISTORICAL_RETRIEVAL_CONTRACT_V1` — a recuperação histórica exata

**PR:** 06.1 · **ADR:** [0041](../architecture/adr/0041-reference-only-same-competition-candidate-universe.md)
e [0042](../architecture/adr/0042-exact-exhaustive-complete-case-retrieval-baseline.md)

## O que este PR entrega

Duas respostas, e nenhuma terceira:

```
quem pode ser candidato histórico?          CandidateUniversePolicy
qual é o top-K exato sobre esses candidatos?  ExactHistoricalRetriever
```

**Ele não é o motor de inteligência.** Não há tendência de resultado, tendência
de pressão, tendência de cotação, contexto de partida, confiança, tamanho
efetivo de amostra, agregação ponderada, previsão, probabilidade nem rótulo.

**Ele não é o índice aproximado.** Não há pgvector, HNSW, IVFFlat, FAISS,
ScaNN, Redis nem ClickHouse. Ele é o **oráculo** contra o qual esses terão de
provar correção.

## O fluxo

```
NormalizedHistoricalFeatureDatasetVersion  status = READY
        ↓
query de AVALIAÇÃO  (uma linha, por chave)
        ↓
CandidateUniversePolicy
        ↓
candidatos de REFERÊNCIA, mesma competição, mesmo instante
        ↓
perfil resolvido      eixos ROBUST FITTED daquela liga
        ↓
elegibilidade         caso completo
        ↓
varredura exaustiva   d² sobre TODO candidato comparável
        ↓
top-K determinístico  (d², chave canônica)
        ↓
ExactRetrievalResult
```

## A autoridade de dados

**Só o dataset normalizado `READY`.** A recuperação não volta ao corpus: durante
uma query,

```
leituras de partida canônica  0
leituras de evento            0
leituras de escalação         0
leituras de cotação           0
leituras de resultado         0
leituras de contexto          0
```

Isso não é disciplina — é estrutura. O contêiner do PR-06.1 recebe **dois**
repositórios de metadado (versões normalizadas e conjuntos de artefatos) e **um**
leitor de Parquet. Não há repositório de fato canônico no grafo, então não há
por onde ler um. Há teste de integração que instrumenta as consultas e falha se
qualquer tabela de fato for tocada.

O PostgreSQL entra em dois lugares e só neles: os metadados da versão e os
números do ajuste. As linhas vêm do object store.

## Os contratos

| contrato | o que ele é | impressão |
|---|---|---|
| `CandidateUniversePolicy` | a REGRA de quem pode ser candidato | sim |
| `CandidateUniverseDescriptor` | o universo que UMA query resolveu | sim |
| `RetrievalFeatureProfile` | a REGRA de quais eixos entram | sim |
| `ResolvedRetrievalProfile` | os eixos de UMA competição, em ordem | sim |
| `DistanceDefinition` | o método, amarrado ao perfil | sim |
| `HistoricalRetrievalQuery` | o pedido: linha, políticas, `K` | — |
| `QuerySnapshot` | a linha de avaliação, com valores e máscara | — |
| `CandidateRow` | uma linha de referência alinhada | — |
| `HistoricalNeighbor` | um candidato no top-K, com a régua ao lado | — |
| `ExactRetrievalResult` | o ranking e a contabilidade | sim |

A separação entre **regra** e **resultado da regra** aparece três vezes —
política/descritor, perfil/resolvido, pedido/resultado — e sempre pelo mesmo
motivo: uma regra cuja impressão mudasse a cada consulta não identificaria regra
nenhuma.

## A query

```
dataset_version_id      qual versão normalizada
representation          as quatro decisões que a escrevem (ADR-0040)
key                     <match_id>#<grid_index>
k                       1 ≤ K ≤ 1000
policy                  CandidateUniversePolicy
profile                 RetrievalFeatureProfile
```

**A representação é conferida contra a linha carregada** — impressão da
representação, do plano e do conjunto de artefatos. Uma linha da chave certa
escrita sob outro conjunto de artefatos é um vetor de números na mesma ordem e
em outra grandeza: o defeito mais caro possível, porque tudo continua parecendo
funcionar.

**O `K` não trunca o universo.** O teto de 1000 é operacional — um `K` de um
milhão viraria um relatório que ninguém lê —, e o oráculo examina todo candidato
elegível de qualquer jeito.

**A query vem do dataset, e não da linha de comando.** Construir features ao
vivo é outro caminho, e ele não existe ainda.

## O resultado

```
query_key, query_row_digest         qual linha perguntou
competition
candidate_policy_fingerprint        sob quais regras
candidate_universe_fingerprint      sobre quais candidatos
retrieval_profile_fingerprint       sob qual regra de eixos
resolved_profile_fingerprint        sobre quais eixos
distance_definition_fingerprint     sob qual método
axis_count
requested_k, returned_k
universe_count, comparable_count    a contabilidade
ineligible                          por motivo
neighbors                           o ranking
exhaustive = True
```

`returned_k = min(requested_k, comparable_count)`. **Sem preenchimento**: uma
competição com poucos candidatos comparáveis devolve poucos vizinhos, e zero
vizinhos é um resultado válido — não uma falha, e nunca uma queda para outra
liga.

## Determinismo

Quatro variações não podem mudar o resultado, e cada uma tem teste de
propriedade:

| variação | teste |
|---|---|
| ordem de iteração dos candidatos | 10 permutações + ordem inversa |
| tamanho do lote de leitura | 1, 7, 128, 512, 2048 |
| layout físico do Parquet | duas execuções sobre o dataset real |
| `K` | `top10(K=50) == resultado(K=10)`, **com empate no corte** |

O caso do empate no corte é o que pega um `<` no lugar de um `<=` dentro do
heap: ele produz um top-K correto em conteúdo e errado em ordem apenas quando há
empate exatamente no `K`-ésimo, e num cenário de cinco candidatos isso nunca
acontece. Por isso o cenário de teste tem empates deliberados ali.

## O que fica para depois

| assunto | PR |
|---|---|
| distância ciente de ausência, cobertura, evidência | 06.2 |
| trajetória e distância entre trajetórias | 06.3 |
| índice aproximado e `Recall@K` contra este oráculo | 06.4 |
| agregação, pesos, tamanho efetivo de amostra | 06.5 |
| lentes de inteligência | 06.6 |
| confiança e explicabilidade | 06.7 |
