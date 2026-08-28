# ADR-0047 — A projeção exata em PostgreSQL substitui a releitura de candidatos no Parquet

**Estado:** aceito · **PR:** 06.4

## Contexto

Os PRs 06.1, 06.2 e 06.3 produziram três oráculos exatos e exaustivos, corretos
e caros:

```
estado exato       p50 ~ 33,5 ms
trajetória exata   p50 ~ 364 ms      (arnês do PR-06.3)
```

A leitura óbvia era «a varredura exaustiva é cara, aproxime». A medição disse
outra coisa: **o custo não estava no cálculo.**

Quarenta e sete distâncias sobre quinze eixos não custam trinta e três
milissegundos. O que custa é IR BUSCAR as representações — baixar objetos
Parquet do MinIO, abrir, projetar colunas, materializar linhas.

## Decisão

Projetar os candidatos de REFERÊNCIA numa tabela PostgreSQL, com o payload
exato em `float64`, e ler o `CandidateUniverse` inteiro por B-tree.

```
Normalized Historical Dataset          AUTORIDADE SEMÂNTICA
        |
        v
Historical Retrieval Projection        read model DERIVADO
        |
        v
B-tree (competição + instante exato)
        |
        v
os MESMOS calculadores do PR-06.2 / PR-06.3
```

**Nada é aproximado.** A projeção muda DE ONDE os candidatos vêm, e nunca COMO
eles são medidos.

## Por que isto e não um índice aproximado

Porque o `CandidateUniverse` é **pequeno por construção**: uma competição num
instante EXATO da grade, o que dá ~47 candidatos no corpus real. Medido, o
planejador do PostgreSQL só escolhe HNSW a partir de alguns milhares. Ver
ADR-0048.

## Consequências

Medido na revisão final:

```
ESTADO       candidate-side  15,51 ms -> 8,09 ms    1,92x
TRAJETÓRIA   candidate-side  22,06 ms -> 13,54 ms   1,63x

objetos por query  2 -> 1   (só a QUERY)
consultas SQL      1        (nunca uma por candidato)
```

E a concordância semântica é **exata**, medida sobre o corpus real: universo,
elegibilidade, cobertura, distância `float64` sem tolerância, impressão de
evidência e top-K ordenado, nos dois caminhos.

**O que ficou:** a leitura da linha de AVALIAÇÃO do Parquet, hoje ~70% do
caminho projetado. Está registrada como `QUERY_REPRESENTATION_PARQUET_IO` e
pertence ao caminho de serving futuro.
