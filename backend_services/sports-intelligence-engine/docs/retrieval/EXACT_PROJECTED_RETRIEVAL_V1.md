# O contrato de equivalência exata

**PR:** 06.4

## A afirmação

Para toda query válida:

```
CandidateUniverse_projetado  ==  CandidateUniverse_Parquet
elegibilidade                ==
cobertura                    ==
D_state / D_trajectory       ==      float64, sem tolerância
impressão da evidência       ==
top-K ORDENADO               ==
```

Não «aproximadamente». **Igual.**

## Por que a implementação compartilhada não basta como prova

O caminho projetado entrega `CandidateRow` e `TrajectoryCandidate` aos MESMOS
`AvailabilityAwareHistoricalRetriever` e `ExactTrajectoryRetriever` que a
varredura usa. Não existe segunda fórmula para divergir.

Isso reduz o risco a quase zero — e **não é prova empírica**. O gate mede.

## O que é medido, e sobre o quê

Corpus real, pipeline real: canônico → dataset de features → ajuste →
normalizado READY → projeções READY. 96 partidas, universo p50 de 47.

E a comparação é do **universo inteiro**, não só do top-K: dois recuperadores
podem coincidir no topo com candidatos divergentes fora do corte, e aceitar isso
como equivalência seria aceitar uma coincidência.

## A armadilha da trajetória

Uma trajetória não é uma linha: é uma âncora e os instantes que ela alcançou. A
impressão dela cobre o digesto de **cada slot**.

Guardar só os deslocamentos produziria uma trajetória com os mesmos números e
**identidade diferente** — e a evidência divergiria sem que um único valor
mudasse. Por isso a projeção guarda `slot_lineage`, e por isso o gate compara
impressões de evidência e não apenas distâncias.

## O recorte para o perfil

A projeção guarda os 29 eixos canônicos do plano; a distância é medida sobre os
eixos que a competição resolveu (15 no corpus real). `restrict_to_profile` faz o
recorte na ORDEM do perfil — e é isso que faz a representação reconstruída ser
idêntica à que o oráculo montaria do Parquet.
