# `HistoricalRetrievalProjection` — o read model operacional

**PR:** 06.4 · **ADR:** [0047](../architecture/adr/0047-postgres-exact-retrieval-projection.md)

## Por que ela existe

O custo da recuperação exata **não estava no cálculo**. Foi medido: o
`CandidateUniverse` real tem ~47 candidatos, e quarenta e sete distâncias sobre
quinze eixos não custam trinta e três milissegundos. O que custa é ir buscar as
representações no Parquet do MinIO.

A projeção move os candidatos para perto do cálculo.

## O que ela NÃO é

```
NÃO é autoridade histórica      o dataset normalizado é
NÃO é cache de resultado        guarda CANDIDATOS, nunca vizinhos
NÃO é aproximação               float64 bit a bit
```

Se a projeção e o dataset divergirem, **o dataset ganha** e a projeção é
reconstruída. É por isso que cada linha carrega o digesto da linha de origem:
para que a divergência seja detectável em vez de opinável.

## Os dois tipos

```
STATE        uma linha por snapshot de REFERÊNCIA
TRAJECTORY   uma linha por âncora, com a linhagem dos slots
```

Separados, e não um com uma coluna `kind`: nível e movimento são grandezas
diferentes, e a separação do PR-06.3 continua valendo na infraestrutura.

## O ciclo de vida

```
DRAFT -> BUILDING -> VALIDATING -> READY
                         |
                         +-> FAILED
```

`VALIDATING` é separado de `BUILDING` de propósito. Construir é escrever linhas;
validar é reconferir contra a origem. Uma projeção que falhou na validação não
é incompleta — é **completa e errada**, que é pior e merece nome próprio.

Só `READY` responde consulta.

## As amarras

Cada versão se prende a sete impressões, e cada uma responde a uma pergunta que,
sem resposta, permitiria uma consulta silenciosamente errada:

```
dataset + versão      é daquele conjunto
referência            o ajuste é aquele
plano                 os eixos significam o mesmo
artefatos             a escala é a mesma
universo              quem é candidato não mudou
codificação           o payload reconstrói o mesmo float64
```

E na trajetória, mais três: janela, perfil e cobertura do PR-06.3.

## Identidade semântica contra identidade física

```
entra na impressão      chave semântica, payload, linhagem, políticas
NÃO entra               version_id, id do PostgreSQL, ordem de inserção,
                        carimbo de tempo, localização física
```

Duas construções independentes do mesmo conteúdo têm **impressões iguais e
`version_id` diferentes**. É isso que torna a projeção verificável.

## A contabilidade da construção

Toda linha lida cai em exatamente um balde:

```
indexada     virou linha da projeção
recusada     não pôde, e o MOTIVO está dito
```

`assert_reconciles()` recusa fechar quando `lidas != indexadas + recusadas`. Uma
projeção menor que a origem sem explicação seria um universo incompleto antes
de qualquer consulta.
