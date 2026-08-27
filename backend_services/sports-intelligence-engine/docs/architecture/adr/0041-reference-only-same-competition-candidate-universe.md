# ADR-0041 — O universo de candidatos históricos é só REFERÊNCIA, da mesma competição, no mesmo instante

**Status:** aceito · **Data:** 2026-08-26

## Contexto

Com o dataset normalizado publicado (ADR-0040), a pergunta seguinte é a
primeira que qualquer recuperação precisa responder — e ela vem **antes** de
qualquer discussão sobre distância:

> Dado um snapshot, **quem pode ser comparado com ele?**

A tentação é tratá-la como filtro de conveniência: pega tudo, calcula a
distância, ordena. Isso produz um top-K perfeitamente plausível e errado por
quatro motivos diferentes, e nenhum deles aparece no número.

**Candidatos de AVALIAÇÃO.** O PR-05.5.2 provou `ArtifactSet = f(REFERENCE)`: a
escala foi calibrada sem enxergar nenhuma partida de avaliação. Um candidato de
avaliação seria medido por uma régua que ele ajudou a definir — e o valor sairia
na mesma faixa dos demais.

**Ligas cruzadas.** A normalização é por competição (ADR-0035). Comparar um
`xg_home_5m` normalizado pela mediana da Premier com outro normalizado pela
mediana do Brasileirão é comparar dois desvios de distribuições diferentes: os
dois são «0,8 robusto» e não significam a mesma coisa.

**Instantes diferentes.** `minute` é uma dimensão do espaço. Sem alinhamento
temporal, a diferença de relógio entre o minuto 20 e o 85 vira a maior parcela
de uma distância que deveria falar de futebol — e o vizinho mais próximo passa a
ser «o estado mais próximo no tempo», e não no jogo.

**A própria partida.** A atomicidade da divisão normalmente já impede isso.
«Normalmente» não é garantia, e um candidato da mesma partida no mesmo minuto
tem distância zero por construção.

## Decisão

**O universo de candidatos é definido por uma política imutável, fechada e
impressa, e ela é exatamente esta equação:**

```
Candidates(q) = { c ∈ REFERENCE :
                    Competition(c) = Competition(q)
                  ∧ TimePoint(c)   = TimePoint(q)
                  ∧ Match(c)      ≠ Match(q) }
```

Nome da política da V1:

```
SAME_COMPETITION_REFERENCE_EXACT_TIMEPOINT_V1
```

**As queries vêm de AVALIAÇÃO; os candidatos, de REFERÊNCIA.** A configuração é
causal de ponta a ponta: a partida da query não participou da escala que a mede,
e nenhum candidato foi calibrado por ela.

**O alinhamento temporal é EXATO** (`EXACT_MATCH_TIME_POINT_V1`). Um candidato
precisa ocupar a mesma posição de jogo: mesma fase, mesmo minuto, mesmo
acréscimo, mesmo desempate. Como a `SnapshotGridPolicy` constrói todo corte com
acréscimo `0` e sem sequência, as duas últimas componentes são constantes **da
grade** — e são conferidas, não descartadas: um corte com acréscimo chegando
deste dataset é defeito a montante, e para.

**Não há amostragem.** Nem reservoir, nem semente, nem «as primeiras dez mil
linhas», nem recorte por temporada, nem teto de candidatos. O catálogo
`CandidateSampling` tem **um** membro — `NONE` —, e ele existe com um membro só
justamente para que a ausência de amostragem seja um campo conferível e entre na
impressão.

**Não há filtro por identidade nem por desfecho.** Nada de mesmo time, mesmo
adversário, mando de campo; e nada de vencedor, placar final, próximo gol ou
classificação. O primeiro compararia quem produziu o estado em vez do estado; o
segundo escolheria os vizinhos pela resposta.

**Não há queda para outra competição.** Uma liga com poucos candidatos devolve
poucos candidatos. Completar o top-K com outra liga produz um `K` cheio e falso.

## A impressão do universo

Ela cobre a política, a competição, o instante, a chave da query e as
**identidades semânticas** dos candidatos — `(chave, digesto)` — em ordem
canônica. E não cobre:

```
chave de objeto     duas gravações do mesmo conteúdo são o mesmo universo
id de banco         idem
ordem de iteração   idem — a impressão é sobre o CONJUNTO ordenado
carimbo de tempo    idem
```

A referência que entra é `normalized_reference_content_fingerprint`, **e nunca a
global**: a global cobre as duas metades, e usá-la faria uma partida
acrescentada à avaliação mudar a impressão do universo sem que candidato nenhum
mudasse.

## Consequências

**As duas invariantes são verificáveis, e são verificadas.**

```
∂ CandidateUniverse   / ∂ EVALUATION_outra  =  0
∂ CandidateUniverse_A / ∂ REFERENCE_B       =  0    para A ≠ B
```

**A violação PARA, em vez de ser filtrada.** O retriever confere competição e
instante de cada candidato que recebe, mesmo com o leitor já podando por
prefixo. Defesa em profundidade: um adaptador novo — um duplo, um leitor
diferente — entregaria candidatos errados sem que nada denunciasse.

**A exclusão da própria partida é contada, e não silenciosa.** Ela aparece como
`SAME_MATCH` no relatório de inelegibilidade, separada de `INCOMPLETE_PROFILE`:
a primeira é estrutural — não deveria acontecer —, a segunda é o número normal.

**O universo fica pequeno.** Com a grade produzindo uma linha por partida por
minuto, o universo de um instante numa competição tem o tamanho do número de
partidas de referência daquela liga — centenas, não milhões. Isso é consequência
direta do alinhamento exato, e é o que torna a varredura exaustiva viável.

**Políticas temporais mais flexíveis vão precisar de uma decisão nova.** Uma
janela de ±1 minuto multiplicaria o universo por três e traria de volta a
pergunta que o alinhamento exato evita: quanto custa o deslocamento de relógio
dentro da distância? Ela não é respondível hoje, e por isso a janela não existe.

## Alternativas descartadas

**Candidatos de todo o dataset.** Vazamento de escala pelo lado da avaliação.

**Cross-competition com normalização global.** Exigiria refazer o ADR-0035, e
apagaria a diferença entre ligas — que é justamente o que se quer medir.

**Janela temporal de ±N minutos.** Descrita acima: o custo do deslocamento vira
parte da distância sem ninguém ter decidido quanto ele vale. E minutos
adjacentes da mesma partida são quase idênticos, então o top-K viraria «os
cinco minutos vizinhos do mesmo jogo».

**Amostragem para conter o custo.** Ela é a forma mais natural de um oráculo
deixar de ser oráculo. Se o universo crescer a ponto de a varredura doer, a
resposta é um índice (PR-06.4) medido contra este resultado — e não um oráculo
mais barato e menos verdadeiro.
