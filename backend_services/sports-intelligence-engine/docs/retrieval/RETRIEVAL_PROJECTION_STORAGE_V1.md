# O armazenamento da projeção

**PR:** 06.4

## O payload exato

```
bytea, IEEE-754 binary64, little-endian
um valor por eixo canônico
um byte de máscara por eixo
```

`CHECK (octet_length(exact_values) = octet_length(exact_mask) * 8)` — um payload
de outro espaço de eixos decodificaria em silêncio e produziria distância sobre
dimensões que não se correspondem. O esquema recusa antes.

## Por que `bytea` e não JSON nem `float8[]`

Medido nesta instalação, 29 `float64`:

```
bytea               236 B
double precision[]  256 B
```

O tamanho decidiu pouco. O que decidiu foi o **controle**: aqui a ordem dos
bytes é declarada (`<`), e o mesmo vetor produz a mesma sequência em qualquer
máquina. Sem isso, indexar num ARM e ler num x86 daria digestos diferentes para
conteúdo idêntico.

## Sem `float32`

Não há conversão para precisão simples em lugar nenhum do caminho de produção.
Houve, enquanto o ANN era avaliado — o `vector` do pgvector é `binary32` e perde
bits, o que foi medido:

```
0.3333333333333333  ->  0.33333334
16777217            ->  16777216
```

Era justamente por isso que o payload exato precisava viajar ao lado do vetor. O
ANN saiu; o payload exato ficou, porque ele é o que a projeção sempre foi.

## A máscara é uma coluna

Um byte por eixo, e não um bit. A economia de 25 bytes por linha não paga a
segunda convenção — ordem de bits além de ordem de bytes — e a máscara já é
pequena perto dos 232 bytes dos valores.

Ela existe porque **`0.0` observado e ausente são estados diferentes** que o
número sozinho não separa.

## A linhagem da trajetória

`slot_lineage jsonb`: por slot, o horizonte, o status, o instante alcançado, a
chave de origem e o digesto dela.

`jsonb` e não `bytea` porque o tipo do dado é outro: os deslocamentos são
numéricos e quentes, e por isso binários; isto é metadado pequeno (três slots) e
auto-descritivo.

## Os índices

```
(projection_version_id, competition, period, minute, stoppage, tie_break)
(projection_version_id, match_id)
```

O primeiro é a conjunção inteira de `EXACT_MATCH_TIME_POINT`; o segundo serve à
exclusão da própria partida. O planejador os usa sem dica nenhuma — verificado
por `EXPLAIN (ANALYZE, BUFFERS)`, sem `enable_seqscan = off`.
