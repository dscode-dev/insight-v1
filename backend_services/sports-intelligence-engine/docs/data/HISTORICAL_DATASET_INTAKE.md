# Intake de datasets históricos — V1

O que acontece entre um arquivo na mão do operador e um dataset marcado
`STAGED`, e por que cada etapa existe.

> **A afirmação que este estágio faz:** antes de interpretar qualquer dado
> externo, o motor é capaz de provar exatamente o que recebeu, de onde veio,
> sob qual licença, em qual versão e quais bytes constituíam aquela entrada.
>
> **A afirmação que ele NÃO faz:** nada aqui descreve futebol.

---

## `RawEvidence ≠ CanonicalKnowledge`

É a separação que este PR formaliza, e ela decide todo o resto.

Um arquivo que diz `Manchester City` continua sendo **texto numa coluna**
depois de atravessar o intake inteiro. Ninguém o resolveu para um `TeamId`,
porque resolver identidade exige confiança, registro de conflito, procedência
da decisão e fila de revisão — e nada disso existe até o PR-03.

```
   arquivo externo          →   EVIDÊNCIA      (PR-02, aqui)
   bytes, hash, licença         guardada, versionada, validada

   evidência interpretada   →   CONHECIMENTO   (PR-03)
   TeamId, MatchId              resolvido, fundido, com conflito registrado
```

A distância entre os dois é um PR inteiro. Encurtá-la — "só resolver o nome
do time, é uma linha" — produz três grafias virando três clubes, cada um com
um terço do histórico, e a tabela continua somando.

Isso é verificado, não prometido: `tests/architecture/test_intake_boundaries.py`
falha o CI se `domain/datasets`, `ingestion/historical` ou `ingestion/validation`
importarem o domínio futebolístico ou definirem uma função com nome de
resolução.

---

## O ciclo de vida

```
REGISTERED ──► UPLOADING ──► UPLOADED ──► VALIDATING ──► VALIDATED ──► STAGED
                   ▲             │             │              │
                   └─────────────┘             ▼              │
                  (mais arquivos)          INVALID ───────────┘
                                                          (revalidar)

   estados de exceção:  INVALID · REJECTED · FAILED
```

**`REGISTERED → STAGED` não existe.** Não como conferência em tempo de
execução: como aresta ausente do grafo. A diferença importa porque uma
conferência especial sobrevive a alguém acrescentar um estado no meio, e a
ausência da aresta obriga a decisão a ser tomada de novo.

| Estado | O que significa | Aceita arquivo novo? |
|---|---|---|
| `REGISTERED` | metadados e fonte declarados; nenhum byte | sim |
| `UPLOADING` | há intenção de arquivo sem bytes confirmados | sim |
| `UPLOADED` | todo arquivo declarado tem bytes confirmados | sim |
| `VALIDATING` | validação em andamento — **o conjunto sela aqui** | não |
| `VALIDATED` | validado sem impeditivo | não |
| `STAGED` | apto a **entrar** em resolução e fusão | não |
| `INVALID` | a validação encontrou impeditivo | não |
| `REJECTED` | um humano recusou | não |
| `FAILED` | falha nossa: store fora, worker morto | não |

**Por que `UPLOADING` existe.** Para um upload simples ele parece cerimônia.
Ele ficou porque tem uma semântica que nenhum outro estado tem: é a janela em
que existe intenção de arquivo no banco sem bytes confirmados no object store
(ou o inverso). Object store e transação SQL não commitam juntos, e fingir que
sim é a origem de um `STAGED` falso. `UPLOADING` é o nome desse intervalo, e é
o que a reconciliação procura.

**Por que o conjunto sela em `VALIDATING` e não antes.** Acrescentar um arquivo
depois de enviar os outros é o caso normal — o operador percebeu que faltava
uma temporada. O que não pode é acrescentar **depois de a validação começar**:
o relatório descreve um conjunto, e um arquivo que entrasse em seguida ficaria
coberto por um relatório que não o examinou.

---

## `STAGED` não é `HISTORICAL_ACTIVE`

É o mal-entendido mais provável deste documento.

```
STAGED     o bruto foi recebido, preservado, e é estruturalmente apto a
           ENTRAR em resolução de identidade e fusão.

NÃO É      apto a alimentar o índice histórico, o vetor, ou qualquer
           inteligência.
```

Entre um e outro estão o PR-03 inteiro e a barreira do ADR-0007. A guarda é
executável: `assert_not_intelligence_ready()` **recusa sempre**, inclusive
para `STAGED`, e existe para ser chamada por qualquer caminho futuro que
pretenda alimentar o histórico a partir de um dataset de intake. O evento
`dataset.staged` carrega `intelligence_ready: false` no payload, e a resposta
da API o repete — para que nenhum consumidor precise inferir.

---

## Identidade e endereçamento por conteúdo

Três perguntas aparecem no primeiro dia de operação manual, e nenhum nome de
arquivo responde:

| Pergunta | Resposta |
|---|---|
| o operador reenviou o mesmo arquivo? | mesmo SHA-256 |
| ele renomeou e reenviou? | mesmo SHA-256, nome diferente |
| ele corrigiu e manteve o nome? | mesmo nome, SHA-256 diferente |

Sem hash, o primeiro caso duplica, o segundo duplica, e o terceiro sobrescreve
em silêncio — que é o pior dos três, porque destrói evidência sem deixar rastro.

**Identidades derivadas, e de quê:**

```
DatasetId       uuid5(nome, versão)              registrar 2x devolve o mesmo
DatasetFileId   uuid5(dataset, versão, sha256)   reenviar 2x devolve o mesmo
object_key      contém o sha256                  regravar escreve no mesmo lugar
```

O hash **não** é o `DatasetId`: um dataset continua sendo a mesma unidade
lógica quando um arquivo é acrescentado, e amarrar sua identidade ao conteúdo
faria cada correção criar outro dataset, perdendo o histórico de decisões.

---

## Armazenamento bruto e imutabilidade

```
datasets/raw/dataset=<uuid>/version=v1.0/sha256=<hash>/<nome-limpo>
```

Três propriedades, cada uma pagando um custo específico:

- **determinística** — o retry escreve no mesmo lugar o mesmo conteúdo;
- **endereçada por conteúdo** — dois arquivos diferentes nunca disputam a
  mesma chave;
- **segura por construção** — todo componente que decide o *caminho* é gerado
  por nós (uuid, versão, hash hexadecimal). O único que vem de fora é o nome,
  e ele entra sanitizado, como folha, onde não redireciona nada.

O nome sobrevive na folha porque um bucket em que todo objeto se chama
`sha256=ab3f.../data` é ilegível para quem opera — e a legibilidade do arquivo
bruto é o que faz alguém conseguir auditá-lo dois anos depois.

**`ObjectStorePort` não tem `delete`, `update`, `copy` nem `move`**, e a
ausência é o contrato (ADR-0014). O bruto é a única camada que não se
reconstrói: dele derivam todas as outras, e ele precisa sobreviver inclusive a
um erro *nosso* de interpretação — que é exatamente o caso em que alguém teria
a tentação de "limpar e reimportar".

---

## O protocolo de três fases

Não existe transação distribuída entre PostgreSQL e S3. O desenho que finge o
contrário produz, mais cedo ou mais tarde:

```
linha no banco, bytes ausentes    →  o dataset "tem" um arquivo vazio
bytes no store, linha ausente     →  bytes órfãos, invisíveis ao registro
```

O primeiro é o perigoso: `len(files) == 3` passa por qualquer contagem, e o
dataset chega a `STAGED` afirmando ter preservado três arquivos quando
preservou dois.

```
1.  lê o stream, calcula SHA-256 e tamanho      memória constante
2.  INSERE a linha em PENDING                   transacional
3.  grava os bytes no arquivo bruto             NÃO transacional
4.  CONFIRMA a linha para STORED                transacional
```

**Um arquivo em `PENDING` não conta.** Não entra em validação, não entra no
manifesto, e não deixa o dataset sair de `UPLOADING`. É o que impede a
contagem de mentir.

| Falha | O que fica | Como converge |
|---|---|---|
| entre 2 e 3 | linha `PENDING`, sem bytes | reenvio retoma da fase 3 |
| entre 3 e 4 | bytes gravados, linha `PENDING` | reenvio vê o objeto, não regrava, confirma |
| bytes órfãos | objeto sem linha | inofensivo; limpeza é administrativa |

`ReconcilePendingUploads` fecha a janela: para cada `PENDING` antigo, pergunta
ao arquivo bruto se os bytes chegaram — confirma se sim, marca `FAILED` se
não. Ela **não apaga nada**: uma linha que desaparece depois de falhar leva
junto a informação de que alguém tentou enviar aquele arquivo.

---

## Validação estrutural

### O que ela verifica

Bytes presentes com o tamanho registrado · formato declarado conferido contra
o conteúdo · compactação recusada · encoding UTF-8 (BOM aceito) · cabeçalho
presente · coluna duplicada · coluna sem nome · número de campos por linha ·
JSONL com objetos válidos · Parquet legível · colunas obrigatórias declaradas ·
tipos declarados · limites de tamanho e de linhas · conteúdo duplicado entre
arquivos · divergência de schema entre arquivos do mesmo dataset.

### O que ela propositalmente **não** verifica

| Não verifica | Por quê |
|---|---|
| que `HomeTeam` é um time | resolução de identidade — PR-03 |
| que `2019-08-09` é uma data válida | exige fuso, que o arquivo não declara |
| que o placar é plausível | semântica futebolística — PR-03+ |
| que duas fontes concordam | fusão — PR-03 |
| que não falta a rodada 12 | completude do domínio, não do arquivo |

### A ordem é a defesa

Todo parser é superfície de ataque: aceita bytes arbitrários e faz alocação,
recursão e decodificação com base neles. Então, **antes** de qualquer parser
ver o arquivo:

```
é compactado?        recusa   (zip bomb não chega ao descompressor)
é do formato certo?  recusa   (o parser errado nunca é chamado)
o texto decodifica?  recusa   (nenhum decodificador roda sobre o resto)
```

Latin-1 **não** é adivinhado: toda sequência de bytes é Latin-1 válida, então
"detectar" Latin-1 é sempre dizer sim — e o resultado é `Ã§` no lugar de `ç`
atravessando o pipeline sem nenhum erro.

### Severidades, e a linha que importa

```
INFO       observado, sem defeito         não muda nada
WARNING    suspeito, provavelmente ok     alguém deveria olhar
ERROR      defeito localizado             algumas linhas se perdem
BLOCKING   o arquivo não é o que diz ser  nada adiante funciona
```

A linha está entre `ERROR` e `BLOCKING`, e separa dano **local** de dano
**total**. Doze linhas malformadas em cem mil é `ERROR`: o operador decide se
importa. Um Parquet declarado como CSV é `BLOCKING`.

`is_valid = True/False` apagaria essa diferença — e as ações que os dois casos
pedem são opostas.

**Só `BLOCKING` impede `STAGED`.** A severidade é propriedade do **código** do
achado, numa tabela única: se cada lugar que emite escolhesse, o mesmo defeito
seria impeditivo num arquivo e aviso em outro.

### Teto de issues

Um arquivo com separador errado produz uma issue por linha. Guardar um milhão
de linhas de relatório para dizer "o separador está errado" derruba o banco
sem acrescentar informação depois da décima.

```
issues       a amostra guardada        (teto configurável, default 200)
issue_count  o total real encontrado
truncated    se a amostra perdeu algo
```

As três, porque só a amostra mentiria sobre a extensão e só o total não
deixaria ninguém entender o problema. **Um impeditivo nunca é descartado por
teto**: se o teto encheu de avisos e o impeditivo chegou depois, ele entra no
lugar do último aviso — o relatório precisa *conter* o motivo pelo qual o
dataset não sobe, não apenas contá-lo.

---

## Formatos

| Formato | Como é inspecionado | Custo |
|---|---|---|
| `PARQUET` | rodapé via PyArrow: schema, tipos, contagem | alguns KB, independente do tamanho |
| `CSV` | varredura linha a linha + Polars para tipos | proporcional às linhas |
| `JSONL` | linha a linha com guarda de profundidade + Polars | proporcional às linhas |

**XLSX ficou de fora por decisão**: é um zip de XML, o que traz zip bomb,
fórmula, macro e três bibliotecas de superfície ampla para ler o que o operador
exporta para CSV em dois cliques.

**Compactação não é aceita**, e a ausência é declarada em vez de silenciosa:
uma decompression bomb causa dano *dentro* da biblioteca de descompressão,
antes de qualquer limite nosso ter chance de agir.

**Parquet é o preferencial interno e nada é convertido na entrada.** O bruto
recebido permanece exatamente como chegou; conversão, quando existir, produz um
artefato derivado ao lado — nunca por cima.

---

## Idempotência

| Caso | Comportamento |
|---|---|
| registrar o mesmo (nome, versão) | devolve o existente, `criado = False`, HTTP 200 |
| reenviar os mesmos bytes | reconhecido pelo hash, nada regravado, HTTP 200 |
| nome diferente, bytes iguais | mesmo arquivo; `was_duplicate = True` |
| mesmo nome, bytes diferentes | arquivo distinto |
| reemitir o mesmo manifesto | mesma impressão, mesma linha |

**Imposta pelo banco, não por Python.** `UNIQUE (dataset_id, sha256)` e
`ON CONFLICT DO NOTHING`: dois uploads simultâneos dos mesmos bytes chegam
juntos, ambos consultam, ambos não encontram, ambos inserem. Só a constraint
impede.

**Duplicata física vs. lógica.** O hash detecta a primeira — os mesmos bytes.
A segunda — o mesmo jogo vindo de duas fontes — é indecidível aqui e é do
PR-03. Este estágio não tenta.

---

## Concorrência

Toda transição de estado é condicional ao estado anterior:

```sql
UPDATE datasets SET lifecycle = $novo
WHERE id = $id AND lifecycle = $esperado
```

`rowcount == 0` significa que outro processo mudou antes. É controle otimista
feito onde funciona; a alternativa — ler, decidir em Python, escrever — deixa
duas requisições lerem `UPLOADED`, ambas concluírem que podem validar, e ambas
seguirem.

A transição para `VALIDATING` **é** o lock da validação. E o grafo do domínio
decide se a transição existe antes de o banco decidir quem chega primeiro: sem
essa primeira metade, um dataset já em `VALIDATING` passaria pela condição (o
estado esperado bateria consigo mesmo).

---

## Licença

`LicenseClass` é obrigatória e viaja com o dataset desde a primeira linha.

- `UNKNOWN` e `RESEARCH_ONLY` **não impedem** armazenar nem validar — a
  evidência precisa ser guardada antes de qualquer decisão sobre ela;
- eles marcam `needs_license_review`, e a validação emite
  `LICENSE_REVIEW_REQUIRED` (severidade `INFO`);
- a promoção futura para uso comercial ativo não pode acontecer por omissão:
  quem promover terá de responder à pergunta.

Neste PR isso é **sinalização, não política comercial**. `UNKNOWN` responde
`allows_commercial_use = False` — o default de uma pergunta sem resposta nunca
pode ser "pode tudo".

---

## Auditoria

Toda mutação administrativa gera uma entrada com ator, ação, dataset,
arquivo, correlação e instante. Ações de **decisão humana** — `DATASET_STAGED`,
`DATASET_REJECTED` — exigem motivo, cobrado no domínio e no banco.

**Só mutação entra.** Registrar leitura faria o volume da trilha ser governado
pelo tráfego em vez de pelas decisões, até ninguém conseguir achar as decisões
no meio.

**Nunca conteúdo de dataset.** O `detail` tem teto de 20 chaves e 512
caracteres por valor: sem isso, alguém acrescenta "a linha que falhou" para
depurar, e aquilo fica — numa tabela lida por quem tem direito de ver decisões
e não necessariamente o dado.

O ator vem de quem autenticou (`X-Actor-Id` na API, usuário do sistema na CLI),
nunca do corpo da requisição, e nunca de um padrão global: `Actor` recusa
`system`, `admin`, `root`, `unknown` — cada um deles, encontrado numa trilha
dois anos depois, significa exatamente "não sabemos quem fez".

---

## Uso

### Infraestrutura local

```bash
make infra-up      # PostgreSQL + MinIO, só os dois que o código exercita
make migrate
engine doctor
```

### Fluxo completo

```bash
engine dataset create \
  --name premier-league-2019-2024 \
  --source-name football-data.co.uk \
  --source-type OPEN_DATA \
  --provider-id football_data \
  --license-class ATTRIBUTION_REQUIRED \
  --retrieved-at 2026-08-01T10:00:00Z \
  --competition PREMIER_LEAGUE \
  --season 2019-2020 --season 2020-2021

engine dataset upload <id> ./E0.csv --format CSV
engine dataset validate <id> --required Date --required HomeTeam
engine dataset validation <id>
engine dataset manifest <id>
engine dataset stage <id> --reason "conferido contra o site da fonte"
```

### API

```
POST   /v1/datasets                      201 criado · 200 já existia
GET    /v1/datasets                      paginado, com filtros
GET    /v1/datasets/{id}
POST   /v1/datasets/{id}/files           corpo cru + X-Filename + ?format=
GET    /v1/datasets/{id}/files
POST   /v1/datasets/{id}/validate
GET    /v1/datasets/{id}/validation
GET    /v1/datasets/{id}/manifest
POST   /v1/datasets/{id}/stage           exige motivo
```

O upload é `application/octet-stream` com o nome num cabeçalho, e não
`multipart/form-data`: o corpo é o arquivo e nada mais, sem um parser de
multipart entre a rede e o hash, e o limite é cobrado **enquanto** se lê — com
multipart, quem decide quando parar é a biblioteca, e a maioria bufferiza a
parte inteira.

`Content-Length` não é usado como limite: ele é do cliente, e um cliente que
mente sobre o tamanho é justamente o que o limite existe para conter.

**Não há rota de download.** O arquivo bruto é evidência, não um serviço de
arquivos, e publicar um caminho de leitura transformaria o Control Plane num
CDN de dados licenciados.

---

## Limites configuráveis

| Setting | Default | O que protege |
|---|---|---|
| `ENGINE_INTAKE_MAX_FILE_SIZE_BYTES` | 2 GiB | o backup de um banco enviado por engano |
| `ENGINE_INTAKE_MAX_FILES_PER_DATASET` | 200 | laço de upload com defeito |
| `ENGINE_INTAKE_MAX_ROWS_PER_FILE` | 50.000.000 | o caso patológico |
| `ENGINE_INTAKE_MAX_VALIDATION_ISSUES` | 200 | um milhão de issues idênticas |
| `ENGINE_INTAKE_UPLOAD_SPOOL_THRESHOLD_BYTES` | 8 MiB | o pico de memória por upload |

São **configuração e não constante de código**: o limite certo depende da
máquina e do disco, e um número fixo obriga um deploy para ajustá-lo — o que,
na prática, significa que ninguém ajusta e alguém contorna.

---

## Limitações declaradas

- **Validação síncrona.** Um arquivo grande segura a requisição. O contrato já
  suporta a mudança (o estado `VALIDATING` é persistido, o relatório tem id
  próprio), então trocar por um worker é trocar quem chama `execute`.
- **Sem worker de reconciliação agendado.** `ReconcilePendingUploads` existe e
  é chamável; nada o dispara periodicamente ainda.
- **Bytes órfãos não são limpos.** São inofensivos — nenhuma consulta os
  alcança — e apagar objeto do arquivo bruto é a única operação que este PR
  deliberadamente não oferece por caminho de código.
- **Sem RBAC.** Há `Actor` obrigatório e token interno; não há papéis nem
  permissões por operação.
- **Eventos em log.** `LoggingEventPublisher` até existir consumidor; Redis
  Streams é o destino (ADR-0004).
- **Sem compactação e sem XLSX.** Declarado acima.

---

## Leitura relacionada

- [`DATASET_MANIFEST_V1.md`](DATASET_MANIFEST_V1.md) — o schema do manifesto
- **ADR-0014** — imutabilidade do dataset bruto
- **ADR-0015** — endereçamento por conteúdo e idempotência
- **ADR-0016** — o limite de staging (`STAGED ≠ HISTORICAL_ACTIVE`)
- **ADR-0017** — consistência entre banco e object store
