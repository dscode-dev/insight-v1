# ADR-0016 — O limite de staging: `STAGED` não é `HISTORICAL_ACTIVE`

**Status:** aceito · **Data:** 2026-08-13

## Contexto

O ADR-0007 estabelece a barreira mais cara desta base: uma partida nunca
alimenta o índice histórico que ela própria consulta. Um dataset histórico
que entra no índice sem passar por resolução e fusão fura essa barreira por
outra porta — e a falha é da mesma família: nada quebra, os números só ficam
errados.

O PR-02 introduz um estado terminal chamado `STAGED`, e o nome é um convite ao
mal-entendido. «Staged» soa como «pronto», e um consumidor futuro lendo
`lifecycle == "STAGED"` concluiria, razoavelmente, que o dado está em uso.

## Decisão

**`STAGED` significa exatamente isto, e nada além:**

> o bruto foi recebido, preservado, e é estruturalmente apto a **ENTRAR** em
> resolução de identidade e fusão.

Não significa que o dado pode alimentar o índice histórico, o vetor, ou
qualquer inteligência. Entre um e outro estão o PR-03 inteiro e a barreira do
ADR-0007.

**Três formas de dizer isso, porque uma documentação não é executável:**

1. `assert_not_intelligence_ready(state)` **recusa sempre**, inclusive para
   `STAGED`. Ela existe para ser chamada por qualquer caminho futuro que
   pretenda alimentar o histórico a partir de um dataset de intake.
2. O evento `dataset.staged` carrega `intelligence_ready: false` no payload, e
   a resposta da API repete o campo — nenhum consumidor precisa inferir.
3. Um teste de arquitetura falha o CI se `domain/datasets`,
   `ingestion/historical` ou `ingestion/validation` importarem o domínio
   futebolístico ou definirem uma função com nome de resolução.

**Chegar a `STAGED` exige duas guardas, e nenhuma basta sozinha:**

```
o estado precisa ser VALIDATED     um relatório limpo não diz nada sobre
                                   um dataset que nem subiu
o relatório precisa estar limpo    um dataset pode estar VALIDATED por um
                                   relatório antigo
```

**`REGISTERED → STAGED` não existe como aresta do grafo.** Não é uma
conferência em tempo de execução: a transição não está lá. A diferença importa
porque uma conferência especial sobrevive a alguém acrescentar um estado no
meio, e a ausência da aresta obriga a decisão a ser tomada de novo.

## Consequências

**Ganhamos:** um limite que o CI defende. O dia em que alguém escrever
`resolve_team` dentro do validador é o dia em que o teste falha — não seis
meses depois, com o histórico já contaminado.

**Pagamos:** um estado a mais no ciclo e a obrigação de explicar, em toda
interface, que `STAGED` não é «pronto». O campo `intelligence_ready: false`
aparece em resposta de dataset que ninguém promoveu ainda, e parece redundante
até o dia em que não é.

## Alternativas consideradas

**Chamar de `INGESTED` ou `PRESERVED`.** Seria um nome melhor e foi descartado
tarde demais para valer a troca. A mitigação é a guarda executável, que não
depende do nome.

**Não ter estado terminal no intake — o dataset fica `VALIDATED` até o PR-03
consumi-lo.** Rejeitado: perde o registro da decisão humana. Promover é um
julgamento — «conferi contra o site da fonte» — e sem estado próprio esse
julgamento não tem onde ser gravado.

