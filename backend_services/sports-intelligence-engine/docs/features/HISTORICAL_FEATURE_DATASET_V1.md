# `HistoricalFeatureDatasetVersion` — o dataset histórico de features

**Status:** vigente desde o PR-05.5.1 · ver ADR-0036 e ADR-0037

O PR-05.4 fechou o **cálculo**: dada uma partida e um corte, o motor produz um
`FeatureSnapshot` de 105 dimensões. O que não existia é o **conjunto** — «as
features de *n* partidas em 91 cortes cada, sob estas políticas, congeladas sob
este nome».

Sem ele não há população para ajustar escala, não há base de vizinhos, e não há
como duas execuções provarem que produziram a mesma coisa.

---

## 1. A cadeia

```
HistoricalCanonicalDatasetVersion   corpus publicado, imutável, impresso
        ↓  SnapshotGridPolicy + FeatureDatasetSplitPolicy
n partidas em 91 cortes
        ↓  MATCH_STATE_RAW_V2                (PR-05.4, sem mudança nenhuma)
FeatureSnapshot por corte
        ↓  MaterializedFeatureRow            coordenadas + digesto
Parquet particionado + manifest.json
        ↓  validação                         releitura, reconciliação, rebuild
HistoricalFeatureDatasetVersion  READY
```

---

## 2. Identidade e ciclo de vida

Duas coisas, e separá-las é a decisão — o mesmo desenho do corpus (ADR-0026):

| | o que carrega |
| --- | --- |
| `HistoricalFeatureDataset` | a identidade **lógica**. Sem conteúdo, sem escopo, sem contagem |
| `HistoricalFeatureDatasetVersion` | o conteúdo congelado: origem, políticas, contagens, impressão |

```
DRAFT → BUILDING → VALIDATING → READY → SUPERSEDED
  ↓        ↓            ↓
FAILED   FAILED       FAILED
```

**`DRAFT → READY` não existe**, e a ausência é o ponto: um dataset publicado sem
passar por construção e validação seria um nome apontando para nada.

O grafo é o **mesmo do corpus**, reusado e não recriado: as perguntas são as
mesmas — «está sendo escrito?», «já foi conferido?», «pode ser lido?» —, e um
segundo grafo com os mesmos nomes divergiria do primeiro na primeira correção
feita num só dos dois.

`READY` exige três provas, conferidas no tipo **e** no banco: impressão de
conteúdo, manifesto, e `row_count > 0`. A terceira é própria daqui — um dataset
vazio publicado devolveria «sem vizinhos» em vez de um erro para quem o
consultasse.

---

## 3. A origem

A versão aponta para a **versão do corpus**, e não para o dataset canônico. «As
features da 1.0» é uma afirmação verificável; «as features do corpus» mudaria de
significado toda vez que o corpus publicasse.

Ela guarda o id **e a impressão**. O id diz «da 1.0»; a impressão diz «da 1.0
cujo conteúdo era este». A construção confere as duas contra a `CorpusSource`
recebida e recusa quando divergem.

---

## 4. As políticas, por extenso

`FeatureDatasetSpec` carrega as políticas **inteiras** — não só as impressões
delas:

```
space   MATCH_STATE_RAW_V2 @ 2.0                  (nome, versão, impressão)
grid    SnapshotGridPolicy                        o OBJETO, com os parâmetros
split   FeatureDatasetSplitPolicy                 idem, com a fronteira
```

**Por que os parâmetros, e não só nome + versão + impressão.** A forma óbvia
guarda a tripla e reconstrói pelo nome quando precisa. Ela não funciona:
`SnapshotGridPolicy(name=…, version=…)` traz os limites **padrão**, então uma
grade de cinco cortes voltaria com noventa e um. A impressão acusaria a
divergência — e acusar não é reconstruir. Uma política com parâmetros só é
reconstrutível a partir dos parâmetros.

No PostgreSQL isso vive nos dois lugares, com papéis diferentes:

```
colunas      grid_name, grid_version, grid_fingerprint, …    para CONSULTAR
jsonb spec   a forma canônica completa                       para RECONSTRUIR
```

O adaptador reconstrói do `jsonb` e **confere as colunas contra ele**: um índice
que apontasse para uma impressão diferente da do documento tornaria a consulta
«quais versões são comparáveis com esta?» silenciosamente errada.

`from_canonical` confere a impressão gravada contra a recalculada. Um documento
com parâmetros adulterados é recusado em vez de produzir uma política que
ninguém declarou.

`spec.is_comparable_with(outra)` responde «estas duas versões podem ser
comparadas linha a linha?» sem reconstruir política nenhuma seis meses depois.

---

## 5. A linha materializada

```
MaterializedFeatureRow = FeatureSnapshot + coordenadas de arquivo
```

| coordenada | o que é |
| --- | --- |
| `key` | `(match_id, grid_index)` — a identidade da linha na versão |
| `split` | a metade da partida |
| `competition_code`, `season_label` | a partição do arquivo |
| `kickoff` | o pontapé canônico |
| `grid_label` | `PRE_MATCH`, `1H_007`, `2H_063` |
| `state_issue_count` | quantos problemas a reconstrução do estado reportou |

`state_issue_count` é da **partida** e se repete nas 91 linhas — de propósito:
quem lê uma linha isolada precisa saber que ela veio de um estado degradado sem
ter de ir buscar a partida inteira.

---

## 6. Os dois digestos

| | responde |
| --- | --- |
| `snapshot_fingerprint` | «duas execuções calcularam a mesma coisa?» (PR-05.1) |
| `materialized_row_digest` | «o que está no arquivo é o que se pretendia gravar?» |

O segundo é **reconstrutível lendo o Parquet e mais nada** — e é essa propriedade
que o torna útil na validação. Se ele dependesse do `FeatureSnapshot`, conferir
um arquivo exigiria reconstruir o estado da partida, e a conferência deixaria de
ser uma leitura para virar um build.

Algoritmo: `SHA256_CANONICAL_JSON_V1`, e o nome vai **dentro** da forma
canônica — dois hex de 64 caracteres de métodos diferentes são indistinguíveis.

Entram no digesto: `as_of`, disponibilidades, competição, temporada, espaço,
índice e rótulo da grade, pontapé, `match_id`, `snapshot_fingerprint`, metade,
contagem de problemas, política temporal, motivos de recusa e valores. **Não
entram**: instante de gravação, id de execução, nome do arquivo.

---

## 7. A impressão do conteúdo

`SHA256_ORDERED_ROW_CHAIN_V1`. Ela encadeia os digestos das linhas **na ordem
canônica** e **recusa** uma chave fora de ordem.

```
cabeçalho   espaço, versão do espaço, impressão da grade, impressão da divisão
linhas      frame("sie.feature.row", "<chave>:<digesto>")  em ordem crescente
rodapé      frame("sie.feature.count", "<n>")
```

**Por que ordenada e não comutativa.** A alternativa comum — somar ou fazer XOR
dos digestos — torna a impressão insensível a permutação, e permutação é
exatamente um dos defeitos que ela existe para pegar (duas linhas trocadas entre
partições).

**Por que o cabeçalho entra.** Sem ele, dois datasets com as mesmas linhas sob
grades diferentes teriam a mesma impressão — e a grade é parte do que o dataset
**é**.

**Por que a contagem entra.** Truncar o dataset tem de aparecer.

A ordem da varredura é `ORDER BY match_id` no PostgreSQL, que ordena os dezesseis
bytes do UUID; o `str()` dele é o mesmo hexadecimal com hífens em posições fixas,
então as duas ordens coincidem. É por isso que a validação consegue reconstruir a
cadeia **sem consultar o banco**.

### De onde vem a ordem, dos dois lados

| lado | como a ordem é obtida | memória |
| --- | --- | --- |
| construção | `ORDER BY match_id` com paginação por chave | **nada é ordenado em memória** |
| validação | os pares `(chave, digesto)` de todos os objetos são reunidos e ordenados | `O(linhas)` em tuplas pequenas |

**Na construção não há ordenação nenhuma.** O banco entrega as partidas em
ordem, a grade entrega os cortes em ordem, e o acumulador **recusa** uma chave
fora de ordem — então o custo é zero e o desvio é um erro, não uma reordenação
silenciosa.

**Na validação há.** Os arquivos são por partição e se intercalam por partida,
então a ordem global só existe depois de reunir os pares. Cada par é
`(texto de 36, inteiro, texto de 64)` — sem os valores de feature, que ficam nos
arquivos. É bounded e é `O(linhas)`; a medição está no baseline, e o limite de
escala que ela implica está declarado lá.

---

## 8. O Parquet

| | |
| --- | --- |
| compressão | ZSTD |
| partição | `features/<dataset>/<versão>/split=…/competition=…/season=…/part-NNNNN.parquet` |
| colunas | 23 de identidade e linhagem + 105 valores + 105 disponibilidades = **233** |
| schema | derivado do catálogo, **nunca inferido** |

Duas colunas por feature:

```
f_<chave>   o VALOR, tipado pelo `FeatureOutputType`, NULÁVEL
a_<chave>   a DISPONIBILIDADE, texto, NUNCA nula
```

**`NULL` sozinho não basta.** Ele diz «não há número» e não diz por quê — e «a
fonte não publica escanteio» exige ação diferente de «o corte proibiu o fato».
Um dataset com só a primeira coluna obrigaria quem investiga a adivinhar entre
sete causas.

**E `NULL` nunca vira zero** (ADR-0009). `corners_home_5m = 0` é um fato:
não houve escanteio. `= NULL` é outro: não se sabe.

Os **motivos de recusa temporal** vão num `map<string,string>` de uma coluna só:
o motivo é definido apenas para `TEMPORALLY_UNAVAILABLE` — o domínio recusa a
combinação contrária —, então 105 colunas dele seriam 105 colunas quase sempre
nulas para carregar um punhado de valores.

`INTEGER` vira `int64` e não `int32`: o ganho de espaço é apagado pela
compressão, e o dia em que uma contagem acumulada não coubesse seria um estouro
silencioso num arquivo já gravado. `CATEGORY` é **recusado na construção do
materializador** — `FeatureValue` guarda `float`, então uma coluna de texto
prometeria uma categoria e gravaria um número.

As linhas dentro do arquivo estão **em ordem de chave**, e o adaptador não
reordena: a impressão é ordenada, e uma reordenação silenciosa faria o arquivo
discordar da impressão sem que nada denunciasse até a validação.

### Os dois tetos de memória

O escritor mantém **um buffer por partição aberta**, e são dois tetos:

```
part_rows          5.000   fecha UM `part-*.parquet` quando ele enche
max_pending_rows  10.000   teto GLOBAL, somando todas as partições abertas
```

**O segundo é o que de fato limita**, e a diferença custou uma medição para
aparecer. Uma linha em espera carrega o `FeatureSnapshot` inteiro — cento e
cinco `ComputedFeature`, cerca de **27 KB medidos**. Com teto só por partição,
uma varredura que atravessa vinte competições mantém vinte buffers de cinco mil
linhas vivos ao mesmo tempo: o pico deixa de ser 130 MB e vira 2,6 GB, e passa a
seguir **quantas partições o corpus tem** em vez do lote.

Quando o teto global é atingido, a **maior** partição é descarregada — não a
mais antiga. A maior é a que libera mais memória por arquivo escrito; escrever o
menor arquivo possível produziria uma enxurrada de `part-*.parquet` minúsculos.

Uma partida **nunca é partida ao meio**: a descarga acontece entre partidas, e
os noventa e um cortes de uma delas ficam sempre no mesmo arquivo.

---

## 9. O manifesto

Responde, e nada mais responde sem arqueologia:

```
o que está aqui dentro     linhas e partidas, por metade e por partição
de onde veio               a VERSÃO do corpus, com a impressão dela
sob quais regras           espaço, grade e divisão — versões E impressões
o que ficou de fora        o catálogo de exclusões da grade, com motivo
quanto está disponível     contagens por estado de disponibilidade
é o mesmo dataset?         uma impressão de 64 caracteres
```

Duas impressões, e confundi-las é caro:

- `manifest_sha256` — o hash dos **bytes** do `manifest.json`; muda quando o
  instante de criação muda;
- `raw_content_fingerprint` — o hash do **conteúdo**; não muda.

O manifesto volta do banco reconstruído **do documento gravado**, e não das
colunas: reconstruir das colunas produziria um manifesto parecido, e o
`manifest_sha256` deixaria de fechar sobre ele.

---

## 10. As quatro fases

| caso de uso | transição | o que faz |
| --- | --- | --- |
| `CreateHistoricalFeatureDatasetVersion` | → `DRAFT` | congela as políticas; confere que o corpus está publicado e que ele declara as famílias exigidas |
| `BuildHistoricalFeatureDatasetVersion` | `DRAFT → BUILDING → VALIDATING` | varre, calcula, escreve, registra objetos, salva manifesto |
| `ValidateHistoricalFeatureDatasetVersion` | `VALIDATING` (ou → `FAILED`) | relê e confere |
| `PublishHistoricalFeatureDatasetVersion` | `VALIDATING → READY` | grava o manifesto no store e supera a versão anterior |

**Quatro passos e não um.** «Construir e publicar» num método só faria a
publicação acontecer sempre que a construção terminasse — e publicar é decidir
que **esta** população passa a ser a base de comparação, que é julgamento e não
consequência mecânica de um `for` ter acabado. A trilha exige motivo.

---

## 11. A validação

Sete conferências, e cada uma pega um defeito diferente:

| conferência | o defeito |
| --- | --- |
| hash de cada objeto | o arquivo não chegou inteiro ao bucket |
| reconciliação manifesto ↔ registro | objeto órfão, objeto faltando |
| contagem de linhas | alguma coisa se perdeu no caminho |
| chave repetida | uma partida foi materializada duas vezes |
| ordem dentro do arquivo | a leitura em fluxo não pode confiar na ordem |
| impressão reconstruída | o conteúdo não é o que a construção calculou |
| **rebuild semântico** | o cálculo não é reproduzível a partir do corpus |

A última é a cara e a mais importante. As outras provam que os **bytes**
sobreviveram; ela prova que o **número** sai igual de novo — que é a propriedade
da qual toda a reprodutibilidade depende.

A amostra do rebuild são as **primeiras N partidas na ordem da chave**, e não
uma amostra sorteada: uma validação que sorteasse produziria vereditos
diferentes sobre o mesmo dataset. No E2E o `rebuild_sample` cobre o conjunto
inteiro.

Reprovar **derruba a versão para `FAILED`**, com os problemas nomeados no
`failure_reason`.

---

## 12. O que o banco guarda, e o que ele não guarda

O PostgreSQL guarda identidade, políticas, contagens, rastro de execução e
**ponteiros**. As linhas de feature moram no Parquet e só nele (ADR-0037).

Nenhuma consulta do adaptador devolve um valor de feature, e a ausência é o
desenho: replicá-los criaria duas verdades sobre o mesmo número.

Tabelas (migration `0012_historical_feature_dataset.sql`):

```
historical_feature_datasets              identidade lógica
historical_feature_dataset_versions      conteúdo congelado + políticas
historical_feature_dataset_manifests     o documento publicado
historical_feature_dataset_build_runs    rastro e custo de execução
historical_feature_objects               os Parquet, com partição em colunas
```

---

## 13. O que este dataset NÃO tem

**Nada normalizado.** Não há artefato de escala, não há coluna normalizada, e o
caso de uso não importa o pacote de ajuste. Ajustar escala exige uma população —
e a população é justamente o que aqui se produz. Sobre qual metade ajustar, com
qual grade de cortes, é decisão do PR seguinte.

**Nada vetorizado.** Sem similaridade, sem embedding, sem pgvector.

**Nada ao vivo.** O dataset é histórico por construção: a origem é uma versão
publicada do corpus, e não existe caminho para ler fato em tempo real.

---

## Referências

- ADR-0036 — a grade é comparável ao vivo e a divisão é temporal e atômica
- ADR-0037 — o dataset de features mora no object store, e não no PostgreSQL
- ADR-0026 — versões do dataset histórico são imutáveis
- ADR-0027 — o Parquet do corpus é representação, e não fonte
- `docs/features/SNAPSHOT_GRID_V1.md`
- `docs/features/FEATURE_DATASET_SPLIT_V1.md`
- `docs/features/RAW_FEATURE_CATALOG_V2.md`
- `docs/performance/PR05_FEATURE_DATASET_BASELINE.md`
