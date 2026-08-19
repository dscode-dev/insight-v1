# ADR-0029 — Geração de features usa semântica temporal AS-KNOWN

**Status:** aceito · **Data:** 2026-08-19

## Contexto

O corpus histórico canônico guarda a verdade FINAL de cada partida: o gol dos
63:21, a correção que o substituiu, o placar do apito final. Ele é
append-only, auditável e completo — e é exatamente por ser completo que ele é
perigoso como entrada de feature.

Uma feature histórica existe para ser comparada com uma partida ao vivo. O
estado de uma partida ao vivo aos 63 minutos contém o que se sabe **naquele
instante**: os eventos que o provedor já publicou, sem as correções que ainda
vão chegar, sem o placar final que ainda não existe. Se o replay histórico
enxerga mais que isso, o modelo aprende a comparar dois mundos diferentes.

**O caso concreto que motivou a decisão:**

```
63:21  GOAL E1                            o gol acontece
64:10  correção E2 substitui E1           o VAR corrige o autor

replay ingênuo às 63:30  →  aplica E2, porque E2 está no corpus
partida ao vivo às 63:30 →  não conhece E2, porque E2 não existe ainda
```

O replay ingênuo não erra por descuido: ele lê o corpus e o corpus tem E2. O
erro é de MODELO — falta a distinção entre *quando o fato aconteceu* e *quando
ele pôde ser sabido*.

Três desenhos ingênuos, e o que cada um quebra:

**Usar sempre a verdade final.** Simples, e produz estados que nenhuma partida
ao vivo terá. Todo modelo treinado assim tem uma vantagem que desaparece em
produção — e ela desaparece exatamente nos lances decisivos, que são os mais
corrigidos.

**Assumir `knowledge_time = effective_time`.** Parece conservador e não é: ele
declara que toda correção era conhecida no instante do lance, que é a suposição
mais otimista possível sobre latência.

**Filtrar por instante de ingestão.** O corpus tem esse carimbo, e ele é a hora
em que NÓS lemos o arquivo — meses depois, num lote. Filtrar por ele produziria
estados vazios ou completos conforme a hora do processamento.

## Decisão

**A geração de features usa semântica AS-KNOWN: um fato só entra num estado
quando ele PODERIA ter sido conhecido naquele corte.**

Quatro consequências concretas, e cada uma é uma peça de código:

**1. `EffectiveTime ≠ KnowledgeTime`, e as duas viajam separadas.** A posição na
partida (`MatchTimePoint`) ordena o que aconteceu dentro do jogo; o instante de
parede ordena o que se soube fora dele. Elas **não se convertem** uma na outra —
isso exigiria saber o instante de cada minuto de jogo, incluindo paralisação, e
o corpus não sabe.

**2. A disponibilidade temporal é CLASSIFICADA, e a classificação é versionada.**
`TemporalAvailabilityPolicy` declara, por família de fato, como ela pode ser
usada. A classificação padrão assume que um evento original é observável quando
acontece — uma aproximação declarada, que ignora a latência do provedor — e
trata correção sem carimbo como retrospectiva. Uma política estrita existe e
recusa tudo sem carimbo.

**3. `UnknownTemporalAvailability ⇒ FailClosed`.** Quando a disponibilidade não
pode ser provada e a feature exige causalidade estrita, o resultado é
indisponível com motivo tipado. Nunca o fato «porque provavelmente já era
conhecido».

**4. Dois modos, e a promessa é estrutural.**

```
AS_KNOWN          o que se sabia            → feature comparável ao vivo
CANONICAL_FINAL   o que hoje sabemos        → auditoria e retrospectiva
```

Um `FeatureSpace` que declare `live_comparable=True` **não constrói** com
`CANONICAL_FINAL`. A combinação inválida é recusada pelo objeto, e não pela
revisão de código.

**`CANONICAL_FINAL` não é passe livre**: ele dispensa a prova de conhecimento e
mantém a causalidade de ocorrência. Um gol aos 80 não faz parte de um estado de
63 sob verdade nenhuma.

## Consequências

**O que fica possível.** Reconstruir estados históricos que um sistema ao vivo
poderia ter tido, e compará-los com estados ao vivo sem vantagem retrospectiva.
É a base de qualquer similaridade honesta entre passado e presente.

**O que fica proibido.** Consultar placar final, agregado do jogo inteiro ou
correção não conhecida dentro de um estado intra-jogo. As três recusas são
tipadas e distinguíveis — `POST_MATCH_ONLY`, `RETROSPECTIVE_ONLY`,
`KNOWLEDGE_TIME_AFTER_CUTOFF` —, porque exigem correções diferentes.

**O custo que isto cobra.** Features intra-jogo ficam mais pobres do que
poderiam ser. Sem carimbo de observação no corpus, correções nunca entram num
replay causal; um provedor que publique carimbos reais melhora o resultado, e
até lá o motor prefere o estado anterior ao estado impossível.

**A suposição que fica em aberto.** «Evento original é observável quando
acontece» é aproximação, e ela está declarada na política com versão e
impressão. O dia em que a latência do provedor importar, uma política nova a
substitui — e os snapshots calculados sob a antiga continuam identificáveis,
porque a impressão da política entra na identidade deles.

## Alternativas consideradas

**Filtrar apenas por tempo efetivo.** Metade do problema resolvido, e a metade
mais fácil. Correções e cotações continuariam vazando: as duas têm tempo
efetivo anterior ao corte e conhecimento posterior.

**Guardar só o estado final e aceitar o viés.** Defensável se o objetivo fosse
análise post-hoc. Não é: o objetivo é comparar com partidas ao vivo, e o viés
aparece exatamente nos lances que mais importam.

**Recalcular a partir do bruto com um filtro temporal.** Reintroduziria o
caminho que o PR-04 fechou — feature lendo `SourceRecord` — e contornaria as
decisões de qualidade e licença que a versão do corpus carrega.
