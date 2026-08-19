# Espaço de features — V1

Um conjunto **ordenado** e versionado de features compatíveis, e a identidade
dele. Implementado em **PR-05.1**.

> **Nenhum espaço de produção existe ainda.** `match-state-core` chega quando
> houver features reais. O que existe é o contrato — e um espaço de teste, que
> vive nos testes.

---

## A ordem é conteúdo

```
[f1, f2, f3]   ≠   [f3, f1, f2]
```

Um `FeatureSpace` vira, adiante, um vetor. Os mesmos números em eixos
diferentes produzem distâncias que **não falham, só mentem**: a aritmética
funciona, o resultado é um número, e ele compara dimensões trocadas.

Por isso a ordem entra na impressão:

```
FeatureSpaceIdentity = nome + versão + impressão(ordem + conteúdo)
```

---

## O que o construtor recusa

| recusa | por que ela existe |
|--------|--------------------|
| chave repetida | uma das duas seria ignorada, e ninguém saberia qual |
| `live_comparable` + `CANONICAL_FINAL` | a promessa e o modo se contradizem (ADR-0029) |
| feature `POST_MATCH` num espaço ao vivo | ela não existe enquanto a partida acontece |
| dependência ausente | feature apontando para o vazio |
| ciclo `A → B → A` | e a mensagem traz o CAMINHO, não só «há um ciclo» |
| exigência de corpus não declarada | a incompatibilidade só apareceria no meio do cálculo |

**A segunda é estrutural, e é o ponto** (§80): a combinação inválida não é
recusada na revisão de código nem no cálculo — ela **não constrói**. Deixá-la
para a disciplina seria confiar que ninguém escreve a linha errada às onze da
noite.

---

## `live_comparable`

```python
live_comparable = True
```

significa: **todos os valores deste espaço são computáveis com a informação
disponível causalmente no momento equivalente de uma partida ao vivo.**

```
HistoricalFeature_t  ~  InformationAvailableLive_t
```

Um espaço que não faz essa promessa é legítimo — auditoria e análise
retrospectiva precisam dele. O que não pode é um espaço fazer a promessa e usar
verdade retrospectiva.

---

## Compatibilidade com o corpus

```python
requirement = CorpusRequirement.of(CoverageFamily.EVENT, CoverageFamily.ODDS)
```

```
requires EVENT   ⇒   a VERSÃO do corpus precisa DECLARAR a família
                 ⇏   toda partida tem eventos
```

A distinção é o §58 inteiro. A exigência é conferida **antes** de compor —
descobrir na décima milésima partida que o corpus não publica eventos custa a
composição inteira. A disponibilidade por partida continua sendo decidida
partida a partida, e vira `NOT_DECLARED` ou `INSUFFICIENT_COVERAGE` no valor.

---

## O snapshot

```
FeatureSnapshot   ≠   MatchStateVector
```

O nome importa: um vetor é uma lista de números com dimensões fixas; um
snapshot é o RESULTADO de um cálculo, com máscara, procedência e identidade
temporal. O vetor sai do snapshot quando as features reais existirem.

### A identidade semântica

```
SameCorpus + SameFeatureSpace + SameAsOf + SameTemporalPolicy
    ⇒  SameFeatureSnapshot
```

Os quatro entram na impressão:

| entra | porque |
|-------|--------|
| impressão do corpus | corpus diferente, conteúdo diferente |
| impressão do espaço | eixos diferentes |
| impressão da política temporal | causalidade diferente |
| o `as-of` | 62' e 63' são estados diferentes |

**Não entra** nada que mude entre duas execuções idênticas: id de execução,
carimbo de criação, id de processo, id de linha. Um snapshot que mudasse de
identidade por ter sido recalculado não serviria para comparar nada.

### O que ele verifica ao ser construído

- a ordem das features é **exatamente** a do espaço;
- cada valor foi calculado sob a **impressão** da definição que o espaço
  declara — mesmo nome com impressão diferente é recusado;
- todos os valores são do **mesmo corte**.

---

## O registro

`FeatureDefinitionRegistry` é declarativo e em memória (§107, §121): um
catálogo em PostgreSQL responderia «quais features existem» de um jeito que o
código-fonte já responde, e acrescentaria um estado que pode divergir do
código.

Ele recusa: chave/versão repetidas, identidade repetida, **mesma chave/versão
com impressão diferente**, dependência inexistente e ciclo.

A terceira é a pior: alguém mudou a semântica e manteve o nome. O número muda e
o histórico não sabe.

---

## Relacionados

- [ADR-0030 — features e espaços são contratos versionados](../architecture/adr/0030-feature-definitions-and-spaces-are-versioned-contracts.md)
- [Contrato de feature](FEATURE_CONTRACT_V1.md)
- [Contrato de normalização](NORMALIZATION_CONTRACT_V1.md)
