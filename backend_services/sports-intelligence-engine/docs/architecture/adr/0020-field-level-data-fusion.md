# ADR-0020 — Fusão em nível de campo

**Status:** aceito · **Data:** 2026-08-13

## Contexto

Três fontes descrevem a mesma partida. A primeira traz chutes, a segunda traz
xG, a terceira traz odds. Duas delas trazem o placar, e discordam.

A forma óbvia de combinar é `dict_a.update(dict_b)`. Ela funciona, e destrói
quatro coisas em silêncio:

```
quem venceu           a última escrita ganha, por acidente de ordem
o que foi descartado  o valor da outra fonte some
por quê               nenhuma regra foi registrada
de onde veio          a procedência por campo não existe
```

Depois disso, `home_score = 2` é um número sem pai.

## Decisão

**A unidade da fusão é o CAMPO, não o registro.** Cada campo do resultado é um
`CanonicalFieldCandidate` com valor escolhido, fonte escolhida, alternativas
preservadas, regra que decidiu, confiança e procedência.

**O default é NÃO resolver.** Um campo sem política declarada sai
`CONFLICT_UNRESOLVED`, sem valor selecionado. É a decisão mais importante
deste ADR: um default que escolhe faria todo campo não declarado produzir um
valor de aparência decidida — e ninguém revisaria, porque nada apareceria como
conflito.

**A política é POR CAMPO, e a precedência global é o que sobra.** Uma fonte é
a melhor em xG e não publica escalação; outra tem escalação boa e placar
copiado. Uma precedência global faria a primeira vencer em escalação por ser
comercial — e a escalação dela é a pior.

`INSIGHT_NATIVE` não ganha automaticamente por ser nativo; a política por
campo pode invertê-lo, com a inversão declarada.

**Média exige declaração explícita, com tolerância.** A média de dois placares
é um placar que nenhuma fonte observou. `allow_averaging` é `False` em tudo, e
a política recusa habilitá-lo sem dizer a que distância dois valores ainda
descrevem a mesma coisa.

**Concordância é evidência.** `EXACT_AGREEMENT` existe como regra própria e a
confiança cresce com o número de fontes concordantes: três fontes dizendo 2
não é o mesmo que uma dizendo 2.

**Conjuntos de observação são uma fusão DIFERENTE.** Odds de casas distintas
não são candidatas ao mesmo valor — coexistem. Deduplicação por discriminante,
nunca seleção, nunca média.

**Execuções concluídas são imutáveis.** Política nova produz execução nova.

## Consequências

**Ganhamos:** a pergunta «de onde veio este valor» é uma consulta —
`fused_field_sources` tem dataset, arquivo e linha. E «as fontes concordavam?»
também.

**Pagamos:** volume e complexidade. Um candidato com vinte campos e três
fontes gera sessenta linhas de procedência. E o operador precisa lidar com
campos em conflito em vez de receber um registro «limpo» — que é o ponto: o
conflito existe, e escondê-lo não o resolve.

## Alternativas consideradas

**Merge com precedência global.** Rejeitado — ver acima.

**Escolher sempre e marcar confiança baixa.** Rejeitado pelo mesmo motivo do
ADR-0018: na prática ninguém filtra por confiança, e um valor gravado é usado
como verdade.

**Média para tudo que é numérico.** Rejeitado: funciona para posse de bola e
falsifica placar, cartões e gols. A distinção depende do campo, e é por isso
que ela é declarada por campo.

