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
   ▼ COMPOSIÇÃO      quais fatos formam ESTE corpus                    PR-04.3
   │
   ▼ PUBLICAÇÃO      conferência, congelamento, manifesto              PR-04.3
   │
   ▼ HISTORICAL_CANONICAL_READY
```

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

## Pesquisa e comércio coexistem

A MESMA avaliação produz corpus diferentes por escopo de uso, e os dois são
igualmente corretos:

```
avaliação
  ├─ build RESEARCH   → corpus de pesquisa    MATCH + ODDS
  └─ build COMMERCIAL → corpus comercial      MATCH   (ODDS excluída por licença)
```

**A identidade da partida é a MESMA nos dois.** O que muda é o conjunto de
famílias materializadas — nunca o `MatchId`, nunca a existência da partida. E as
impressões são diferentes, porque os conteúdos são diferentes.

O manifesto comercial registra a exclusão com o motivo E a licença, e distingue
`licenses_present` de `independent_support` — a fronteira que o PR-04.2.1
provou nos dois sentidos (ADR-0025).

---

## Baseline

`docs/performance/PR04_CANONICAL_CORPUS_BASELINE.md` — 12.500 registros →
10.000 partidas, do bruto ao `READY`.

---

## Documentos relacionados

- ADR-0026 — versões imutáveis, e por que a aresta `DRAFT → READY` não existe
- ADR-0027 — PostgreSQL é a verdade; o Parquet é representação
- ADR-0025 — elegibilidade canônica ciente de licença
- `docs/contracts/HISTORICAL_CANONICAL_MANIFEST_V1.md`
- `docs/contracts/HISTORICAL_CANONICAL_DATASET_V1.md`
- `docs/data/CANONICAL_BUILD_CORE.md` — o degrau anterior
