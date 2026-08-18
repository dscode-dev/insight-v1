# Execução da qualidade histórica

> PR-04.2 · Fase 2 do PR-04 — **avaliar** e **gravar** o veredito.
> O corpus histórico publicável continua sendo o PR-04.3.

O PR-04.1 respondeu «o que é qualidade histórica». Este documento descreve o
que faltava: como esse veredito é **produzido sobre entrada real**, **gravado**
e **reproduzido meses depois sob a política que de fato o decidiu**.

---

## 1. O que a execução acrescenta ao veredito

```
MatchQualityAssessment      o VEREDITO — decidido pela política, e nada mais
      ↓ envolvido por
MatchQualityRecord          o veredito COMO ESTA EXECUÇÃO o produziu
      ↓ agrupado por
QualityRun                  sobre o quê, sob qual política, quando, por quem
```

**Por que um envelope e não campos a mais no veredito.** O assessment é a
resposta do domínio de qualidade; misturar nele o identificador de execução
faria o mesmo veredito, reavaliado sob política nova, precisar de outro objeto
para dizer a mesma coisa.

`MatchQualityRecord` acrescenta três coisas, e as três são de execução:

| campo | por quê |
|---|---|
| `quality_run_id` | em qual execução este veredito saiu |
| `fusion_group_id` | o elo da linhagem para trás — sem ele, ela se rompe no primeiro salto |
| `families_in_conflict` | famílias indecidíveis: **não** é defeito de qualidade, é insumo da política de build (§46) |
| `families_unresolved_identity` | o mesmo, para o §14: um jogador não resolvido afeta a escalação, não o núcleo |

---

## 2. `QualityRun` — ciclo de vida e imutabilidade

```
PENDING → RUNNING → COMPLETED
                  → COMPLETED_WITH_REVIEW
                  → FAILED
                  → CANCELLED
```

O status **sai das contagens**, não de um parâmetro. `review_required > 0`
leva a `COMPLETED_WITH_REVIEW` — os dois são sucesso, e a diferença é que o
segundo diz «nada a fazer» quando há partidas esperando uma decisão humana.

**Uma execução concluída é imutável.** `complete()` e `fail()` recusam com
`ConflictError`; no banco, o `UPDATE` é condicional a `status = 'RUNNING'`,
que é como esta base faz concorrência desde o PR-02. Dois workers fechando a
mesma execução produziriam duas contagens, e a segunda sobrescreveria a
primeira.

**As contagens precisam fechar.** `eligible + review_required + ineligible =
records_examined`, cobrado no domínio e repetido numa constraint — a diferença
silenciosa entre eles é onde um lote perdido se esconde.

---

## 3. A entrada: fusões concluídas, com impressão

```python
QualityRunInput(fusion_run_id=..., fusion_output_fingerprint=...)
```

O caso de uso recusa avaliar sobre uma fusão que não produziu saída utilizável
(`FAILED`, `CANCELLED`): ela pode ter processado metade dos grupos, e avaliar
metade produziria um veredito que parece completo e não é.

A impressão viaja junto porque **o id não basta**: a mesma fusão pode ter sido
relida antes e depois de alguém reprocessar a resolução, e é a impressão que
distingue os dois casos.

---

## 4. Versão **e** impressão da política

```
policy_version      1.0        o que a política DIZ que é
policy_fingerprint  sha256…    o que ela É
policy_snapshot     jsonb      a política inteira, por extenso
```

A versão pega a mudança declarada. A impressão pega a que ninguém declarou:
alguém edita um piso e esquece de subir o número, e as duas execuções ficam
rotuladas `1.0` decidindo diferente — «sob qual política esta partida
reprovou» passa a ter duas respostas com o mesmo nome.

O snapshot é o que faz «esta partida reprovou» ter a continuação «sob a
política que exigia identidade de jogador acima de 0,96», sem arqueologia.

---

## 5. O avaliador: observa, nunca decide

`HistoricalQualityAssessor` mede e entrega para
`MatchQualityAssessment.evaluate`. Nenhum limiar mora nele — um teste de
arquitetura procura comparações contra literais de ponto flutuante na faixa de
limiar e falha se encontrar.

### Os seis eixos, e como cada um é MEDIDO

| eixo | medida |
|---|---|
| `integrity` | binário: 0,0 se há identidade obrigatória ausente ou referência pendurada |
| `consistency` | fração dos campos de NÚCLEO (placar + horário) sem conflito |
| `completeness` | fração dos papéis de PLACAR presentes (`SCORE_ROLES`) |
| `identity_confidence` | o **elo mais fraco** das confianças por tipo — nunca a média |
| `temporal_integrity` | binário: 0,0 se há inconsistência temporal |
| `provenance_quality` | fração das contribuições com `record_ref`, zerada por linhagem quebrada |

**`consistency` conta só o núcleo, e a restrição é o §46 escrito no eixo.**
Contar todos os campos faria um conflito de formação num candidato de seis
campos dar 0,83 — abaixo do piso de 0,95 — e a partida inteira reprovaria por
causa de uma escalação indecidível. A escalação some; a partida fica.

### Cobertura: três estados, e o denominador honesto

| família | como sai | por quê |
|---|---|---|
| `MATCH` | `MEASURED` 1/1 | o candidato é a partida |
| `LINEUP` | `MEASURED` n/2 ou `NOT_DECLARED` | uma escalação por time é denominador honesto |
| `ODDS` | `AVAILABILITY_ONLY` | não existe «quantas casas deveriam ter cotado» |
| `PLAYER` | `AVAILABILITY_ONLY` ou `NOT_DECLARED` | contagem sem denominador |
| `EVENT`, `SPATIAL`, `TRACKING` | `NOT_DECLARED` | o contrato fundido da V1 não os carrega |

`NOT_DECLARED` **não** é `0%`. No banco, `expected_count` é `NULL` e uma
constraint impede `MEASURED` sem denominador — porque «a fonte prometeu e não
veio nada» e «a fonte não promete isso» exigem ações opostas.

### Licença por família: rótulo fora, fato dentro

> Fechado no PR-04.2.1. Ver §11 e `CANONICAL_BUILD_CORE.md` §11.

O mapa é construído das contribuições **factuais**. O que fica de fora são os
RÓTULOS de identidade — `HOME_TEAM_NAME`, `SEASON_LABEL`, ids de provedor:

1. **Rótulo não contamina.** O `Match` canônico não é construído a partir de
   `HOME_TEAM_NAME`; ele vem do registro, com identidade provada no PR-03.
   Contá-lo faria toda fonte de odds `RESEARCH_ONLY` restringir o núcleo por
   ter dito de que jogo se trata.
2. **Desacordo de grafia não é conflito.** `Man City` e `Manchester City` já
   terminaram no mesmo `TeamId`; absorver isso é o que a resolução existe para
   fazer.

**Mas o fato continua sujeito a procedência.** `KICKOFF`, `ROUND_NUMBER`,
`VENUE_NAME` e as observações AFIRMAM coisas, e quem as afirma é procedência
factual do núcleo. Se a única fonte que afirma que a partida existe é
`RESEARCH_ONLY`, o núcleo não vira comercialmente livre por os times já terem
id canônico.

**Confirmação não é derivação.** `independent_support` guarda as licenças das
fontes que sustentam a família sozinhas — `EXACT_AGREEMENT` e `MOST_COMPLETE`
sim, desempate não —, e é ela que impede uma fonte restrita que apenas
CONFIRMA um placar público de condenar o placar.

---

## 6. Persistência

```
quality_runs
 ├── quality_run_inputs              (fusão + impressão da saída)
 └── match_quality_assessments       (6 eixos em COLUNAS, não jsonb)
      ├── quality_assessment_coverage    (expected_count NULL-ável)
      ├── quality_assessment_licenses    (família → licença)
      ├── quality_assessment_identity    (tipo → confiança, nunca média)
      └── quality_assessment_issues      (código do catálogo + severidade da política)
```

**Colunas tipadas e não um blob (§57).** As seis dimensões são estáveis desde
o PR-04.1 e são consultadas — «quantas partidas reprovaram por identidade» é a
pergunta do relatório, e dentro de um `jsonb` ela exige varredura com extração
por linha.

**A severidade é gravada junto do problema.** Ela é da política e o
`QualityIssue` não a carrega; sem a coluna, contar bloqueantes exigiria
reaplicar sobre cada linha uma política que pode ter mudado.

**Nada aqui tem `UPDATE`** além de fechar a execução em curso. Um teste de
arquitetura lê o adapter e falha se aparecer.

---

## 7. Lotes, e o que a execução NÃO segura

O caso de uso recebe um iterador assíncrono de lotes de evidência. Dentro do
laço ele acumula **contagens** e uma **impressão** — nunca a lista de
vereditos. Um `list(assessments)` de dez mil partidas com vetor, cobertura,
licenças e problemas é o pico que o PR-03.2 mediu e corrigiu.

A impressão é **comutativa** (`SetFingerprint`, XOR sobre os digests), então
ela não depende de como os lotes foram particionados: duas execuções que
quebrem os mesmos candidatos em lotes diferentes produzem a mesma impressão.
O que ela custa está dito por extenso no módulo — XOR não é resistente a
colisão escolhida por adversário, e o modelo de ameaça aqui é «duas execuções
nossas produziram o mesmo conjunto?».

---

## 8. Reprocessamento

```
mesma fusão + política 1.0  →  QualityRun A   (fica)
mesma fusão + política 1.1  →  QualityRun B   (nova)
```

As duas coexistem, com os dois conjuntos de vereditos sobre as mesmas
partidas. A diferença entre elas é o que mostra o que a política nova passou a
enxergar — e se a nova pudesse reescrever a anterior, a comparação seria
contra si mesma.

---

## 9. Ator e trilha

```
ServiceActor("historical-quality-assessor")
```

Nunca `system`, `root` nem `admin` — numa trilha de auditoria eles significam
«não sabemos quem fez».

A trilha registra **início e fim da execução**, e não cada partida:
`match_quality_assessments` já é o registro por partida, e auditar cada uma
faria o volume da trilha ser governado pelo tamanho do corpus até ninguém
achar as decisões no meio.

---

## 10. O limite desta fase

Esta execução produz **vereditos**. Ela não constrói fato canônico nenhum —
isso é `CANONICAL_BUILD_CORE.md` — e não publica corpus nenhum, que é o
PR-04.3.

---

## 11. Integridade do repositório e do arnês

> Fechado no PR-04.2.1. Duas propriedades que não são do domínio e que a
> suíte verde não garantia.

### O artefato é o repositório

```
o working tree passar  ≠  o repositório ser válido
```

Uma regra `build/` sem barra inicial, no `.gitignore` do monorepo, excluía
`domain/build/` e `historical/build/`; `data/` excluía `docs/data/` inteiro.
Tudo passava — porque tudo lê o working tree —, e um `clone` não importava o
motor: o adapter commitado importava um pacote que não foi.

`tests/architecture/test_repository_integrity.py` protege em três camadas:

| camada | pergunta |
|---|---|
| `git check-ignore` | algum caminho essencial está ignorado? (ciente de negação) |
| `git ls-files` | «não ignorado» não implica «versionado» |
| árvore exportada | só o conteúdo versionado importa, do zero |

A terceira copia **apenas** o que `git ls-files` lista, e confere de onde o
módulo foi carregado — sem isso, o install editável resolveria de volta para o
working tree e a prova seria vazia.

`respect-gitignore = false` no Ruff fecha o ponto cego do lint: dois pacotes
inteiros passaram por «All checks passed» sem nunca terem sido lidos.

### Uma suíte de performance por banco

Duas suítes concorrentes sobre o mesmo PostgreSQL produziram
`ForeignKeyViolationError` — uma truncava as tabelas da outra no meio de um
lote. O motor estava certo; o arnês é que tinha estado mutável compartilhado, e
a falha se apresentou como regressão do produto.

`exclusividade_do_benchmark` é um lock consultivo (`pg_try_advisory_lock`) de
**sessão**, `autouse`. Ele serializa em vez de isolar por schema — um schema
por execução mudaria o que se mede — e **falha** com mensagem explícita em vez
de pular, porque uma suíte que «passa» sem medir é pior que uma que não roda.
