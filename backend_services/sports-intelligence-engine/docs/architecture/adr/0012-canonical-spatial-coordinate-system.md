# ADR-0012 — Sistema canônico de coordenadas

**Status:** aceito · **Data:** 2026-08-12

## Contexto

Times trocam de lado no intervalo. Provedores discordam sobre a origem: uns
põem (0,0) no canto inferior esquerdo, outros no centro, outros invertem o
eixo Y. As dimensões do campo variam — 105 por 68 metros é padrão e não é
obrigatório.

Um chute a cinco metros do gol vira um chute do próprio campo dependendo de
quem descreveu, e a coordenada continua sendo um par de números perfeitamente
válido. Comparar coordenadas de referenciais diferentes é somar metros com
jardas sem que nada falhe.

## Decisão

**Coordenadas normalizadas em [0,1]**, nunca em metros. Comparar 30 metros do
Maracanã com 30 metros de um campo menor compara frações diferentes do campo.

**`ATTACKING` é o referencial canônico:**

```
x = 0.0   o próprio gol de quem executa a ação
x = 1.0   o gol adversário
```

Assim um chute perigoso é `x ≈ 0.95` sempre — primeiro tempo, segundo tempo,
mandante, visitante. É o que torna duas partidas comparáveis sem que cada
consumidor saiba para que lado cada time atacava.

**`ABSOLUTE` existe e é declarado**, para o que é do estádio e não do time:
posição de câmera, lado do banco.

**O referencial viaja com a coordenada, e `assert_comparable` recusa** a
comparação entre frames diferentes. `distance_to_opponent_goal` só existe em
`ATTACKING` — em `ABSOLUTE` não há "gol adversário".

**Sem NumPy** para guardar dois floats.

## Consequências

**Ganhamos:** comparação histórica independente do lado físico e do tamanho do
campo. Um erro de referencial vira exceção em vez de número plausível.

**Pagamos:** o adapter de cada provedor precisa converter — e precisa saber
para que lado o time atacava em cada período, que é informação que nem toda
fonte publica de forma direta.

## Alternativas consideradas

**Metros com dimensões declaradas.** Rejeitado: exige a dimensão real de cada
estádio, que raramente vem, e a comparação entre campos de tamanhos diferentes
continuaria enganosa.

**Um referencial só, absoluto.** Rejeitado: obrigaria todo consumidor a saber
quem atacava para onde, e a maioria erraria no segundo tempo.

