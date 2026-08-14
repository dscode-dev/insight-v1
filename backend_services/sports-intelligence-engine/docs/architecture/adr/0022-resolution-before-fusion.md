# ADR-0022 — Resolução antes de fusão

**Status:** aceito · **Data:** 2026-08-13

## Contexto

Duas linhas de fontes diferentes parecem descrever a mesma partida: mesmos
nomes de clube, mesma data. A tentação é combiná-las e descobrir depois qual
partida é.

Isso inverte a ordem, e a inversão é cara de duas maneiras.

A primeira: o merge acontece por SEMELHANÇA, sem decisão registrada. Não há
evidência, não há confiança, não há alternativa preservada, não há fila de
revisão. Se estiver errado, não há nem como descobrir — o registro fundido não
guarda de onde veio.

A segunda é mais sutil. Combinar primeiro cria pressão para resolver depois
com MENOS informação: o registro fundido já misturou campos de duas fontes, e
a identidade passa a ser inferida sobre um objeto que nenhuma fonte produziu.

## Decisão

```
IDENTIDADE  →  AGRUPAMENTO  →  FUSÃO
```

Nesta ordem, e a ordem é imposta pelo TIPO — não por convenção.

`FusionEngine.fuse` aceita `FusionGroup`, que contém `ResolvedSourceRecord`, e
`ResolvedSourceRecord` **não se constrói** sem `resolution_decision_id`. Não
existe caminho de código que funda registros cuja identidade não foi provada.

**Só decisões `RESOLVED` produzem registros fundíveis.** Um registro cuja
partida ficou `AMBIGUOUS` simplesmente não aparece em grupo nenhum, e a
diferença entre lidos e agrupados é reportada.

**A ordem interna da resolução também é obrigatória:**

```
competição → temporada → time → partida
```

Cada etapa consome o que a anterior resolveu, e a cadeia para na primeira que
não resolve. Resolver partida antes de time significaria resolver time por
dentro, sem evidência nem decisão registrada.

**O banco reforça:** `fusion_group_records.resolution_decision_id` é
`NOT NULL`, e há `UNIQUE (group_id, provider_id)` — duas linhas da mesma fonte
no mesmo grupo são duplicata interna, não confirmação, e contá-las como duas
fontes inflaria a concordância.

**Testes de arquitetura guardam a fronteira:** o pacote de fusão não importa o
de resolução, e nenhuma função com nome de resolução pode ser definida nele.

## Consequências

**Ganhamos:** todo valor fundido tem uma cadeia completa até o arquivo bruto —
campo → contribuição → registro → decisão → execução → manifesto → bytes. E a
garantia não depende de ninguém lembrar da regra.

**Pagamos:** registros não resolvidos não entram na fusão, então a cobertura
do candidato depende da qualidade da resolução. Um dataset com muitos casos
ambíguos produz poucos grupos — o que é honesto e é visível na contagem.

## Alternativas consideradas

**Fundir por semelhança e resolver o resultado.** Rejeitado — ver contexto.

**Permitir fusão «provisória» de registros não resolvidos, marcada como tal.**
Rejeitado: um registro provisório gravado é um registro que alguém vai
consultar. A marca não protege — é a mesma razão pela qual só `RESOLVED`
produz referência canônica.

**Impor a ordem por convenção documentada.** Rejeitado: convenção sobrevive
até a primeira sexta-feira apertada. O tipo não.

