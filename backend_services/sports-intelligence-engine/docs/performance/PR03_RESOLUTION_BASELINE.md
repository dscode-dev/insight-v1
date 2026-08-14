# Baseline de resolução e fusão

Medido no PR-03.1 e **remedido no PR-03.2**, em **2026-08-13**. Este documento existe para que a próxima execução
tenha contra o que comparar, e **não** para declarar SLO.

---

## O que estes números afirmam e o que não afirmam

**Afirmam** que o desenho orientado a lote do PR-03 processa cem mil registros
com uso de memória limitado e sem N+1, e dizem quanto isso custa nesta
máquina.

**Não afirmam** nada sobre outra máquina. Throughput depende de CPU, disco e
do que mais estiver rodando; comparar o número daqui com o de um laptop não
significa nada. O que sobrevive à troca de hardware são as **propriedades**:
consultas crescem por lote e não por registro, o pico de memória não acompanha
o tamanho do arquivo, e a DECISÃO não muda quando o tamanho do lote muda.

---

## Ambiente

```
CPU               Intel Core i9-14900KF · 32 threads
RAM               31 GB (27 GB disponíveis)
kernel            6.18.33.2-microsoft-standard-WSL2
disco             SSD, 583 GB livres
Python            3.13 (imagem python:3.13-slim)
PostgreSQL        17.10 (Alpine), em contêiner SEM limite de CPU ou memória
object store      MinIO, mesmo host
```

Configuração do PostgreSQL — **padrão de fábrica**, deliberadamente:

```
shared_buffers          128 MB
effective_cache_size      4 GB
work_mem                  4 MB
max_connections           100
max_wal_size              1 GB
```

Não foi tunado. Um baseline medido contra um banco ajustado à mão mede o
ajuste; este mede o que qualquer pessoa obtém subindo o `docker-compose` do
repositório.

**Contexto de execução**: o motor roda em contêiner, o banco em outro, na
mesma máquina. Rede é loopback — então a latência por consulta é o **piso**.
Num ambiente com banco remoto, o número de consultas passa a pesar muito mais
que aqui, e é justamente por isso que a contagem de consultas é reportada
separada do tempo.

---

## Cenário

Gerado por `tests/support/corpus.py`, determinístico, semente `20260813`.

### Registro canônico (o lado de dentro)

```
5 competições         o catálogo fechado da V1
15 temporadas         3 por competição
300 times             60 por competição, núcleos disjuntos entre ligas
300 aliases           uma abreviação por clube
3.000 jogadores       + 3.000 vínculos com clube
26.550 partidas       turno único de 60 times, 15 temporadas
```

Os jogadores **não são lidos** pelo dataset de partidas — nenhuma coluna
carrega `PLAYER_NAME`. Estão lá porque o registro precisa ter o **tamanho** de
um registro de verdade: um índice de nome com trinta linhas tem seletividade
que nenhum plano de produção terá.

### Linhas de fonte (o lado de fora)

100.000 linhas de CSV, ordenadas por calendário — que é como um arquivo
público de futebol de fato sai, e o que dá **localidade** ao lote.

Distribuição de caminhos, exata por construção (a lista é montada e
embaralhada, não sorteada linha a linha):

| caminho | fatia | como a linha escreve o clube | o que o resolver faz |
|---|---|---|---|
| `ALIAS` | 55% | `Ashford Rov` | alias registrado, casamento exato |
| `CANONICAL` | 25% | `Ashford Rovers` | chave canônica normalizada |
| `SIMILAR` | 12% | `sAhford Rovers` | busca de candidatos, pontua ~0,55 e **não** resolve |
| `UNKNOWN` | 8% | `Clube Externo 024` | nenhum candidato acima do corte |

**Não é 100% caminho barato de propósito.** Um benchmark em que tudo resolve
por chave exata mede um `dict.get` e chama isso de resolução de identidade.

---

## O que o PR-03.2 mudou nos números

As correções funcionais do PR-03.2 — consumo preguiçoso dos lotes, universo de
candidatos por nome, caminho de mapeamento de provedor e etapa de jogador —
foram medidas contra o mesmo cenário:

| | PR-03.1 | PR-03.2 | |
|---|---|---|---|
| pico de memória (100k) | 224 MB | **24 MB** | −89% |
| tempo (100k, frio) | 377,1 s | **284,6 s** | −25% |
| throughput | 265 reg/s | **351 reg/s** | +32% |
| consultas (100k) | 909 | **1.009** | +11% |
| consultas por lote | 9,1 | **10,1** | +1 |
| pico ao multiplicar o dado por 20 | ×5,6 | **×1,1** | — |
| divergências entre lotes 250/1.000/5.000 | 2,7% das alternativas | **0** | — |

**As cem consultas a mais são as duas buscas de candidatos por lote** —
`team_candidates_for_names` e `player_candidates_for_names`. Elas são o preço
do determinismo, e o §63 é explícito: **correção vem antes de economizar uma
consulta**. O preço é 11% de consultas para transformar «2,7% das listas de
alternativas mudam com o tamanho do lote» em zero.

**A memória caiu 89% e o tempo caiu junto**, o que à primeira vista surpreende
— era de esperar que streaming trocasse memória por tempo. Não trocou porque
o custo removido não era só memória: materializar cem lotes antes de começar
alocava, copiava e mantinha vivos os objetos de cem mil registros durante a
execução inteira, e o coletor de lixo pagava por isso do início ao fim.

---

## Resultados

### A medida principal — 100.000 registros, lote 1.000

```
decisões          480.000  (competição, temporada, dois times e partida por linha)
fila de revisão         0

fria              284,6 s   ·  351 reg/s  ·  pico 24 MB
quente            285,0 s   ·  351 reg/s  ·  pico 24 MB

consultas           1.009   em 100 lotes  ·  10,1 por lote  ·  0,0101 por registro
por verbo         fetch 702 · executemany 300 · fetchrow 5 · execute 2

RESOLVED          440.000
UNRESOLVED         40.000
AMBIGUOUS               0
REVIEW_REQUIRED         0
REJECTED                0
```

**Dez consultas por lote, não dez por registro.** Os alvos mostram a forma
exata do desenho: cem execuções contra `competitions`, `seasons`, `teams`,
`matches` (uma por lote cada), duzentas contra `entity_aliases`, duas buscas de
candidatos por nome, e trezentos `executemany` — cem para decisões, cem para evidências, cem
para alternativas. Nada cresce com o número de linhas.

**Frio e quente são iguais** — 284,6 s contra 285,0 s, diferença de 0,1%. O
cache do PostgreSQL e o do sistema operacional não mudam nada aqui, e a razão
aparece nos alvos: o trabalho é dominado por **escrita**, não por leitura. As
707 leituras cabem em memória; os 300 `executemany` gravam 480 mil decisões,
cerca de um milhão de linhas de evidência e as alternativas.

Ou seja: **o gargalo é a persistência, e é onde ele deveria estar** para um
pipeline que precisa deixar rastro de tudo o que decidiu.

**Os 40.000 `UNRESOLVED`** são exatamente as fatias `SIMILAR` (12%) e
`UNKNOWN` (8%) do cenário, multiplicadas pelos dois times de cada linha:
20% × 100.000 × 2 = 40.000. A distribuição declarada aparece intacta na saída.

**Zero na fila de revisão** merece explicação, porque parece bom e não é: a
similaridade sozinha produz confiança em torno de 0,55, e a política de time
exige **duas** evidências corroborantes. Sem país, competição ou participação
histórica que apoie o nome, o resultado é `UNRESOLVED` — não `REVIEW_REQUIRED`.
Está correto e conservador; o efeito prático é que a fila só enche quando há
evidência de apoio, e não a cada nome mal escrito.

### Tamanho de lote — 10.000 registros, 48.000 decisões

| lote | tempo | throughput | pico | consultas | por lote |
|---|---|---|---|---|---|
| 250 | 32,7 s | 306 reg/s | 7,8 MB | 409 em 40 lotes | 10,2 |
| **1.000** | 27,6 s | 363 reg/s | 24,0 MB | 109 em 10 lotes | 10,9 |
| 5.000 | 21,0 s | 477 reg/s | 64,3 MB | 29 em 2 lotes | 14,5 |

**A escolha continua sendo 1.000.** O de 5.000 é 24% mais rápido e custa
**2,7×** mais memória; o de 250 economiza dois terços da memória e custa 19%
de tempo mais 4× de consultas. Mil fica no joelho da curva.

A troca ficou mais nítida no PR-03.2: com os lotes consumidos preguiçosamente,
o pico passou a ser praticamente só o do lote em si — então ele agora
acompanha o tamanho do lote de forma quase linear, em vez de ficar escondido
atrás da materialização do dataset inteiro.

O lote de 250 mostra por que o valor não deve cair: quatro vezes mais lotes
produzem quase quatro vezes mais consultas para o **mesmo** trabalho, e o
tempo piora 19%.

### Consultas: crescem por lote, não por registro

| registros | lotes | consultas | por lote | **por registro** |
|---|---|---|---|---|
| 1.000 | 1 | 19 | 19,0 | 0,0190 |
| 10.000 | 10 | 109 | 10,9 | **0,0109** |

Dez vezes mais registros produziram **5,7×** mais consultas — porque são dez
vezes mais lotes, e o custo fixo do primeiro lote se dilui. Num N+1, as
consultas **por registro** seriam constantes; aqui elas caem quase pela
metade quando o volume cresce, e ficam na casa de **0,01 por registro**.

O caminho ingênuo — uma consulta por linha por dimensão — produziria da ordem
de 700.000 consultas para cem mil linhas. A distância entre os dois números é
grande demais para ser ruído, e é por isso que a asserção do teste não precisa
de um limite ajustado com precisão.

### Memória: limitada pelo lote, não pelo arquivo

```
 2.500 registros    pico  22,1 MB
50.000 registros    pico  24,0 MB

dado x20  ·  pico x1,1
```

**Vinte vezes mais dado custou 10% mais memória.** No PR-03.1 custava cinco
vezes e meia, porque `read_batches` devolvia `list[SourceBatch]` e o chamador
materializava o dataset inteiro antes de resolver — o leitor era preguiçoso e
o consumidor desfazia a preguiça com um `list()`.

Agora ele é um gerador assíncrono consumido lote a lote, e o pico é o do
lote mais o contexto de candidatos. Os 22 MB do caso de 2.500 registros são
quase todos custo fixo: o corpus canônico carregado por lote não encolhe.

### Fusão — 3 fontes x 15.000 registros

```
resolução das 3 fontes   173,5 s   ·  259 reg/s
releitura + filtro         8,5 s   ·  36.000 registros com identidade provada
fusão                     58,2 s   ·  206 grupos/s  ·  2.268 campos/s  ·  pico 72 MB

grupos           12.000   (todos multi-fonte)
campos          132.000
conflitos        24.000   ·  não resolvidos: 0
consultas            81
```

Memória por volume:

```
 2.000 registros/fonte →  1.600 grupos  ·  pico 14,9 MB
10.000 registros/fonte →  8.000 grupos  ·  pico 38,3 MB
```

---

## A única otimização do PR-03.1

O benchmark de fusão mediu **276.009 consultas para 12.000 grupos** — vinte e
três por grupo. `save_candidates` fazia um `INSERT` por candidato, um por campo
e um por conjunto de contribuições. É N+1 clássico, só que na **escrita**,
onde a assinatura em massa dos ports não protegia: o método recebe a coleção
inteira e gastava as idas ao banco por dentro.

A correção troca os laços por `unnest` com arrays paralelos, em blocos de 500
candidatos. O `INSERT` de campos usa `RETURNING id, candidate_id, field_name`
porque o `id` do `bigserial` é o que liga as contribuições.

| | antes | depois |
|---|---|---|
| consultas | 276.009 | **81** |
| tempo da fusão | 107,3 s | **58,2 s** |
| campos/s | 1.230 | **2.268** |
| pico | 72 MB | 72 MB |
| **impressão da saída** | `4c90bb11…de4e` | `4c90bb11…de4e` |

**A impressão é idêntica** — e é ela que prova o que o §14 exige: a otimização
não mudou valor, regra, procedência nem ordem. Se tivesse mudado qualquer
coisa, o SHA-256 da saída canônica seria outro.

---

## Avaliação de capacidade

Não é SLO comercial — é a conta que responde se dá para seguir para o PR-04.

```
265 registros/s  ·  954.000 por hora
```

O corpus histórico alvo da V1 — cinco competições, com o que há de público —
está na ordem de **200 a 400 mil partidas por fonte**. A conta:

| corpus | por fonte | três fontes |
|---|---|---|
| 100 mil linhas | 6 min | 19 min |
| 400 mil linhas | 25 min | 1 h 15 |
| 1 milhão de linhas | 63 min | 3 h 8 |

**Veredito: adequado para processamento histórico offline.** Resolução
histórica não é caminho quente — ela roda uma vez por dataset, fora de
requisição, e nada espera por ela. Uma fonte inteira em vinte e cinco minutos
e um reprocessamento completo de três fontes em pouco mais de uma hora cabem
numa janela operacional sem worker, sem fila e sem paralelismo.

**Não é adequado para caminho síncrono de API**, e nunca foi para ser: seis
minutos por cem mil linhas é três ordens de grandeza acima de qualquer
requisição. A execução síncrona segue sendo dívida declarada do PR-03, e este
número diz quando ela passa a doer — **acima de uns dois milhões de linhas por
execução**, o tempo de parede começa a exigir retomada de onde parou, e aí o
worker deixa de ser conveniência.

**Onde atacar quando doer**, na ordem que a medição indica:

1. **persistência de evidência** — é o que domina. Cada decisão grava de uma a
   três linhas em `resolution_evidence`; um milhão de linhas por dataset de
   cem mil. Gravar evidência só para decisões que precisam de explicação
   (`UNRESOLVED`, `AMBIGUOUS`, `REVIEW_REQUIRED`) cortaria a maior parte — e
   é uma decisão de produto, não de performance: quanto de rastro se quer
   sobre o que resolveu por chave exata.
2. **`COPY` em vez de `executemany`** — vale medir; a diferença costuma ser de
   duas a cinco vezes em carga de escrita pura.
3. **paralelismo por lote** — os lotes são independentes; o que os serializa
   hoje é o `for`, não uma dependência.

Nenhuma das três foi feita, porque nenhuma é necessária **agora** — e esse é o
critério do §3.

---

## Planos das consultas quentes

`EXPLAIN (ANALYZE, BUFFERS)` sobre o corpus real (304 times, 331 aliases,
26.554 partidas, 3.002 jogadores).

### Confronto → partidas — a consulta que domina

```
Nested Loop  (rows=1160)
  ->  Function Scan on t
  ->  Index Scan using matches_confronto_idx  (loops=1160)
        Index Cond: season_id = ... AND home_team_id = ... AND away_team_id = ...
Execution Time: 1,967 ms
```

1.160 confrontos resolvidos em **2 ms**, um índice por triple. É a consulta
mais executada do motor — **11,8 milhões de usos do índice** durante a bateria
— e a que justifica sozinha a existência de `matches_confronto_idx`.

### Nome/alias → times

```
Hash Right Join  →  Seq Scan on entity_aliases  +  Seq Scan on teams
Execution Time: 0,183 ms
```

**Sequential scan, e está certo.** Com 304 times e 331 aliases, a tabela
inteira cabe em cinco páginas; um índice custaria mais que ler tudo, e o
planejador sabe disso. Os índices `teams_normalizado_idx` e `aliases_busca_idx`
existem para quando o registro tiver dezenas de milhares de clubes — que é o
tamanho que ele terá depois do PR-04.

### Índices que não foram usados, e por quê (§35)

_Medido no PR-03.1; as duas últimas linhas deixaram de valer no PR-03.2._

| índice | usos | por quê |
|---|---|---|
| `teams_normalizado_idx`, `teams_pais_idx` | 0 | 304 linhas: `seq scan` é mais barato. **Legítimo.** |
| `seasons_busca_idx` | 0 | 17 linhas. **Legítimo.** |
| ~~`players_normalizado_idx`, `players_dob_idx`~~ | 0 | resolução de jogador não tinha chamador — **fechado no PR-03.2** |
| ~~todos de `provider_entity_mappings`~~ | 0 | mapeamento não era consultado — **fechado no PR-03.2** |
| `fused_fields_candidato_idx`, `fused_sources_campo_idx` | 0 | servem à LEITURA do operador, que o benchmark não exercita |
| `fused_fields_conflitos_idx` | 0 | idem — a política do cenário resolve os conflitos, então não há linha `CONFLICT_UNRESOLVED` |

Os dois primeiros grupos são planejamento correto. O terceiro e o quarto são
**evidência dos achados 6 e 7**: um índice com zero usos sobre uma consulta que
deveria acontecer é o sintoma de que ela não acontece.

---

## O que o PR-03.2 fechou

Os cinco pontos que o benchmark do PR-03.1 expôs. Cada um vinha com uma
evidência medida, e é a mesma medição que prova o fechamento.

### 1. Odds de duas casas em duas linhas

**Era**: `group_by_identity` tratava duas linhas da mesma fonte para a mesma
partida como duplicata interna. Uma fonte que publica uma linha por casa de
apostas perdia todas menos a primeira. Nada era promediado, e a dispersão
entre casas — que é o sinal — sumia.

**É**: a identidade da observação inclui a **casa** e o **payload**. Linha
extra com identidade nova entra como observação; com identidade repetida é
duplicata verdadeira, descartada e **contada**.

```
BET365   @ 2.00     observação
PINNACLE @ 2.05     observação      →  2 observações, 2 record_refs
BET365   @ 2.00     duplicata       →  1 descarte, reportado
```

### 2. `PlayerResolver` sem chamador

**Era**: `players_normalizado_idx` e `players_dob_idx` com **zero usos** em
toda a bateria. A cadeia ia de competição a partida e nunca passava por
jogador.

**É**: ramo próprio, condicional ao mapeamento — se a fonte declara
`PLAYER_NAME`, há identidade de jogador. Independente da cadeia da partida,
porque um registro cuja competição não resolveu ainda pode ter jogador
legítimo.

```
nome + nascimento + clube na data  →  RESOLVED, confiança 1,000
nome só, dois homônimos            →  REVIEW_REQUIRED, 0,550
id do provedor                     →  RESOLVED, EXACT_PROVIDER_MAPPING
```

### 3. `ProviderEntityMapping` sem chamador

**Era**: os quatro índices da tabela com **zero usos**. `TeamResolver`
consultava o mapeamento quando recebia `provider_ref`, e a execução em lote
nunca o passava — ela resolvia por nome distinto.

**É**: caminho **prioritário**, resolvido sobre as referências distintas do
lote. Vale para time e para jogador, pelo mesmo código — o teste do §26
existe para que um `if subject is TEAM` escondido não passe.

O teste usa nomes propositalmente impronunciáveis (`xxq zzt clube 998877`):
se o id canônico sai certo com um nome desses, ele só pode ter vindo do
mapeamento.

### 4. Universo de candidatos dependente do lote

**Era**: 2,7% das listas de alternativas mudavam entre lote 250 e 5.000.

**É**: **zero** divergências em 250, 1.000 e 5.000 — incluindo a ordem das
alternativas. Os candidatos vêm de uma busca por nome, com `LIMIT` **por
nome** e ordem determinística.

Uma sutileza que só a execução revelou: ordenar o `LIMIT` por `id` deixava
três mil `Silva NNNNN` empurrarem os homônimos exatos de `Rodrigo Silva` para
fora do corte. A ordem passou a ser **nome exato primeiro**, depois tokens em
comum, e o id só como desempate.

### 5. Materialização global dos lotes

**Era**: `read_batches` devolvia `list[SourceBatch]`; o leitor era preguiçoso
e o chamador desfazia a preguiça.

**É**: gerador assíncrono consumido lote a lote. Pico de 224 MB para **24 MB**,
e o crescimento com o volume passou de ×5,6 para ×1,1.

---

## Achados do PR-03.1

### 1. `record_ref` era gravado como `NULL` em toda decisão

`_decisao_para_tupla` escrevia `None` na coluna `record_ref`. Como
`resolved_entities_of_run` filtra por `record_ref IS NOT NULL`, ela devolvia
**dicionário vazio, sempre** — e `to_resolved_records` não deixava passar
nenhum registro. **A fusão recebia zero registros em qualquer execução real.**

Os testes de unidade não pegaram porque constroem `ResolvedSourceRecord`
diretamente; o defeito mora exatamente na costura entre resolução e fusão, que
só o PostgreSQL exercita.

Corrigido: `ResolutionDecision` ganhou o campo `record_ref`, o caso de uso o
preenche com `str(registro.ref)`, e o adapter o escreve e o relê. A decisão
manual também o preenche, a partir do item de fila que a originou.

### 2. Id canônico relido do banco perdia o tipo concreto

O adapter reconstruía `EntityId(linha[...])` — a superclasse. O caso de uso
faz `assert isinstance(competicao, CompetitionId)`. Passava no `mypy`
(`EntityId` é supertipo) e **explodia em produção** na primeira competição
resolvida por alias vindo do banco.

Corrigido com `_id_canonico(subject, valor)`, que lê a coluna `entity_type` —
que já estava lá, gravada pelo mesmo `INSERT` — e devolve `CompetitionId`,
`SeasonId`, `TeamId`, `PlayerId` ou `MatchId`.

### 3. Time resolvido por alias impedia a partida de resolver

`_confrontos` montava os pares (temporada, mandante, visitante) buscando os
times **só por nome canônico normalizado**. Um clube escrito como `Man City`
resolvia — o resolver consulta alias antes de nome — mas o confronto nunca era
carregado, e a partida ficava `UNRESOLVED` por ausência de candidato.

O sintoma era o pior tipo possível: uma fonte que usa abreviações — a fonte
comum — resolvia **todos** os times e **nenhuma** partida. Nada falhava.

Medido antes e depois, no mesmo cenário de 5.000 registros:

```
antes    1.250 partidas RESOLVED de 4.000 elegíveis    31%
depois   4.000 partidas RESOLVED de 4.000 elegíveis   100%
```

Corrigido em `_times_possiveis`, que cai para os aliases quando o nome
canônico não casa. Carregar confrontos a mais não muda decisão nenhuma:
`MatchResolver` consulta os confrontos da temporada e dos times **já
resolvidos** daquele registro, então um confronto carregado que ninguém
consulta é custo, não candidato.

### 4. O tamanho do lote muda as ALTERNATIVAS, não a decisão — CORRIGIDO no PR-03.2

Medido em 9.600 decisões, lote 250 contra lote 5.000:

```
status · método · confiança · entidade escolhida    IDÊNTICOS  (9.600 de 9.600)
lista de alternativas                               259 divergem  (2,7%)
alternativas divergentes em decisão RESOLVED        0
```

Não é defeito de implementação; é consequência direta do desenho, e vale
dizê-la em voz alta: o candidato de similaridade sai de `context.teams`, que
tem os times carregados **para aquele lote**. Um lote de cinco mil linhas
carrega mais clubes e, portanto, enxerga candidatos parecidos que um lote de
duzentos e cinquenta nem chegou a ler.

A **decisão** não muda — o limiar de time é 0,92 e nenhum desses candidatos
chega perto — mas a **lista que o operador vê na fila de revisão** muda. O
teste `test_lote_250_e_lote_5000_decidem_igual` cobra a invariância onde ela
existe e **mede** a variação onde ela existe; afirmar as duas como iguais seria
afirmar algo falso.

A consequência prática está na dívida: a busca de candidatos por similaridade
é limitada ao que o lote carregou por chave exata. Um nome mal escrito cujo
clube canônico não aparece em nenhuma outra linha do lote não gera candidato
nenhum — vira `UNRESOLVED` em vez de `REVIEW_REQUIRED`.

### 5. Odds de duas casas em duas linhas: uma é descartada — CORRIGIDO no PR-03.2

Encontrado, **não corrigido**. `group_by_identity` trata duas linhas do mesmo
provedor para a mesma partida como duplicata interna e descarta uma. A regra
existe por bom motivo — contar a mesma fonte duas vezes inflaria a
concordância —, e aqui ela apaga uma observação legítima.

A propriedade do §20 continua valendo: **nada é promediado**, e o valor que
sai é um valor que uma casa de fato ofereceu. O que se perde é a segunda casa.

Corrigir exige distinguir «linha repetida» de «observação a mais do mesmo
provedor», o que é decisão de desenho da fusão e não cabe num PR de
fechamento. O descarte é **contado e reportado** (`FusionOutput.discarded`), e
o teste de integração cobra essa visibilidade.

### 6. `PlayerResolver` não tem chamador operacional — CORRIGIDO no PR-03.2

A cadeia de `RunIdentityResolution` é competição → temporada → time → partida.
Jogador não entra. Mesmo assim `_carregar_contexto` executa duas consultas por
lote para carregar jogadores e vínculos que ninguém consulta.

Não corrigido: ligar jogador à cadeia é decisão de desenho — uma linha de
partida tem vinte e dois jogadores, não um — e seria funcionalidade nova.

### 7. Mapeamento de provedor também não tem chamador operacional — CORRIGIDO no PR-03.2

`TeamResolver` consulta `ProviderEntityMapping` quando recebe `provider_ref`,
e `_resolver_distintos` nunca o passa: ele resolve por **nome distinto**, que
é o que torna o lote barato. `_carregar_contexto` carrega os mapeamentos assim
mesmo.

Consequência para este baseline: a fatia «mapeamento de provedor existente» da
distribuição pedida (§5) foi substituída por **alias**, que é o caminho
equivalente que a execução de fato percorre — memória de uma decisão anterior,
casamento exato, custo de `dict.get`. Está declarado aqui e no relatório.

O ciclo de revisão manual **não** depende disso: `ResolveReviewItem` grava um
`EntityAlias`, e alias é consultado.

---

## Como reproduzir

```bash
docker compose -f infra/docker-compose.yml up -d

SIE_TEST_POSTGRES_DSN=postgresql://engine:engine_local@postgres:5432/sports_intelligence \
SIE_TEST_OBJECT_STORE_ENDPOINT=http://minio:9000 \
SIE_TEST_OBJECT_STORE_BUCKET=sports-intelligence-raw \
pytest tests/performance -m performance -s
```

O `-s` é necessário: os blocos de relatório vão para `stdout`. Eles **não**
são gravados num arquivo versionado de propósito — um artefato gerado pelo
teste entraria no `git` a cada execução com números diferentes, e o diff
passaria a ser ruído permanente.

---

## Leitura relacionada

- [`../data/IDENTITY_RESOLUTION.md`](../data/IDENTITY_RESOLUTION.md)
- [`../data/DATA_FUSION.md`](../data/DATA_FUSION.md)
- **ADR-0019** — decisões versionadas e execuções imutáveis
- **ADR-0022** — resolução antes de fusão
