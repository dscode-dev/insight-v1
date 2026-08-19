# O corpus histórico canônico

Como um byte bruto vira um corpus publicado, imutável e reproduzível — e o que
cada etapa recusa fazer.

---

## O caminho inteiro

```
arquivo bruto        object store, imutável, endereçado por conteúdo   PR-02
   │
   ▼ resolução       texto da fonte → id canônico, com evidência       PR-03
   │
   ▼ fusão           várias fontes → um candidato por partida          PR-03.1
   │
   ▼ qualidade       seis eixos, cobertura, licença — por PARTIDA      PR-04.1/2
   │
   ▼ build           fatos canônicos no PostgreSQL, com linhagem       PR-04.2
   │
   ▼ eventos         uma linha por EVENTO → CanonicalMatchEvent        PR-04.4.1
   │
   ▼ COMPOSIÇÃO      quais fatos E QUAIS EVENTOS formam ESTE corpus    PR-04.3
   │                                                                  PR-04.4.2
   ▼ PUBLICAÇÃO      conferência, congelamento, manifesto              PR-04.3
   │
   ▼ HISTORICAL_CANONICAL_READY
```

**Os eventos entram pelo lado**, e não no meio da fila da partida: eles são
construídos por execuções PRÓPRIAS (`CanonicalEventBuildRun`), sobre partidas
que já existem. A composição é onde os dois caminhos se encontram.

E o que vem depois **não é este PR**: feature, `MatchStateVector`, índice
vetorial e similaridade são o PR-05. `HISTORICAL_CANONICAL_READY` ≠
`HISTORICAL_VECTOR_ACTIVE`.

---

## `CanonicalFacts ≠ PublishedHistoricalCorpus`

A distinção que o PR-04.3 inteiro existe para estabelecer.

**Os fatos canônicos são globais.** O registro contém tudo que qualquer build
já escreveu — inclusive o que um build de PESQUISA produziu e o corpus
comercial não pode conter. Ele cresce depois de qualquer publicação.

**O corpus publicado é um recorte declarado e congelado.** Ele diz: estas
partidas, estas famílias, sob estas políticas, produzidas por estas execuções.

Três razões pelas quais a pertinência é **gravada** e nunca derivada:

```
o registro é global          «tudo que está lá» traria o build de pesquisa
                             para dentro do corpus comercial
a mesma partida varia        ela entra na 1.0 com ODDS e na comercial sem
derivar por data quebra      uma correção de placar mudaria o conteúdo de uma
                             versão publicada sem mudar o nome dela
```

**E isso vale duas vezes para EVENTO** (PR-04.4.2). «Os eventos da partida que
está no corpus» é falso das duas pontas: uma versão pode publicar a partida SEM
eventos — porque não declarou execução de evento nenhuma, ou porque a licença
os excluiu do escopo comercial — e o registro de eventos também é global e
cresce depois da publicação. Por isso a pertinência de evento é uma tabela
própria, `historical_canonical_event_members`, com uma linha por
`(versão, evento)`.

**O fato não é duplicado.** `historical_canonical_members` aponta para
`matches`; não copia a partida. Duplicá-la faria a mesma partida existir cinco
vezes com cinco ids — o que a resolução passou três PRs impedindo.

---

## A composição

Uma varredura em lotes sobre a interseção «fatos canônicos **que estes builds
autorizaram**». A pergunta não tem resposta no registro sozinho nem na linhagem
sozinha — ela é o cruzamento, e ele acontece no banco.

```
para cada lote de 500 partidas:
    ler os fatos (partida, resultado, escalações, odds)      1 consulta + 2
    ler os vereditos daquele lote                            1 consulta
    absorver no acumulador                                   memória constante
    gravar a pertinência                                     1 escrita
    ler as decisões por família                              1 consulta
    escrever os pedaços de Parquet do lote                   por partição
```

**Memória constante.** O que sobrevive entre lotes é o acumulador — contadores
e uma impressão de 32 bytes. Os fatos do lote anterior já foram gravados e
descartados. Medido: 2.000 registros → 5,7 MB; 8.000 registros → 6,5 MB.

### A mesma partida em vários builds

O PR-04.3 evitava a partida em dobro com `DISTINCT ON (match_id) … ORDER BY
created_at DESC`. Isso DEDUPLICA, e ao deduplicar responde uma pergunta que
ninguém fez: **«qual build vence?»**. Um build vencia por ser mais recente, e
com ele venciam as famílias que ele incluiu e a linhagem que ele registrou. As
do outro sumiam, em silêncio.

O PR-04.3.1 tirou a decisão do SQL. A leitura devolve **uma linha por (partida,
build)**; quem as junta é `domain/corpus/composition.py`, e ele distingue
quatro situações que `DISTINCT ON` não distinguia:

```
identidade repetida      dois builds falam da MESMA partida — o normal quando
                         duas temporadas são construídas em execuções diferentes

fato EQUIVALENTE         os dois afirmam o mesmo. UM membro, DUAS linhagens.
                         Nenhum vence, porque não há disputa.

famílias COMPLEMENTARES  A trouxe ODDS, B trouxe LINEUP. O corpus recebe a
                         UNIÃO — e os fatos são MESCLADOS, não eleitos: eleger
                         um portador escreveria uma família vazia enquanto o
                         manifesto prometeria as duas.

fato CONFLITANTE         os dois afirmam coisas diferentes. NADA é publicado;
                         a versão termina em FAILED e alguém decide.
```

**Escopos de uso incompatíveis são recusados antes de qualquer escrita.** Um
build de pesquisa e um comercial não formam uma versão: a composição uniria as
famílias, e a união de um corpus comercial com um de pesquisa é um corpus de
pesquisa com rótulo comercial — as odds restritas que a política comercial
acabou de excluir voltariam pela porta do outro build.

**A linhagem é plural.** `historical_canonical_member_builds` guarda uma linha
por contribuição, com a avaliação e a PARCELA de famílias de cada build. O
membro guarda a UNIÃO. As duas coisas são diferentes e as duas importam.

**A página é cortada no fim da última partida completa.** As contribuições de
uma partida podem cair em páginas diferentes; compor a partida em duas metades
gravaria metade da linhagem em cada. O corte custa reler no máximo uma partida
por página.

**Idempotente por `(version_id, match_id)`.** Um retry depois de um timeout
parcial reescreve o lote inteiro e não duplica nada.

---

## A impressão do corpus

```
corpus_fingerprint = SHA-256(
    "INSIGHT:HISTORICAL_CANONICAL_CORPUS:FINGERPRINT:V1"
    ‖ frame("header",  {algoritmo, versão do contrato, escopo})
    ‖ frame("member",  membro₁)          em ordem de match_id
    ‖ …
    ‖ frame("member",  membroₙ)
    ‖ frame("trailer", {contagens})
)

algorithm         canonical-sha256-v1
schema_version    1.0
```

**POR QUE NÃO É MAIS XOR** (PR-04.3.1). O PR-04.3 acumulava com XOR-fold, e a
propriedade que o justificava era boa — comutativo, então o lote não vazava
para o resultado. O problema é algébrico e não some com constraint:

```
H(A) ⊕ H(A)         = 0
H(A) ⊕ H(A) ⊕ H(B)  = H(B)
```

Um item repetido se CANCELA: `[A, A, B]` produzia a impressão de `[B]`, e o
corpus dizia não conter A. A duplicata era impedida por fora — chave primária,
guarda no acumulador —, mas a impressão é a autoridade de entrada de toda a
matemática que vem depois, e ela não pode depender de guardas externas para não
ter uma colisão trivial.

**O que entrou no lugar:** hash SEQUENCIAL sobre ordem canônica explícita. A
comutatividade foi substituída por algo mais forte — a ordem é IMPOSTA na
leitura (`ORDER BY match_id`) e VERIFICADA na acumulação. Membro fora de ordem
ou repetido vira ERRO, no lugar em que acontece.

**Três defesas que o XOR não tinha:**

```
ordem estritamente crescente   duplicata e desordem viram erro
framing por tamanho            «AB»+«C» e «A»+«BC» não colidem
separador de domínio           a construção não é reaproveitável por acidente
```

**O que entra:** escopo de uso, escopo declarado, os membros (identidade,
famílias e digest do conteúdo) e as contagens.

**O que NÃO entra:** nome do dataset, número da versão, impressões de política,
ids de execução, carimbos de tempo, ids de linha. A política saiu no PR-04.3.1
por uma razão explícita: ela só é relevante para o conteúdo quando MUDA o
conteúdo — e aí os membros já mudaram. Incluí-la só acrescentaria falsos
negativos. Ela continua no MANIFESTO, que é conteúdo + procedência.

```
corpus_fingerprint   «é o mesmo CONTEÚDO?»
manifest             «é o mesmo conteúdo, produzido do mesmo JEITO?»
manifest_sha256      «é o mesmo ARQUIVO?»
```

**O digest de cada membro cobre o CONTEÚDO** — placar, escalações, odds — e não
só a identidade. Sem isso, dois corpus com as mesmas partidas e placares
diferentes teriam a mesma impressão.

Medido: lote 250 e lote 2.000 sobre 4.000 partidas produzem a mesma impressão.

---

## O gate

A publicação confere **contra o banco**, não contra o que a composição disse
ter feito:

```
contagem gravada  ==  contagem do manifesto     um lote perdido ou em dobro
match_count       ==  contagem gravada          a versão não pode mentir
impressão gravada ==  impressão do manifesto    o conteúdo não mudou no meio
manifesto existe e é do schema conhecido
```

E ela **não conserta nada**: discordância vira `FAILED` e uma versão nova, nunca
um ajuste na publicada.

Medido: 7 consultas para publicar um corpus de 10.000 partidas — a conferência
é por agregação, e não por varredura.

---

## Eventos no corpus

**A versão DECLARA quais eventos publica.** `VersionInputs.event_build_run_ids`
lista as execuções de canonicalização que entram; vazio é uma declaração
legítima — «esta versão não publica eventos» —, e é o que toda versão anterior
ao PR-04.4.2 é.

```
historical_canonical_event_members         uma linha por (versão, evento)
historical_canonical_event_member_builds   as execuções que o produziram
historical_canonical_version_event_builds  as execuções que a versão declarou
```

**Uma pertinência, várias linhagens.** Duas execuções que produziram o MESMO
evento — reprocessamento, com id derivado — contribuem duas linhagens e uma
pertinência. Guardar uma execução só apagaria metade da resposta a «de onde
veio este evento».

**Conteúdo conflitante bloqueia.** Se a mesma identidade canônica chega com
conteúdo diferente, nada é publicado: a identidade afirma serem o mesmo evento
e o conteúdo afirma o contrário, e escolher um seria o motor decidindo qual
versão da história é verdade. O registro grava um `content_digest` do FATO — sem
o estado do ciclo de vida — exatamente para poder recusar isso.

**O que os eventos mudam na impressão.** Eles entram no conteúdo de cada
membro, então:

```
mesmas partidas, um evento a mais       → corpus DIFERENTE
mesmas partidas, uma correção nova      → corpus DIFERENTE
mesmos eventos, lote/ordem diferentes   → corpus IGUAL
```

Um corpus sem eventos imprime hoje exatamente o que imprimia antes deste PR: a
chave `events` só aparece no conteúdo quando há evento, e é isso que mantém as
versões já publicadas reproduzíveis.

**O arquivo.** `family=EVENT/competition=…/season=…/part-00000.parquet`, com
schema declarado e zstd, ao lado das outras famílias. Uma linha é um evento —
nunca `event_1_type` (ADR-0028). Coordenada ausente é `NULL`, e `xg = 0.0` é um
valor observado que não se confunde com xG não medido.

**O gol do evento NÃO é o placar.** `events.parquet` pode conter `GOAL`, e a
autoridade sobre o resultado continua sendo a família `MATCH` — `home_goals`,
`away_goals`, prorrogação e pênaltis. Os dois descrevem coisas diferentes: um
diz «aos 23 minutos, este jogador marcou», o outro diz «o jogo terminou 2 a 1».
Derivar o placar contando gols seria trocar um fato declarado por uma soma que
erra sempre que a fonte de eventos estiver incompleta — e é justamente quando
ela está incompleta que ninguém percebe.

Pelo mesmo motivo, **odds não entram em `events.parquet`**: elas são família
própria, com granularidade própria (casa × mercado × seleção × instante).

**A cobertura.** Duas famílias saem do que foi publicado, e não da declaração
da fonte:

```
EVENT     AVAILABILITY_ONLY   não há denominador honesto para «quantos eventos
                              esta partida DEVERIA ter» — e inventar um
                              produziria porcentagem que parece medida
SPATIAL   MEASURED            com coordenada ÷ espacialmente ELEGÍVEIS. O
                              apito final e o cartão não entram no
                              denominador: eles não acontecem num ponto
```

---

## Pesquisa e comércio coexistem

A MESMA avaliação produz corpus diferentes por escopo de uso, e os dois são
igualmente corretos:

```
avaliação
  ├─ build RESEARCH   → corpus de pesquisa    MATCH + ODDS + EVENT
  └─ build COMMERCIAL → corpus comercial      MATCH   (ODDS e EVENT restritos
                                                       excluídos por licença)
```

**Com eventos a diferença fica maior, e continua sendo a mesma regra.** Uma
execução de canonicalização de evento tem escopo próprio: a comercial recusa
evidência `RESEARCH_ONLY` na hora de construir, então o corpus comercial
simplesmente não tem aqueles eventos para publicar. Compor um corpus comercial
com execuções de evento de pesquisa é recusado — seria trazer de volta, pela
porta do evento, o dado restrito que a política acabou de excluir.

**E o núcleo da partida não é degradado por isso.** Excluir a família `EVENT`
por licença remove eventos, e não a partida.

**A identidade da partida é a MESMA nos dois.** O que muda é o conjunto de
famílias materializadas — nunca o `MatchId`, nunca a existência da partida. E as
impressões são diferentes, porque os conteúdos são diferentes.

O manifesto comercial registra a exclusão com o motivo E a licença, e distingue
`licenses_present` de `independent_support` — a fronteira que o PR-04.2.1
provou nos dois sentidos (ADR-0025).

---

## O que o PR-05 pode ler — e o que ele não deve

```
FeatureBuilderInput = HistoricalCanonicalDatasetVersion
```

**A entrada autorizada é a versão publicada.** Partida, resultado, escalação,
odds e evento estão todos lá, numa versão imutável com impressão própria e
manifesto que descreve o que ela contém. Um `MatchStateVector` calculado sobre
a `1.0` continua explicável pela `1.0` daqui a dois anos.

**`FusionRun`, `ResolutionRun`, `SourceRecord` e os datasets brutos NÃO são
entrada de feature.** Não é uma questão de conveniência: ler o bruto
contornaria as decisões de qualidade, de licença e de pertinência que a versão
carrega — e um resultado calculado assim não seria explicável pela versão que
ele diz ter usado. Eles continuam existindo para a AUDITORIA, que percorre o
caminho ao contrário.

A seta tem um sentido só, e há teste de arquitetura para os dois lados: o
corpus não importa código de feature, e só uma versão `READY` ou `SUPERSEDED` é
legível como corpus.

---

## Baseline

- `docs/performance/PR04_CANONICAL_CORPUS_BASELINE.md` — 12.500 registros →
  10.000 partidas, do bruto ao `READY`.
- `docs/performance/PR04_EVENT_CORPUS_BASELINE.md` — as mesmas 10.000 partidas
  com 100.000 eventos publicados, com o custo do evento isolado.

---

## Documentos relacionados

- ADR-0026 — versões imutáveis, e por que a aresta `DRAFT → READY` não existe
- ADR-0027 — PostgreSQL é a verdade; o Parquet é representação
- ADR-0025 — elegibilidade canônica ciente de licença
- `docs/contracts/HISTORICAL_CANONICAL_MANIFEST_V1.md`
- `docs/contracts/HISTORICAL_CANONICAL_DATASET_V1.md`
- `docs/data/CANONICAL_BUILD_CORE.md` — o degrau anterior
- ADR-0028 — registro de evento é entidade repetida, e chega ao corpus assim
- `docs/data/HISTORICAL_EVENT_CANONICALIZATION.md` — como o evento é construído
- `docs/data/HISTORICAL_EVENT_CONTRACT.md` — o que uma fonte de evento declara
