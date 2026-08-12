# ADR-0009 — Procedência e valores ausentes

**Status:** aceito · **Data:** 2026-08-12

## Contexto

Dois problemas com a mesma assinatura: falham em silêncio e os números ficam
errados.

**Procedência.** Quando duas fontes discordam de um placar, alguma regra
decide — e se ela não estiver escrita antes, será inventada na hora. E uma
base `RESEARCH_ONLY` descoberta depois de estar no índice significa
reconstruir o índice.

**Ausência.** Um clube sem estatística tem `chutes_por_jogo` ausente. Gravado
como `0.0`, vira "não finaliza" — o extremo inferior da escala. Padronizado,
vira um z-score muito negativo, e todos os clubes sem estatística passam a
parecer parecidíssimos entre si por um motivo que não existe.

## Decisão

**Procedência** (`DataProvenance`) viaja com o dado: tipo de origem, provedor,
id na origem, os quatro carimbos de tempo, e classe de licença. A precedência
entre origens é **declarada** e estável — nunca ajustada pelos dados, porque
"de quem é este placar" precisa ter a mesma resposta amanhã.

**Ausência** (`FeatureValue`) é um tipo sem `__float__`. O número só sai por
`require()` — que falha alto — ou `or_default()` — que exige escrever o
default. `FeatureMask` acompanha o vetor e diz quais dimensões ele realmente
tem; a comparação entre dois vetores só é honesta sobre a interseção.

`Unavailability` distingue os motivos, porque a ação é diferente: não
publicado (buscar outra fonte), ainda não observado (esperar), histórico
insuficiente (resolve sozinho), recusado por validação (revisar a fonte).

## Consequências

**Ganhamos:** ausência é impossível de confundir com zero, e a pergunta "posso
publicar isto?" tem resposta sem arqueologia.

**Pagamos:** o código fica mais verboso — todo acesso a feature é explícito. É
o preço de tornar o erro impossível em vez de improvável.

## Alternativas consideradas

**`float | None`.** Rejeitado: some no primeiro `or 0.0` que alguém escreve
para calar o type checker.

**Sentinela (`-999`).** Rejeitado: é um número, entra em média, e o resultado
é pior que o zero.

