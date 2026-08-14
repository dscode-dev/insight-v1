# ADR-0014 — Imutabilidade do dataset bruto

**Status:** aceito · **Data:** 2026-08-13

## Contexto

O arquivo bruto é a única camada que não se reconstrói. Todas as outras
derivam dele; ele deriva da fonte — que muda de layout, apaga o histórico e
encerra o contrato.

A pressão para editá-lo é constante e sempre razoável no momento:

- «o CSV veio com uma coluna a mais, deixa eu tirar antes de guardar»;
- «esse arquivo estava errado, apaga e manda de novo»;
- «converte tudo para Parquet, ocupa menos espaço».

As três parecem limpeza e são a mesma coisa: destruir a evidência do que a
fonte de fato mandou. E o custo aparece no pior momento possível — quando
descobrimos que o mapeamento estava errado e precisamos reconstruir a partir
do bruto. Se ele já foi «limpo», o erro é permanente.

## Decisão

**O arquivo bruto é imutável, e a imutabilidade é imposta por ausência.**

`ObjectStorePort` não declara `delete`, `update`, `copy` nem `move`.
`RawDatasetArchivePort` também não. Não há caminho de código que alcance uma
sobrescrita — não porque uma verificação a impede, mas porque a operação não
existe.

**Nada é convertido na entrada.** Parquet é o formato preferencial interno e
isso não muda o que se guarda: o bruto permanece exatamente como chegou.
Conversão, quando existir, produz um artefato derivado **ao lado**.

**Regravar sob a mesma chave é permitido em um caso, e ele não é exceção à
regra.** A chave contém o hash do conteúdo, então um objeto sob ela só pode
ter aqueles bytes — a menos que a gravação anterior tenha parado no meio, o
que o tamanho denuncia. Regravar por cima de um fragmento truncado não
sobrescreve evidência: um fragmento nunca foi evidência de nada.

**Apagar é operação administrativa deliberada**, feita por fora, por quem
responde por ela. Não é algo que um caminho de código alcance por engano.

## Consequências

**Ganhamos:** capacidade de reprocessar tudo com um normalizador novo, sem
rebaixar nenhuma fonte. É o que torna possível

```
Raw v1 → Resolver v1 → Canonical v1
Raw v1 → Resolver v2 → Canonical v2
```

sem voltar à origem — que pode nem existir mais.

**Pagamos:** espaço. Guardamos CSVs redundantes de fontes públicas que ainda
estão no ar hoje. É barato comparado a descobrir, em 2028, que a fonte tirou o
arquivo do ar e o nosso «foi convertido para economizar espaço».

## Alternativas consideradas

**Guardar só o normalizado.** Rejeitado: um erro nosso de normalização vira
permanente, e não há como sequer detectá-lo depois.

**Guardar o bruto com retenção de 90 dias.** Rejeitado: o erro de mapeamento
que mais custa é o que ninguém percebe por meses.

**Permitir `delete` com auditoria.** Rejeitado por experiência: uma operação
destrutiva que existe é uma operação que será chamada por um script de
limpeza, e a auditoria registra a perda em vez de evitá-la.

