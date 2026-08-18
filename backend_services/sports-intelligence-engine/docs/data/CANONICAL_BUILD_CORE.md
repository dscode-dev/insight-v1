# Núcleo da construção canônica

> PR-04.2 · Fase 2 do PR-04 — transformar veredito em **fato canônico
> persistido**. O corpus histórico publicável é o PR-04.3, e continua fora.

---

## 1. A cadeia, e o lugar de cada peça

```
FusedMatchCandidate
      ↓  HistoricalQualityPolicy        (PR-04.1, executada no PR-04.2)
MatchQualityRecord            ← persistido, imutável
      ↓  CanonicalBuildPolicy           ← a ÚNICA que decide o build
BuildDecision                 ← por partida e por família
      ↓  construtores tipados           ← recusam sem decisão
Match · MatchResult · Lineup · OddsObservation
      ↓  CanonicalRegistryWritePort     ← equivalência antes de reuso
PostgreSQL
      ↓
CanonicalBuildRecord          ← linhagem, gravada DEPOIS da escrita
```

**O construtor não recalcula qualidade.** Ele recebe a `BuildDecision` pronta.
Um teste de arquitetura lê a árvore sintática e falha se a política de build
importar `QualityVector` ou chamar `minimum_for`, e se qualquer construtor
perder o parâmetro obrigatório `decision`.

---

## 2. `CanonicalBuildPolicy`

Versionada, com escopo, e é o único lugar com regra de build.

| campo | decide |
|---|---|
| `scope` | `RESEARCH` ou `COMMERCIAL` |
| `required_families` | sem uma delas, a partida **não** entra |
| `optional_families` | podem faltar sem derrubar nada |
| `license_droppable_families` | quais podem ser descartadas para contornar licença |
| `on_review_required` | `NEVER_BUILD` (default) ou `BUILD_CORE_ONLY` |
| `on_optional_conflict` | `EXCLUDE_FAMILY` (default) ou `REVIEW_FAMILY` |
| `require_result` | se a partida pode existir sem placar (§33) |

**A lista de descartáveis vem da política de QUALIDADE.** A política comercial
usa `DEFAULT_QUALITY_POLICY.commercially_droppable` — o mesmo objeto, não uma
cópia. Duas listas divergiriam no primeiro ajuste, e a divergência
significaria publicar comercialmente uma família que a qualidade considerava
restrita: o defeito mais caro deste PR, porque é jurídico e silencioso.

**Ela recusa exigir família que o contrato não carrega.** Uma política que
pedisse `EVENT` reprovaria o corpus inteiro por um limite NOSSO, e o relatório
culparia a fonte. `BUILDABLE_FAMILIES = {MATCH, LINEUP, ODDS}`.

### A ordem das guardas

```
1. avaliação INELIGIBLE            → SKIP,  famílias EXCLUDED(ASSESSMENT_INELIGIBLE)
2. avaliação REVIEW_REQUIRED       → conforme `on_review_required`
3. por família:
     não disponível                → EXCLUDED(NOT_AVAILABLE)
     licença não elegível          → descartável? EXCLUDED(LICENSE_POLICY) : bloqueia
     identidade não resolvida      → EXCLUDED(UNRESOLVED_IDENTITY)
     conflito não resolvido        → obrigatória? bloqueia : conforme política
     senão                         → INCLUDED
4. `require_result` e sem placar   → bloqueia
```

Quando algo bloqueia, **as decisões individuais sobrevivem** e as que iam
entrar viram `MATCH_NOT_BUILT`. Trocar todas por um motivo único apagaria a
informação mais útil da linha — qual família de fato falhou — justamente no
caso em que alguém vai procurar.

---

## 3. Pesquisa contra comércio

O cenário, montado pelo pipeline de verdade no teste de integração:

```
fonte pública    PUBLIC_DOMAIN    núcleo da partida e placar
fonte restrita   RESEARCH_ONLY    odds de duas casas
```

| | `MATCH` | `ODDS` |
|---|---|---|
| **research** | `INCLUDED` | `INCLUDED` |
| **commercial** | `INCLUDED` | `EXCLUDED` · `LICENSE_POLICY` · `RESEARCH_ONLY` |

**A identidade da partida é a MESMA nos dois.** O que muda é o conjunto de
famílias materializadas. As duas execuções coexistem, cada uma com a própria
linhagem, sobre a **mesma** `QualityRun`.

**A exclusão deixa rastro** em `canonical_build_family_decisions`, com motivo
do catálogo fechado e a licença que a causou. Uma constraint exige a licença
sempre que o motivo for `LICENSE_POLICY`.

---

## 4. Os construtores

| construtor | entrada tipada | recusa |
|---|---|---|
| `CanonicalMatchBuilder` | `MatchIdentityFacts` | identidade de outra partida |
| `CanonicalResultBuilder` | `ScoreFacts` | — devolve `None` se não há placar |
| `CanonicalLineupBuilder` | `LineupDraft` | jogador sem `PlayerId` canônico |
| `CanonicalOddsBuilder` | `ObservationSet` | — pula observação sem casa |

**Não há `CanonicalEventBuilder`,** e a ausência é declarada: nenhum
`SemanticRole` carrega evento, e um construtor que nunca recebe evento seria
dívida com aparência de cobertura. Um teste de arquitetura verifica que ele
não existe e que `EVENT` não está em `BUILDABLE_FAMILIES`.

### `Match` continua sem resultado

Verificado em três lugares: o agregado não tem os campos, o construtor de
partida não menciona `MatchResult` na árvore sintática, e `matches` não tem
coluna de placar no banco. O primeiro write real não desfaz a decisão central
do PR-01.

### Ausência é ausência

```
placar ausente     → MatchResult é None, NUNCA 0-0
meio placar        → `2-None` não é `2-0`
placar em conflito → a fusão não escolheu; escolher aqui seria decidir por ela
prorrogação        → None: não há papel semântico, e derivá-la inventaria um jogo
odds sem instante  → observed_at NULL, nunca o kickoff, nunca now()
```

### Odds: observações, nunca uma média

`Bet365 @ 2.00` e `Pinnacle @ 2.05` viram **duas** observações, e cada seleção
do mercado 1X2 vira uma linha — duas casas dão seis linhas. `2.025` é um preço
que casa nenhuma ofereceu.

A identidade da V1 é `(partida, casa, mercado, seleção, linha)`, exatamente a
que o PR-03.2 entregou. **O instante não entra nela**, e é o que faz reler o
mesmo arquivo produzir a mesma observação em vez de uma segunda.

`CanonicalOddsObservation` é um tipo próprio, ao lado de `OddsQuote`: aquele
exige `observed_at` e a exigência está certa para o caminho ao vivo; um
arquivo histórico não declara quando observou, e `None` é a resposta honesta.

---

## 5. A escrita canônica

`PostgresCanonicalRegistryWriter` nasce **ao lado** de
`PostgresCanonicalRegistry`, que continua sendo o leitor sem um único
`INSERT`. A separação é de responsabilidade e não de dado: as tabelas são as
mesmas da migration 0003, e não existe `canonical_matches_v2`.

Dar escrita ao leitor daria à RESOLUÇÃO a capacidade de criar entidade
canônica sem passar pela qualidade — era exatamente a porta que o PR-03 se
recusou a abrir.

### Três desfechos, e nenhum `UPDATE`

```
ausente                 INSERTED
presente e idêntico     REUSED_EQUIVALENT   ← nova linhagem, mesmo fato
presente e DIFERENTE    CONFLICT            ← nada escrito, alguém decide
```

`upsert` responderia «gravado» aos três, e o terceiro é aquele em que gravar é
o erro. A equivalência do `Match` é **estrutural** — competição, temporada,
times, horário marcado e fase; `lifecycle`, `venue` e `actual_kickoff` mudam
legitimamente entre execuções e ficam de fora, porque um conflito que sempre
dispara é um conflito que ninguém lê.

**Duas consultas por família, não duas por partida:** um `SELECT` de quem já
existia, o `INSERT` em bloco, e um `SELECT` de comparação.

---

## 6. `CanonicalBuildRun` e `CanonicalBuildRecord`

```
canonical_build_runs
 ├── canonical_build_run_inputs         (as fusões que alimentaram)
 ├── canonical_build_records            (um por FATO: MATCH, MATCH_RESULT, …)
 └── canonical_build_family_decisions   (um por FAMÍLIA, com motivo e licença)
```

Estados do registro: `BUILT`, `REUSED`, `SKIPPED`, `REVIEW_REQUIRED`, `FAILED`.
`REUSED` é distinto de `BUILT` porque «quantas partidas novas este build
trouxe» tem respostas diferentes nos dois casos.

**Um registro que afirma ter materializado precisa dizer o quê** — uma
constraint amarra `status ∈ {BUILT, REUSED}` a `fact_id IS NOT NULL`. Sem
isso, a travessia de linhagem termina num beco no primeiro salto.

**Um fato falhado impede declarar conclusão.** `records_failed > 0` leva a
`FAILED`, no domínio e numa constraint. Um corpus que perdeu partidas e
informa sucesso mente onde a mentira é mais cara: no número que alguém usa
para decidir publicar.

**A linhagem é gravada DEPOIS de a escrita voltar,** com o desfecho que ela
devolveu. Gravá-la antes afirmaria ter construído um fato que a transação
seguinte poderia não conseguir gravar.

---

## 7. A travessia completa

```
Match (matches.id)
  → canonical_build_records         (match_id, fact_type='MATCH')
  → match_quality_assessments       (quality_assessment_id)
  → fusion_groups                   (fusion_group_id)
  → fusion_group_records            (record_ref)
  → dataset_files                   (dataset:arquivo:linha)
  → object store                    SHA-256 do objeto bruto
```

Cada salto é uma junção, e o teste de integração percorre os seis contra
PostgreSQL e MinIO reais — terminando por reler o objeto e conferir o hash.

**O id do grupo de fusão precisa ser o que a fusão gravou.** Quem relê as
fontes para remontar os candidatos produz grupos com ids novos; a borda
realinha com `group_ids_of(fusion_run_id)` antes de avaliar. Sem isso o
`fusion_group_id` do veredito apontaria para um grupo que nunca foi
persistido, e a travessia terminaria num beco.

---

## 8. Lotes e transação

A unidade transacional é o **lote**, não a execução. Uma transação global
sobre dez mil partidas seguraria locks por minutos e refaria tudo por causa de
uma; uma por partida pagaria o custo de transação dez mil vezes.

Dentro do lote: duas leituras para N partidas (vereditos e identidades), uma
escrita por família, e a linhagem no fim — tudo na mesma transação, para que
uma falha não deixe `BuildRecord=BUILT` sem os fatos.

Medido em 4.000 partidas com lote de 500:

```
avaliação    56 consultas   (7,0 por lote · 0,014 por partida)
construção  120 consultas   (15,0 por lote · 0,030 por partida)
```

Com lote de 200 são 8 lotes e 56 consultas; com 800 são 2 lotes e 30. As
mesmas partidas. O custo cresce por **lote**.

---

## 9. Reprocessamento

```
QualityRun A + ResearchBuildPolicy    → BuildRun R
QualityRun A + CommercialBuildPolicy  → BuildRun C     (R fica intacta)
```

E um segundo build idêntico reaproveita os fatos e grava a própria linhagem:
**um** `Match` canônico, **duas** linhagens.

---

## 10. Onde esta fase para

O que sai daqui são **fatos canônicos persistidos** — não um corpus
publicável. Faltam a versão imutável do dataset, o manifesto, a impressão do
corpus, o Parquet e as interfaces. `assert_not_a_published_corpus` recusa
sempre, e existe para ser chamada por qualquer caminho que trate uma execução
de build como versão publicada do histórico.

**PR-04 continua bloqueado.**

---

## 11. Evidência de identidade não é procedência factual

> Fechado no PR-04.2.1. A regra tem dois lados, e generalizar qualquer um
> deles quebra o outro.

### O que é rótulo e o que é fato

| papel | classe | consequência |
|---|---|---|
| `HOME_TEAM_NAME`, `SEASON_LABEL`, `*_PROVIDER_ID` | **rótulo** | não vira conflito; não entra na pegada de licença |
| `KICKOFF`, `ROUND_NUMBER`, `VENUE_NAME` | **fato** | conflito real; é procedência factual do núcleo |
| `HOME_SCORE`, `ODDS_*`, `ATTENDANCE` | **fato** | idem |

`SemanticRole.is_identity_label` é o catálogo fechado, e ele decide duas
coisas caras: se um desacordo é conflito, e se uma licença restrita contamina
o fato canônico.

### Os três invariantes

```
RestrictedIdentityEvidence     ⇏  RestrictedCanonicalFact
    uma fonte RESEARCH_ONLY que só escreve `Man City` não restringe o núcleo

RestrictedOnlyFactualEvidence  ⇏  CommercialSafeFact
    mas se ela é a ÚNICA que afirma que a partida existe, o núcleo NÃO vira
    comercialmente livre por os times já terem id canônico

ResolvedIdentity               ⇏  IgnoreFactualProvenance
    resolver a identidade não apaga a pergunta «quem afirmou o fato»
```

### Confirmação não é derivação

`LicenseFootprint.independent_support` guarda as licenças das fontes que
sustentam a família **sozinhas**, e a regra vem da `FusionRule` que a fusão já
gravava:

| regra | suporte independente |
|---|---|
| `EXACT_AGREEMENT` | todas as contribuintes — o valor seria idêntico com qualquer uma |
| `MOST_COMPLETE` | a única contribuinte |
| desempate (`PREFERRED_SOURCE`, `HIGHEST_QUALITY`, `MOST_PRECISE`) | nenhuma — o valor foi produzido comparando as fontes |
| `CONFLICT_UNRESOLVED` | nenhuma — não há valor |

`family_verdict` pergunta primeiro «há fonte elegível que sustenta isto
sozinha?». Só quando não há é que vale a regra do conjunto, que é a mais
restritiva (§35 do PR-04.1, preservado).

A coluna `quality_assessment_licenses.independent` faz isso sobreviver ao
banco — sem ela, a política de build decidiria diferente depois de reler.

### Horário continua sendo fato

`KICKOFF` está em `CORE_ROLES`: duas fontes com 20:00 e 23:00 discordam de
verdade, e o conflito é bloqueante. A regra **não** é «papel de identidade
nunca participa de consistência» — é «rótulo não participa».

`SCORE_ROLES` (placar) é o subconjunto que decide se existe *resultado*;
`CORE_ROLES` acrescenta o horário e decide o que é conflito de núcleo.

---

## 12. Identidade de configuração

```
versão              a mudança declarada
impressão           a que ninguém declarou
```

`QualityRun` guarda as duas desde a 0005; `CanonicalBuildRun` passou a guardar
as duas na 0006. `policy_fingerprint` é uma função só, sobre `as_canonical()`,
com serialização determinística — nada de ordem de `dict`, `repr` ou endereço
de memória.

Pesquisa e comércio têm a **mesma versão** e impressões diferentes: sem a
impressão, os dois corpus seriam indistinguíveis pelos metadados gravados.
