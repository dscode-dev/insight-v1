# Data Fusion — V1

Como valores de várias fontes viram um candidato canônico, e por que o
resultado desejável, muitas vezes, é **não escolher**.

---

## O que `dict_a.update(dict_b)` destrói

```
quem venceu           a última fonte escrita ganha, por acidente de ordem
o que foi descartado  o valor da outra fonte some
por quê               nenhuma regra foi registrada
de onde veio          a procedência por campo não existe
```

Depois disso, `home_score = 2` é um número sem pai. Ninguém consegue dizer se
saiu da fonte A ou da B, se elas concordavam, ou se uma delas dizia 3.

Então cada campo do resultado é um `CanonicalFieldCandidate`: valor escolhido,
fonte escolhida, alternativas preservadas, regra que decidiu, confiança e
procedência. **Um campo — não o registro.**

---

## Pré-condição: identidade provada

A fusão só aceita `ResolvedSourceRecord`, que não se constrói sem
`resolution_decision_id`. Não existe caminho de código que funda registros
cuja identidade não foi provada (ADR-0022).

Se não for possível **provar** que duas linhas pertencem à mesma partida, elas
não são fundidas. Ficam como estão, cada uma na sua fonte, e a execução
reporta quantas ficaram de fora.

### Agrupamento

```
FusionGroup
  canonical_match_id      a MESMA para todos os registros — verificado
  records[]               um por FONTE
```

**Duas linhas da mesma fonte para a mesma partida não formam duas
contribuições.** É duplicata interna daquela fonte, não confirmação — e
contá-las como duas fontes inflaria a concordância. Elas saem do grupo e a
execução as reporta como descartadas.

---

## Duas fusões diferentes

Confundi-las apaga dado (§52).

| | escalar | conjunto de observações |
|---|---|---|
| exemplos | `home_score`, `formation`, `attendance` | odds de várias casas, eventos |
| pergunta | qual é o valor certo? | quais observações existem? |
| conflito | possível | **não existe** |
| saída | `selected_value` + alternativas | conjunto deduplicado |

### Odds nunca são conflito

```
Casa X @ 2.00        duas observações distintas
Casa Y @ 2.05        as duas são verdade ao mesmo tempo
```

`(2.00 + 2.05) / 2 = 2.025` é um preço que **nenhuma casa ofereceu**, e a
média apagaria justamente a dispersão entre casas — que é o sinal que o Odds
Intelligence vai ler (§54).

### Identidade de observação

A deduplicação é por **discriminante**, e ele carrega casa **e valores**:

```
1X2|BET365|ODDS_HOME=2.00|ODDS_DRAW=3.40|ODDS_AWAY=3.60
```

Cada parte responde a uma pergunta que já foi respondida errado:

| parte | o que ela impede |
|---|---|
| casa | `BET365` e `PINNACLE` colapsarem numa cotação só |
| valores | duas cotações **diferentes** da mesma casa colapsarem |
| provedor (na chave de agrupamento) | contar a mesma fonte duas vezes |

**`mesma fonte` NÃO implica `mesma observação`** (PR-03.2). A regra de uma
linha por fonte está certa para fusão escalar — duas linhas dizendo o placar
são a mesma fonte falando duas vezes — e estava errada aqui: uma fonte que
publica **uma linha por casa de apostas** perdia todas menos a primeira. Nada
era promediado, e mesmo assim a dispersão entre casas sumia.

Agora a linha extra da mesma fonte tem três destinos, e a identidade de
observação decide qual:

```
identidade NOVA        entra como observação — FusionGroup.extra_observations
identidade REPETIDA    duplicata verdadeira — descartada e CONTADA
SEM identidade         não é observação: duplicata escalar, descartada
```

**Sem tolerância temporal.** A V1 não tem papel semântico para o instante da
cotação nem para o id dela no provedor, então não há como distinguir «tick
seguinte» de «linha repetida» por metadado. Na dúvida, preserva-se: valores
diferentes são observações diferentes, e só o payload **idêntico** da mesma
casa é tratado como repetição.

---

## Regras de fusão

```
EXACT_AGREEMENT       todas as fontes disseram o mesmo
PREFERRED_SOURCE      divergência, e a política nomeia uma preferida
HIGHEST_QUALITY       divergência resolvida pela qualidade declarada
MOST_COMPLETE         só uma fonte trouxe — cobertura, não conflito
MOST_PRECISE          divergência de precisão: 59.8 contra 60
MANUAL_SELECTION      um humano escolheu
CONFLICT_UNRESOLVED   divergência, e a política NÃO diz como resolver
```

### `EXACT_AGREEMENT` não é caso trivial

A concordância é **evidência**. Um valor confirmado por três fontes não é o
mesmo que um valor que só uma trouxe, e a confiança do campo reflete isso:

```
confiança = min(1,0 ; 0,6 + 0,2 × fontes concordantes)
```

Por isso `agreeing_sources` é plural: um `selected_from` único apagaria a
diferença.

### `CONFLICT_UNRESOLVED` é o resultado desejável

Quando a política não sabe decidir, o campo fica **sem valor selecionado** e
com todas as contribuições preservadas.

Escolher por desempate arbitrário produziria um número de aparência decidida
que ninguém revisaria. A ausência é a informação — e o banco a cobra:

```sql
CONSTRAINT fused_fields_conflito_sem_valor CHECK (
    (rule = 'CONFLICT_UNRESOLVED') = (selected_value IS NULL)
)
```

---

## Política por campo

`SOURCE_PRECEDENCE` (ADR-0009) ordena **fontes**: nativo, comercial, aberto,
manual. É a resposta certa para «quem ganha quando não há nada mais a dizer» e
a resposta errada para quase todo campo específico:

```
uma fonte é a melhor em xG e não publica escalação
outra tem escalação confiável e placar copiado de terceiros
uma terceira é a única com odds
```

Uma precedência global faria a primeira vencer em escalação por ser comercial
— e a escalação dela é a pior das três.

`INSIGHT_NATIVE` **não ganha automaticamente** (§47): ele vence por padrão
porque foi observado pelo próprio motor, e a política por campo pode inverter
isso — com a inversão declarada.

### O que a V1 declara

| campo | conflito | por quê |
|---|---|---|
| `HOME_SCORE`, `AWAY_SCORE` | `KEEP_UNRESOLVED` | duas fontes discordando de um fato público e verificável significa que uma está errada — escolher esconde um problema de fonte |
| `HOME_POSSESSION` | `PREFER_PRECISION`, tolerância 1,5 | diverge por arredondamento: 59.8 e 60 são a mesma observação |
| `HOME_XG`, `AWAY_XG` | `KEEP_UNRESOLVED` | xG é **modelo**, não observação: escolher um seria escolher um modelo sem dizer qual |
| `HOME_FORMATION` | `KEEP_UNRESOLVED` | `4-2-3-1` contra `4-3-3` é desacordo de interpretação, não de fato |
| `HOME_SHOTS` | `GLOBAL_PRECEDENCE` | diverge por critério de contagem; aqui a fonte melhor tende a ser melhor no geral |
| **qualquer outro** | `KEEP_UNRESOLVED` | o default preserva o conflito |

**O default é não resolver**, e é a decisão mais importante do módulo. Um
default que escolhe alguma coisa faria todo campo sem política declarada
produzir um valor de aparência decidida — e ninguém revisaria, porque nada
apareceria como conflito.

### Média exige declaração explícita

`allow_averaging` existe e é `False` em tudo. A média de dois placares é um
placar que nenhuma fonte observou. E a política **recusa** permitir média sem
tolerância declarada: se dois valores podem ser promediados, precisa estar
dito a que distância eles ainda descrevem a mesma coisa (§50).

---

## Procedência por campo

Cada contribuição carrega dataset, arquivo e linha:

```
canonical_match.home_score  =  2
  ← fonte_a  dataset=9f2b…:arquivo=3c1e…:linha=391   valor "2"   [selecionada]
  ← fonte_b  dataset=7a4d…:arquivo=8b2f…:linha=118   valor "3"
```

É a tabela `fused_field_sources` que responde «de onde veio este valor» — e
que preserva o que a outra fonte disse. Sem ela, a resposta seria «da fonte
B», que não permite conferir.

### Licença

O candidato herda a licença **mais restritiva do conjunto** (§76), não a da
fonte que venceu mais campos. Um campo cujo conflito foi resolvido consultando
a fonte restrita foi produzido usando-a — mesmo que o valor final tenha vindo
de outra. Usar a permissiva porque ela contribuiu mais seria contornar a
restrição pelo caminho de trás.

---

## Execuções e reprodutibilidade

`FusionRun` é imutável quando concluída (ADR-0020):

```
mesmos inputs  +  FusionPolicy v1  →  FusionRun A
mesmos inputs  +  FusionPolicy v2  →  FusionRun B     (A fica intacta)
```

Comparar as duas é o único jeito honesto de medir o que a política nova mudou.
Se B pudesse reescrever A, a comparação seria contra si mesma.

**Conflito não resolvido leva a `COMPLETED_WITH_REVIEW`**, não a `COMPLETED`.
Os dois são sucesso; a diferença é que o segundo diz «nada a fazer», e há
coisa a fazer.

### Impressão

```
FusionOutputFingerprint = SHA256( canonical_json(candidato) )
```

A saída é ordenada por nome de campo e por provedor — não pela ordem de
processamento —, senão a impressão não provaria nada: duas execuções que
processam os mesmos grupos em ordens diferentes precisam produzir a mesma
impressão.

Todo desempate termina no **id do provedor**, e é isso que torna a fusão
reproduzível: duas contribuições com a mesma precisão e a mesma qualidade
sairiam do banco em ordem arbitrária.

---

## Linhagem

```
Raw Dataset
   └── ResolutionRun        manifest_fingerprint fecha a entrada
        └── ResolutionDecision
             └── FusionGroup / fusion_group_records
                  └── FusedCandidate
                       └── fused_fields
                            └── fused_field_sources → record_ref
```

Navegável nos dois sentidos (§77): `fusion_run_inputs` liga a fusão às
execuções de resolução, e `fused_field_sources.record_ref` volta ao dataset,
arquivo e linha do arquivo bruto — que é imutável e continua lá (ADR-0014).

---

## O que este PR NÃO funde

- **eventos** — deduplicação profunda de eventos entre fontes exige matching
  próprio, com sua própria confiança e fila de revisão. Fica para PR
  posterior; aqui as observações de ambas as fontes seriam preservadas (§53);
- **qualidade final do dataset** — a qualidade das fontes entra como evidência
  da política de fusão; o cálculo global e a promoção são o PR-04 (§75).

---

## Limite

```
FUSED CANONICAL CANDIDATE  ≠  HISTORICAL_ACTIVE
FUSED CANONICAL CANDIDATE  ≠  MATCH STATE VECTOR
```

`assert_not_historical_active(candidate)` recusa sempre. Falta a avaliação de
qualidade e a construção canônica — o PR-04 — mais a barreira do ADR-0007.

---

## Leitura relacionada

- [`IDENTITY_RESOLUTION.md`](IDENTITY_RESOLUTION.md)
- [`../contracts/FUSION_OUTPUT_V1.md`](../contracts/FUSION_OUTPUT_V1.md)
- **ADR-0020** — fusão em nível de campo
- **ADR-0022** — resolução antes de fusão
