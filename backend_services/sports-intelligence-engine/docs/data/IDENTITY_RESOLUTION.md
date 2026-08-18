# Resolução de identidade — V1

Como o motor decide que um texto numa coluna representa uma entidade canônica,
e por que ele prefere **não decidir** quando a evidência não basta.

> **O princípio que governa tudo aqui:** o sistema jamais deve confundir
> *"parece ser a mesma entidade"* com *"foi provado ser a mesma entidade"*.

---

## `Resolution ≠ Fusion`

Duas perguntas, nesta ordem, e a ordem não é negociável:

```
1.  quem ou o que este registro representa?          RESOLUÇÃO
2.  que informações das várias fontes se combinam?   FUSÃO
```

É **proibido** o caminho inverso — juntar linhas parecidas e depois inferir a
identidade do que sobrou. A ordem obrigatória é:

```
IDENTIDADE  →  AGRUPAMENTO  →  FUSÃO
```

E ela não é convenção: `ResolvedSourceRecord` — o único tipo que a fusão
aceita — não se constrói sem `resolution_decision_id`. Não existe caminho de
código que funda identidade não provada (ADR-0022).

---

## O que é uma decisão

Nenhuma resolução é um booleano. Toda decisão carrega sete coisas:

| | |
|---|---|
| **o que foi decidido** | status + entidade canônica |
| **com base em quê** | evidências, uma a uma, com peso e resultado |
| **quão forte** | confiança explícita, em [0,1] |
| **por qual regra** | método, de um catálogo fechado |
| **sob qual versão** | resolver, normalizador e política |
| **quem decidiu** | ator humano ou de serviço |
| **de qual entrada** | dataset, versão e impressão do manifesto |

Sem as sete, a decisão não é auditável — e uma decisão de identidade que não
se audita é indistinguível de um palpite que deu certo.

### Status — cinco, e nenhum é booleano

```
RESOLVED          entidade identificada com evidência suficiente
UNRESOLVED        nenhum candidato plausível
AMBIGUOUS         dois ou mais empatados — o motor SABE que não sabe
REVIEW_REQUIRED   há um provável, e não o bastante para decidir sozinho
REJECTED          decidido que NÃO corresponde a nada (fora do catálogo, lixo)
```

`resolved = True/False` apagaria a distinção que mais importa
operacionalmente: entre «não achei nada» e «achei dois e não sei qual». A
primeira se conserta com mais dados; a segunda, com uma decisão humana.

**Só `RESOLVED` produz referência canônica utilizável.** É a guarda que a
fusão consulta, e ela é cobrada no domínio **e** no banco.

### Método — como, e nunca `AUTO`

```
EXACT_PROVIDER_MAPPING   já havia mapeamento persistido       confiança 1,0
EXACT_CANONICAL_KEY      casou com a chave canônica           confiança 1,0
EXACT_ALIAS              casou com alias registrado           confiança 1,0
COMPOSITE_RULE           regra determinística composta
CONFIDENCE_MATCH         similaridade acima do limiar, com apoio
MANUAL_REVIEW            um humano decidiu
```

`AUTO` responde «não foi humano» e não diz nada sobre a força da conclusão. Um
mapeamento de provedor conhecido e um casamento por similaridade de nome são
as duas coisas mais distantes possíveis em confiabilidade — e ambos seriam
`AUTO`.

---

## Confiança não é probabilidade

`ResolutionConfidence` está em [0,1] e **não** é probabilidade calibrada.

Uma probabilidade calibrada afirma que, de cem casos com confiança 0,9,
noventa estarão certos — e essa afirmação exige um conjunto rotulado que não
existe e que ninguém mediu. Publicar um número como se fosse probabilidade,
sem calibração, é a forma mais fácil de o operador confiar num limiar que
nunca foi verificado.

O que o número significa, e só:

> a força da evidência usada nesta decisão, segundo a versão **atual** do
> resolver e da política.

Duas consequências, ambas deliberadas:

- comparar confianças entre versões de resolver é comparar réguas diferentes,
  e `DecisionVersions.assert_comparable` recusa fazê-lo;
- o limiar de auto-resolução é **configuração versionada**, não constante —
  porque ele é uma escolha de risco, não uma verdade medida.

Quando houver corpus rotulado para calibrar de verdade, isto vira uma
probabilidade com `CalibrationVersion` própria, e esta classe sai.

---

## A política do falso merge

```
Custo(falso merge)  >  Custo(não resolvido)
```

Um `PlayerId` errado contamina influência de jogador, força de elenco, estados
históricos e grafo tático — e a contaminação **não é detectável depois**,
porque tudo continua somando. Um registro não resolvido é visível, contável e
consertável.

Por isso, na dúvida: `REVIEW_REQUIRED` (ADR-0018).

Os limiares vivem em `ResolutionPolicy`, versionada, e **nenhum resolver
escreve um número**. Um teste de arquitetura falha o CI se um literal de
limiar aparecer numa comparação dentro dos resolvers.

| sujeito | auto | revisão | evidências mínimas | por quê |
|---|---|---|---|---|
| competição | 0,95 | 0,75 | 1 | catálogo fechado de cinco, casamento exato |
| temporada | 0,90 | 0,60 | 2 | exige a competição como evidência obrigatória |
| time | 0,92 | 0,65 | 2 | nome sozinho nunca basta |
| **jogador** | **0,96** | 0,55 | **3** | homônimo é comum, e o erro é irreversível |
| partida | 0,90 | 0,60 | 3 | competição e temporada obrigatórias |

Além do limiar, três guardas duras — e a **ordem** delas importa, porque um
score alto obtido por uma evidência só nunca deve ultrapassar a exigência de
corroboração:

1. **evidência obrigatória** — sem competição não se resolve temporada;
2. **corroboração mínima** — o nome é UMA evidência;
3. **margem mínima** — dois candidatos a 0,91 e 0,90 viram `AMBIGUOUS`, porque
   0,01 não é informação, é ruído da régua.

---

## Normalização de nomes

Determinística, sem estado, versionada (`NormalizerVersion`).

```
Manchester City FC  →  manchester city      sufixo societário removido
Sporting CP         →  sporting cp          PRESERVADO
Grêmio              →  gremio               acento removido
The Arsenal FC      →  arsenal fc           artigo removido, sufixo não
```

**A metade difícil é o que ela NÃO faz.** `Sporting CP` não pode virar
`sporting`: existem Sporting CP, Sporting Gijón, Sporting Kansas City e
Sporting Cristal, e apagar o qualificador funde quatro clubes de quatro
continentes.

Três regras saem disso:

- remoção apenas de sufixos de um **catálogo fechado** (`fc`, `afc`,
  `football club`, `sad`, `ltda`…);
- apenas quando sobram **duas palavras significativas**;
- nunca de palavras que **compõem identidade** — `United`, `City`, `Real`,
  `Sporting`, `Athletic`, `Dynamo`, `Wanderers`… — mesmo soltas.

`Chelsea FC` continua `chelsea fc`, e é conservador de propósito: o alias
explícito resolve, a remoção agressiva não.

### Similaridade

Jaro-Winkler + Jaccard de tokens, **implementados aqui**, sem dependência
externa (`ingestion/normalization/similarity.py`).

Não é preferência estética. Duas razões concretas:

- **determinismo entre versões** — a implementação de Jaro-Winkler varia entre
  bibliotecas no tamanho do prefixo, no fator de escala e no tratamento de
  transposições. Trocar de versão da biblioteca mudaria scores gravados, e
  decisões de identidade guardam score;
- **leitura** — o resolver é o ponto em que alguém vai querer entender
  exatamente por que dois nomes casaram.

Se o volume justificar velocidade, a troca é substituir a implementação atrás
do mesmo ponto de uso, sem tocar em nenhum resolver.

**Nada de embedding nem LLM** (§64). Similaridade de nome precisa ser
explicável e estável, e a diferença entre `Sporting CP` e `Sporting Gijón` é
exatamente o tipo de distinção que um espaço vetorial de propósito geral
colapsa. Um teste de arquitetura falha o CI se `sklearn`, `torch`,
`transformers`, `faiss` e afins aparecerem em qualquer camada.

---

## A cadeia operacional

A ordem que `RunIdentityResolution` percorre por registro:

```
mapeamento de provedor        →  caminho PRIORITÁRIO, quando a fonte traz id
      ↓ (quando não há)
competição → temporada → time → partida
jogador                       →  ramo próprio, independente da cadeia da partida
```

**O mapeamento de provedor vem primeiro** (PR-03.2). Um id que já foi
traduzido é a evidência mais barata e mais estável que existe: alguém já
tomou aquela decisão e ela ficou registrada. Reler `Manchester City` por texto
a cada execução é refazer trabalho conferido.

Ele é resolvido sobre os valores **distintos** do lote, como tudo o mais — mil
linhas de Premier League têm vinte ids de clube, não mil.

**O ramo de jogador é independente da cadeia da partida.** Um registro cuja
competição não resolveu ainda pode ter identidade de jogador legítima;
pendurá-lo na cadeia faria a primeira falha apagar a segunda.

A etapa é condicional ao **mapeamento**, não a um `if` sobre o dataset: se a
fonte declara `PLAYER_NAME`, há identidade de jogador para resolver. O clube
vem de `TEAM_NAME` quando declarado, e é ele que ativa a evidência temporal —
`team_at` responde pelo vínculo **na data**, nunca pelo clube atual.

---

## Os cinco resolvers

### Competição

Catálogo fechado de cinco, **sem fuzzy irrestrito**. Ou casa exato — código,
nome canônico, alias registrado — ou é uma competição que não cobrimos.

Fora do catálogo é **`REJECTED`**, não `UNRESOLVED`: a Bundesliga não vai
aparecer no catálogo da V1 por mais que se espere, e mantê-la em `UNRESOLVED`
faria a fila crescer com casos que nunca resolvem.

Os aliases das cinco são **semeados** (`EPL`, `E0`, `Campeonato Brasileiro`,
`UCL`…). Um alias errado se corrige com um `DELETE`; uma regra errada no
resolver exigiria deploy.

### Temporada

`2024` **não** resolve universalmente (§15):

| escrita | Brasileirão | Premier League |
|---|---|---|
| `2024` | temporada de 2024 | 2023/24 — ou 2024/25, conforme o publicador |
| `2023/24` | — | 2023/24 |

Três fontes de desambiguação, em ordem:

1. a **convenção declarada** pela fonte no mapeamento (`CALENDAR_YEAR` /
   `SPLIT_YEAR`);
2. o rótulo canônico da temporada, normalizado;
3. a **data da partida** — a evidência mais forte, porque a janela registrada
   de cada temporada responde sem precisar da convenção.

Sem nenhuma das três: revisão. Não adivinha.

### Time

Ordem: mapeamento de provedor → alias → nome canônico exato → similaridade com
evidência de apoio.

**País divergente é penalidade forte.** É a evidência que separa Sporting CP
de Sporting Kansas City — e foi a ausência dela que fundiu clubes entre
continentes no motor anterior, com 591 partidas atribuídas ao clube errado.

`Man City` **não** casa com `Manchester City` por similaridade (`man` e
`manchester` são palavras diferentes) e resolve por **alias registrado**.
Abreviação de fonte é registrada, não inferida.

### Jogador — o mais conservador

Evidências: id do provedor, nome normalizado, **data de nascimento**,
nacionalidade, **clube na data**, posição, competição, temporada.

```
mesmo nome + mesma DOB + mesmo clube      →  candidato forte
mesmo nome + DOB diferente                →  NÃO resolve (penalidade quase fatal)
mesmo nome + clube/data diferente         →  confiança reduzida
mesmo nome, sem nada que distinga         →  AMBIGUOUS, sempre
```

**Homônimo jamais auto-resolve por nome.** Além do limiar de 0,96 e das três
evidências mínimas, há uma trava explícita: quando o nome normalizado casa com
mais de um jogador e nada os distingue, o resultado é `AMBIGUOUS` mesmo que
uma evidência fraca empurre um deles para cima.

**O clube é o da DATA, nunca o atual** (§20). `team_at` devolve `None` fora da
janela do vínculo — devolver o clube atual como aproximação reescreveria o
passado, e aqui viraria evidência falsa a favor de um candidato errado.

### Partida

Score composto de sete dimensões, com pesos versionados em
`MatchResolutionPolicy` (somam 1,0 — verificado, porque um conjunto que soma
0,8 produz score que nunca alcança o limiar e o sintoma é «nada resolve»).

```
competição 0,22   temporada 0,14   mandante 0,20   visitante 0,20
horário    0,16   fase      0,04   rodada   0,02   estádio   0,02
```

**Competição e temporada são evidência dura.** Dois jogos entre os mesmos
times na mesma data em competições diferentes existem — copa e liga —, e sem
essa trava eles seriam fundidos.

**Tolerância de horário em três faixas**, não numa curva contínua: a diferença
entre 14 e 16 minutos não é informação, e entre 15 minutos e 3 horas é.

```
≤ 15 min    1,00   arredondamento, hora cheia
≤  3 h      0,50   fuso provavelmente não declarado
≤ 26 h      0,15   mesmo dia, horário muito diferente
acima       0,00   outra partida
```

Fuso não declarado vira evidência **fraca** (`TIMEZONE_UNDECLARED`), nunca
correção silenciosa.

**Inversão de mando nunca é corrigida automaticamente** (§24). `Arsenal x
Chelsea` contra `Chelsea x Arsenal` produz candidato com penalidade de 0,35 —
o bastante para cair na faixa de revisão. Trocar automaticamente resolveria o
caso em que a fonte errou e **destruiria** o caso em que são os dois jogos do
returno.

**Estádio é apoio, nunca autoridade.** Campo neutro, punição e mudança
logística fazem uma partida legítima acontecer em outro lugar.

---

## Mapeamentos e aliases

```
ProviderRef  →  MappingRepository  →  EntityId       (quando já há mapeamento)
ProviderRef  →  Resolver → Decision → Mapping        (quando não há)
```

**Não existe `ProviderRef.to_entity_id()`** e nunca vai existir (ADR-0011). A
passagem entre a referência do provedor e a identidade do domínio é uma
decisão — com evidência, confiança e possibilidade de falhar — e um atalho a
transformaria num cast. Um teste de arquitetura guarda a ausência.

Todo mapeamento aponta para a `ResolutionDecision` que o originou, e o campo é
**obrigatório**: um mapeamento sem decisão que o explique é indistinguível de
um mapeamento inventado.

**Reapontar um mapeamento é conflito explícito.** Se `MCI → Manchester City`
existe e uma execução conclui `MCI → Melbourne City`, sobrescrever faria todo
o histórico já resolvido apontar para o clube errado — e nada falharia. A
saída é `ConflictError`: alguém decide qual está errado, e a correção vira
janela de validade.

**Aliases ficam FORA da entidade** (§17). Um clube tem um nome canônico e
ganha aliases pelo resto da vida, um por fonte, alguns com janela. Guardá-los
dentro faria toda leitura de clube carregar uma lista que quase nenhum caminho
usa.

---

## A fila de revisão

Ela é a **contraparte do conservadorismo**. Uma política que prefere
`REVIEW_REQUIRED` a um merge duvidoso só funciona se existir para onde mandar
o duvidoso — senão a escolha conservadora vira «esse dado simplesmente some»,
e a pressão para afrouxar o limiar fica irresistível.

```
OPEN  →  IN_REVIEW  →  RESOLVED
                    →  REJECTED
```

Quatro estados e um dono opcional. **Não é workflow**: sem etapas, aprovação
em dois níveis, SLA nem escalonamento — um motor de workflow construído antes
do segundo caso de uso é calibrado para um caso hipotético.

**A decisão humana é evidência, não exceção** (§31). Resolver um item produz
uma `ResolutionDecision` completa: método `MANUAL_REVIEW`, ator humano, motivo
obrigatório. Nunca um `UPDATE` silencioso no mapeamento.

E o ciclo se fecha: a decisão grava o **alias**, e a próxima execução resolve
sozinha. Sem isso, o mesmo nome cairia na fila em toda execução, e o operador
decidiria a mesma coisa indefinidamente.

```bash
engine resolution review list
engine resolution review resolve <item> --entity-id <id> --reason "conferido no site"
engine resolution review reject  <item> --reason "clube não existe no nosso catálogo"
```

**Rejeitar também produz decisão.** Sem ela, o item rejeitado seria
indistinguível de um que ninguém olhou — e a próxima execução o recolocaria na
fila.

---

## Contrato de fonte

O mapeamento declara qual coluna carrega qual **papel semântico**:

```jsonc
{
  "provider_id": "football_data",
  "conventions": { "season_convention": "SPLIT_YEAR" },
  "fields": [
    { "column": "Div",      "role": "COMPETITION_NAME" },
    { "column": "HomeTeam", "role": "HOME_TEAM_NAME" },
    { "column": "Date",     "role": "KICKOFF_DATE", "date_format": "%d/%m/%Y" }
  ]
}
```

`HOME_TEAM_NAME` diz «aqui há um texto que a fonte usa para nomear o
mandante» — uma afirmação sobre o **arquivo**, que o operador faz olhando o
cabeçalho. `TeamId` seria uma afirmação sobre o **mundo**.

**Nada aqui é executável** (§81). Não há campo de expressão, não há `eval`, não
há regex fornecida pelo usuário. Transformações vêm de um catálogo fechado
(`TRIM`, `UPPER`, `STRIP_PERCENT`, `DECIMAL_COMMA`…), e formatos de data
também. Um mapeamento vem de fora, e o que vem de fora nunca vira código —
verificado por teste de arquitetura.

Mapeamentos são **versionados**: corrigir um publica outro, e as execuções que
rodaram sob o anterior continuam explicáveis.

---

## Execuções e reprocessamento

`ResolutionRun` é uma entidade própria, e **não** um estado novo em
`DatasetLifecycle` (§57). O ciclo do dataset descreve o que aconteceu com os
BYTES e foi encerrado em `STAGED`; resolução é um PROCESSO sobre esses bytes,
e o mesmo dataset passa por várias execuções com versões diferentes — todas
válidas, todas coexistindo.

**Uma execução concluída é imutável** (ADR-0019):

```
mesmo raw  +  resolver v1  →  ResolutionRun A
mesmo raw  +  resolver v2  →  ResolutionRun B     (A fica intacta)
```

A diferença entre A e B é o que mostra o que o resolver novo passou a
enxergar. Se B pudesse reescrever A, a comparação seria contra si mesma.

### Determinismo

Mesma entrada + mesmas versões + mesmo estado do registro canônico → **as
mesmas decisões, na mesma ordem**.

Nenhum `random`, nenhuma leitura de relógio dentro do resolver, e todo
desempate explícito: score decrescente, depois id da entidade. Dois candidatos
com o mesmo score saem do banco em ordem arbitrária, e sem desempate a mesma
entrada produziria decisões diferentes em execuções diferentes.

O contexto de resolução é uma **fotografia**: um mapeamento criado no meio do
lote não muda decisões já tomadas no mesmo lote.

### O universo de candidatos não depende do lote

```
Resolution(x, lote de 250)  ==  Resolution(x, lote de 5.000)
```

Vale para status, método, confiança, entidade **e a ordem das alternativas**.

Até o PR-03.1 não valia. O candidato de similaridade saía de `context.teams`,
que continha o que **aquele lote** tinha carregado por chave exata — então um
lote de cinco mil linhas enxergava clubes parecidos que um lote de duzentos e
cinquenta nem lia. A medição pegou: **2,7%** das listas de alternativas
mudavam. Nenhuma decisão `RESOLVED` mudava, e ainda assim era uma violação: a
lista de alternativas é o que o operador vê na fila de revisão.

Agora os candidatos vêm de uma busca **por nome**: as entidades que
compartilham pelo menos um token com o nome consultado, ordenadas por nome
exato primeiro, depois por tokens em comum, e o id como desempate final.

```
team_candidates_for_names(nomes, limit_per_name)  →  (nome consultado, Team)
```

Três propriedades, nessa ordem de importância:

- **por nome** — o resultado de `x` depende só de `x`;
- **em massa** — uma consulta para N nomes, com `unnest` e `LATERAL`;
- **limitado por nome, não no total** — um teto global faria o corte depender
  de quantos nomes vieram no lote, trocando uma dependência de lote por outra.

O `ORDER BY` dentro do `LATERAL` não é cosmético: ele decide **quem sobrevive
ao `LIMIT`**. Ordenar por id deixava três mil `Silva NNNNN` empurrarem os
homônimos exatos de `Rodrigo Silva` para fora do corte — e a resolução passava
a comparar o nome certo com cinquenta pessoas erradas.

---

## Desempenho e N+1

O caminho ingênuo resolve linha a linha e consulta o banco por linha:

```
100.000 linhas por 7 evidências = 700.000 SELECTs
```

Cada uma é uma ida à rede. Numa máquina razoável isso são horas, e o sintoma
não é erro — é «a resolução está lenta».

A saída é **inverter a ordem**:

```
ler lote → valores distintos → carregar candidatos → resolver → persistir
  1 I/O        0 I/O            ~6 consultas         0 I/O      1 I/O
```

Um lote de mil linhas de Premier League tem **vinte** nomes de clube, não mil.

Todo port de leitura recebe uma **coleção** e devolve uma **coleção** — a
assinatura é o antídoto. `find_team_by_name(nome)` convidaria ao laço por
linha; `teams_by_normalized_names(nomes)` não tem como ser chamado errado.

Redis **não** entra (§35): a autoridade é o PostgreSQL, o escopo é uma
execução, e um cache distribuído resolveria um problema de leituras repetidas
entre execuções que ainda não existe.

---

## Ator: humano e serviço

```
Actor.service("historical-resolution-worker")    kind=SERVICE
Actor.human("user:9f2b6f3e-…")                   kind=HUMAN_OPERATOR
```

`Actor` recusa `system`, `admin`, `root`, `unknown` — cada um deles,
encontrado numa trilha dois anos depois, significa exatamente «não sabemos
quem fez».

E a coerência é cobrada: `ResolutionDecision` recusa método `MANUAL_REVIEW`
com ator de serviço, e método automático com ator humano. O método diz que um
humano decidiu; o ator precisa concordar.

---

## Limites deste PR

```
RAW → STAGED → RESOLUTION RUN → FUSION RUN → CANDIDATO FUNDIDO
                                                    ≠
                                            HISTORICAL_ACTIVE
                                                    ≠
                                            MATCH STATE VECTOR
```

`assert_not_historical_active` existe nos dois lados — resolução e fusão — e
**recusa sempre**. Ela está lá para ser chamada por qualquer caminho futuro
que tente promover a saída.

Entre o candidato e o índice histórico estão a avaliação de qualidade e a
construção canônica — o PR-04 — mais a barreira do ADR-0007.

---

## Leitura relacionada

- [`DATA_FUSION.md`](DATA_FUSION.md)
- [`../contracts/RESOLUTION_DECISION_V1.md`](../contracts/RESOLUTION_DECISION_V1.md)
- **ADR-0018** — resolução conservadora de identidade
- **ADR-0019** — decisões versionadas e imutáveis
- **ADR-0021** — atores humanos e de serviço
- **ADR-0022** — resolução antes de fusão
