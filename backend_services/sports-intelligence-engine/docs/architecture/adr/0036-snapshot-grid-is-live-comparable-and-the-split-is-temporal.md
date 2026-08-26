# ADR-0036 — A grade de snapshots é comparável ao vivo, e a divisão é temporal e atômica

**Status:** aceito · **Data:** 2026-08-24

## Contexto

O motor sabe calcular features de uma partida num corte (PR-05.4). Falta
transformar isso num **conjunto**: quais cortes, de quais partidas, separados
como, congelados sob que nome.

A pergunta parece de engenharia e tem duas decisões científicas dentro, cada uma
com uma resposta defensável e várias plausíveis que produzem números excelentes
e sem significado.

**Quais cortes.** «Todos» não existe: o relógio de futebol tem acréscimo, tem
intervalo, tem prorrogação e tem pênaltis, e nem todos são minutos comparáveis
entre partidas. «Um por partida» desperdiça 90% do sinal. E há um contrabando
silencioso: um corte que a produção nunca conseguirá reproduzir — o minuto
`45+2`, o intervalo, o apito final — entra na população que ajusta escalas e
define vizinhança, e passa a influenciar respostas sobre estados que ele nunca
poderá descrever.

**Como separar.** A divisão óbvia é sortear linhas. Sobre snapshots ela produz o
vazamento mais bem disfarçado que existe:

```
minuto 62 do jogo X  →  treino
minuto 63 do jogo X  →  avaliação
```

As duas linhas descrevem quase o mesmo estado. A avaliação passa a medir a
capacidade de reencontrar o mesmo jogo um minuto depois, e o resultado é ótimo e
vazio.

Há ainda uma terceira tentação, menor e igualmente cara: carimbar cada corte
intra-jogo com um instante de parede. `kickoff + minuto` parece o momento
daquele minuto do jogo, e é uma fabricação — ela ignora o intervalo, os
acréscimos e as interrupções.

## Decisão

**A grade é o conjunto dos cortes que a produção consegue reproduzir, e a
divisão é temporal e atômica por partida. As duas são políticas versionadas e
impressas.**

```
LIVE_COMPARABLE_MINUTE_GRID_V1     1 pré-jogo + 45 + 45 = 91 cortes
TEMPORAL_MATCH_ATOMIC_SPLIT_V1     kickoff < fronteira ⇒ REFERENCE
```

Seis consequências:

**1. O critério da grade é a comparabilidade ao vivo, e não a exaustividade.**
Ao vivo o motor recebe um estado num minuto de relógio; um corte histórico que
não possa existir ao vivo nunca será consultado, e não deveria ter voz na
população. Ficam de fora o acréscimo (o corpus não publica a duração dele, então
`45+1` existe num jogo e não noutro), o intervalo, o apito final e os pênaltis —
cada um com motivo nomeado num catálogo de exclusões que vai **dentro do
manifesto**.

**2. A prorrogação exige prova canônica.** Evento carimbado em período de
prorrogação, ou `MatchResult` com placar de prorrogação. `ExtraTimeRule.ALWAYS`
não existe no enum: materializar 91..120 «por garantia» inventaria trinta linhas
de estado para cada jogo que terminou aos 90. `stage` não é prova — mata-mata se
decide no tempo normal o tempo todo.

**3. O corte intra-jogo NÃO tem instante de conhecimento, e o pré-jogo tem.**
A causalidade dentro do jogo é sustentada pela **posição**, que o corpus publica
de verdade. O pré-jogo usa o pontapé canônico, que também é real — e é ele que
impede uma cotação publicada depois do apito de entrar num snapshot rotulado
como pré-jogo. Um corte fabricado seria pior que corte nenhum, porque parece
prova.

**4. A divisão é atômica POR PARTIDA e a fronteira é um INSTANTE.** As duas
regras juntas, porque nenhuma basta sozinha: sem atomicidade, um jogo atravessa
a fronteira e fica dos dois lados; sem temporalidade, dois jogos da mesma rodada
compartilham calendário e mercado através da divisão. A assinatura
`assign(kickoff) -> DatasetSplit` torna a atomicidade estrutural: quem recebe um
apito e devolve uma metade não consegue dar respostas diferentes para dois
minutos do mesmo jogo.

**5. A fronteira é declarada pelo operador, e não derivada de percentil.** Um
percentil faz a fronteira mudar quando o corpus cresce — dois datasets «80/20»
construídos com um mês de diferença teriam fronteiras diferentes sob o mesmo
nome. Não há semente, não há proporção, e o tipo não tem onde guardá-las.

**6. `REFERENCE` e `EVALUATION`, e não `TRAIN`/`TEST`.** Nada é treinado: a
metade de referência é a população que o motor consulta. `train` traria a
expectativa de gradiente, época e validação, e nenhuma delas existe. Uma terceira
metade exigiria uma segunda fronteira e uma decisão sobre o que ela serve — as
duas seriam inventadas sem que ninguém precisasse delas.

**Um pontapé canônico só.** `actual_kickoff or scheduled_kickoff`, definido num
lugar. Se a grade usasse um e a divisão usasse o outro, uma partida adiada cairia
numa metade e teria o corte pré-jogo carimbado na outra.

## Consequências

**Positivas.** Toda linha do dataset descreve um estado que a produção sabe
reproduzir. Nenhuma partida atravessa a divisão. A fronteira é a mesma hoje e
daqui a um ano. E o tamanho da grade é uma propriedade **impressa** da versão —
duas construções sob grades diferentes se declaram incomparáveis em vez de
parecerem o mesmo dataset.

**Negativas, e assumidas.** Perde-se o acréscimo, que é onde acontece uma fração
desproporcional dos gols — e é uma perda real, não um detalhe. A grade de minuto
é grossa: dentro dela o estado muda, e o dataset não vê. A divisão temporal
produz uma avaliação que é sempre o período mais recente, então mudanças de
regra ou de calendário caem inteiras num lado só. E uma fronteira mal escolhida
produz uma metade vazia — o manifesto denuncia, e o operador tem de decidir de
novo.

**O que esta decisão NÃO fecha.** Grades mais finas, grades orientadas a evento,
cortes de acréscimo com duração publicada, divisão por competição e validação
cruzada temporal continuam possíveis — cada uma como **política nova, com nome e
versão próprios**. O que não é possível é mudar estas e manter o nome.

## Alternativas consideradas

**Um corte por partida (o minuto 60).** Rejeitada: descarta 99% do sinal e torna
o dataset inútil para consulta em qualquer outro minuto.

**Todos os minutos, incluindo acréscimo.** Rejeitada: a grade deixaria de ser a
mesma entre partidas, porque a duração do acréscimo não é publicada.

**Grade orientada a evento** («o estado imediatamente antes de cada
finalização»). Rejeitada por antecipação: é uma política legítima e responde
outra pergunta — a produção não pergunta «antes de um chute», pergunta «no
minuto 63».

**Sorteio estratificado de linhas.** Rejeitada — é o defeito central que a
atomicidade existe para impedir.

**Sorteio por partida, sem fronteira temporal.** Rejeitada: resolve a
atomicidade e deixa dois jogos da mesma rodada em metades diferentes, com
contexto de calendário e mercado formados com a mesma informação.

**Fronteira por percentil dos apitos.** Rejeitada: torna a divisão dependente do
tamanho do corpus, e o mesmo nome passa a significar coisas diferentes.

**Carimbar cada corte intra-jogo com `kickoff + minuto`.** Rejeitada: fabrica um
instante que erra por dez a vinte minutos nos jogos irregulares, e o número
resultante parece prova de conhecimento.

## Referências

- ADR-0026 — versões do dataset histórico são imutáveis
- ADR-0029 — features usam semântica temporal `AS_KNOWN`
- ADR-0031 — o estado histórico é reconstruído e nunca armazenado
- ADR-0037 — onde o dataset de features mora
- `docs/features/SNAPSHOT_GRID_V1.md`
- `docs/features/FEATURE_DATASET_SPLIT_V1.md`
