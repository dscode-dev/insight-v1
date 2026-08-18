# ADR-0026 — Versões imutáveis do corpus histórico

**Status:** aceito · **Data:** 2026-08-18

## Contexto

O PR-04.2 deixou o motor com fatos canônicos no PostgreSQL e linhagem completa
por fato. O que faltava é a pergunta que o PR-05 vai fazer todos os dias:
**«sobre qual conjunto exato de fatos este resultado foi calculado?»**

Três desenhos ingênuos, e o que cada um custa:

**«O corpus é o que está no registro canônico.»** O registro é global e cresce
depois. Um vetor calculado hoje descreveria um corpus que não existe mais
amanhã, e nenhum resultado seria reproduzível — que é a propriedade que o
`FeatureSpaceVersion` do ADR-0008 existe para preservar e que sozinho não
consegue garantir.

**«O corpus é o que estava no registro até a data X.»** Melhor, e ainda quebra:
bastaria alguém corrigir um placar de 2019 para a versão publicada mudar de
conteúdo sem mudar de nome. Correção de fato é legítima e frequente; o que não
pode acontecer é ela reescrever o passado de um resultado já calculado.

**«O corpus é a saída de um build.»** Um `CanonicalBuildRun` constrói fatos; ele
não declara quais fatos formam o corpus. Uma temporada costuma vir de vários
builds, e um build de pesquisa produz fatos que o corpus comercial não pode
conter (ADR-0025).

## Decisão

**Duas entidades, e juntá-las apaga a mais útil:**

```
HistoricalCanonicalDataset          «o corpus histórico principal»
                                    um NOME estável, que dura anos

HistoricalCanonicalDatasetVersion   «o que exatamente estava nele em 1.0»
                                    um CONTEÚDO imutável, que nunca muda
```

O nome continua sendo um ponteiro; a versão continua sendo um fato.

**A pertinência é GRAVADA, partida a partida, e nunca derivada.**
`historical_canonical_members` liga versão a partida com as famílias que
entraram naquela versão, a execução de build que as produziu e a avaliação que
as autorizou. Derivar por consulta traria o registro global; derivar por data
traria o passado reescrito.

**O FATO NÃO É DUPLICADO.** O `Match` canônico continua sendo um só; o que
existe por versão é uma LINHA DE PERTINÊNCIA que aponta para ele. Duplicá-lo
faria a mesma partida existir cinco vezes com cinco ids — exatamente o que a
resolução de identidade passou três PRs impedindo.

**O ciclo de vida é um grafo explícito, e a aresta que MAIS importa é a que não
existe:**

```
DRAFT ──▶ BUILDING ──▶ VALIDATING ──▶ READY ──▶ SUPERSEDED
  │           │             │
  └───────────┴─────────────┴──▶ FAILED

DRAFT ──▶ READY      NÃO EXISTE
```

Uma versão que nunca materializou nem conferiu não pode se declarar publicada.
O gate não é um `if` em quem publica — é a ausência de uma aresta, e por isso
não há caminho de código que o contorne.

**`published = true` não bastaria.** Ele não distingue «está sendo conferida»
de «falhou na materialização» de «foi substituída», e as três exigem ações
diferentes de quem opera.

**Depois de `READY`, nada muda.** Nem ganha partida, nem perde, nem troca
política, nem recalcula impressão. Qualquer mudança produz uma versão NOVA, e a
anterior fica marcada como `SUPERSEDED` — **e continua legível**. Impedir a
leitura de uma versão superada tornaria irreproduzível todo resultado já
calculado sobre ela, que é o oposto do motivo de as versões existirem.

**A impressão do corpus é SEMÂNTICA, e não do documento.** Duas impressões
diferentes coexistem e confundi-las é caro:

```
corpus_fingerprint   o hash do CONTEÚDO. Não muda entre duas publicações
                     independentes dos mesmos fatos — nenhum carimbo de tempo
                     e nenhum id de execução entram nela
manifest_sha256      o hash dos BYTES de `manifest.json`. Muda, e responde
                     outra pergunta
```

Ela é acumulada por **XOR sobre os digests dos membros**, que é comutativo: a
partição em lotes não vaza para o resultado, e publicar com lote de 250 ou de
5.000 produz a mesma impressão. É a mesma decisão do `SetFingerprint` do
PR-04.2, e o motivo é o mesmo — dez mil partidas não cabem numa ordenação em
memória.

**A concorrência é resolvida pelo banco.** Toda transição é
`UPDATE ... WHERE status = $esperado`; a segunda publicação simultânea vê zero
linhas afetadas e decide, em vez de sobrescrever. Um lock distribuído seria uma
dependência a mais para resolver o que uma cláusula `WHERE` já resolve — e o
Redis não existe nesta fase por decisão do ADR-0004.

**Publicar é uma DECISÃO administrativa.** `CORPUS_VERSION_PUBLISHED` é
`is_decision`, e o domínio exige motivo. «Quem publicou a 1.0, quando, com qual
escopo e por quê» tem de ter resposta sem arqueologia.

## Consequências

**Ganhamos:** «este resultado foi calculado sobre qual conjunto de fatos» tem
resposta em uma consulta, e a resposta continua verdadeira anos depois. Duas
publicações independentes dos mesmos fatos são reconhecíveis como o mesmo
corpus pela impressão — que é o que torna reprodutibilidade uma afirmação
verificável em vez de uma promessa.

**Pagamos:** uma linha de pertinência por partida por versão. Dez mil partidas
em três versões são trinta mil linhas de ponteiro. É o preço de não duplicar o
fato, e ele é pequeno perto da alternativa.

**Aceitamos:** o escopo é DECLARADO e não descoberto. Uma partida que o build
produziu e o escopo não menciona reprova a composição inteira, em vez de entrar
como bônus. Ou o escopo está errado, ou os builds são os errados — e as duas
exigem que alguém decida, e não que a publicação escolha.

---

## Emenda — PR-04.3.1: a impressão e a composição

Duas decisões desta ADR foram revisadas na revisão do PR-04.3. Nenhuma das duas
muda o que a ADR decide; as duas mudam COMO ela é cumprida.

### A impressão deixou de ser XOR-fold

O texto acima descrevia os membros combinados por **XOR sobre os digests**,
justificado pela comutatividade: a partição em lotes não vazava para o
resultado. A propriedade era desejável e o mecanismo é inadequado:

```
H(A) ⊕ H(A)         = 0
H(A) ⊕ H(A) ⊕ H(B)  = H(B)
```

Um item repetido se CANCELA. A duplicata era impedida por fora — chave primária
`(version_id, match_id)` e guarda no acumulador —, mas a impressão do corpus é
a autoridade de entrada de toda a matemática do PR-05 em diante, e ela não pode
depender de guardas externas para não ter uma colisão trivial. Cada porta nova
para o corpus precisaria lembrar da mesma guarda.

**Ela passou a ser SHA-256 sequencial sobre ordem canônica explícita**, com
framing por tamanho e separador de domínio. A comutatividade foi trocada por
algo mais forte: a ordem é IMPOSTA na leitura (`ORDER BY match_id`) e
VERIFICADA na acumulação, então desordem e duplicata viram ERRO em vez de
virarem silêncio. O cálculo continua em uma passagem com memória O(lote).

`fingerprint_algorithm` (`canonical-sha256-v1`) e `fingerprint_schema_version`
passam a viajar no manifesto e na tabela: as duas construções produzem hex de
64 caracteres e são incomparáveis.

**As impressões de política saíram da impressão do corpus.** Uma política só é
relevante para o conteúdo quando MUDA o conteúdo — e quando muda, os membros já
mudaram. Incluí-la acrescentava apenas falsos negativos: duas publicações dos
mesmos fatos sob políticas de versões diferentes diriam «corpus diferente»
sobre conteúdo igual. Ela continua no manifesto, que é conteúdo + procedência.

### `DISTINCT ON` deixou de decidir semântica

A pertinência multi-build era resolvida com `DISTINCT ON (match_id) … ORDER BY
created_at DESC`. Isso deduplica e, ao deduplicar, responde uma pergunta que
ninguém fez: **qual build vence?** Um build vencia por ser mais recente, e com
ele venciam as famílias que ele incluiu e a linhagem que ele registrou.

**Nenhuma linha vence arbitrariamente.** A leitura devolve uma linha por
(partida, build) e a junção é decisão de domínio:

```
fatos EQUIVALENTES        um membro, TODAS as linhagens
famílias COMPLEMENTARES   a UNIÃO, com os fatos MESCLADOS
fatos CONFLITANTES        publicação bloqueada; alguém decide
escopos incompatíveis     recusados antes de qualquer escrita
```

A migration 0008 move a linhagem de duas colunas do membro para
`historical_canonical_member_builds` — uma linha por contribuição, com a
avaliação e a parcela de famílias de cada build.
