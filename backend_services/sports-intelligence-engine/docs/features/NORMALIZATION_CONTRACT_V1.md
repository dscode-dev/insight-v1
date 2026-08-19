# Contrato de normalização — V1

O que um normalizador declara antes de ajustar coisa nenhuma. Implementado em
**PR-05.1**.

> **Nenhum normalizador foi ajustado.** Não há z-score calculado, mediana,
> IQR nem parâmetro treinado. O que existe é a declaração — com identidade
> versionada e impressão — para que o ajuste, quando existir, não possa vazar
> em silêncio.

---

## As duas formas de vazamento

### 1. Escopo — normalizar ligas diferentes na mesma população

Premier League e Brasileirão têm distribuições diferentes de quase tudo:
finalizações, posse, faltas, ritmo. Uma escala comum faz um valor mediano de
uma parecer alto na outra.

```
NormalizationScope.COMPETITION          a decisão da V1
NormalizationScope.COMPETITION_SEASON   admissível
NormalizationScope.GLOBAL               existe no catálogo, e é RECUSADA
```

`GLOBAL` está nomeada de propósito: é o que permite recusá-la com mensagem, em
vez de não ter como expressá-la.

### 2. Corte de ajuste — usar maio para avaliar março

```
NormalizerFitData  ⊆  DataAllowedBeforeEvaluationCutoff
```

**Este é o mais traiçoeiro porque não aparece no valor.** `+0.3 desvio` parece
um número inocente, e a distribuição que o produziu já tinha visto o resto da
temporada. Nenhum teste sobre o valor o encontra; o único lugar onde ele é
visível é a identidade do normalizador.

```
FitCutoffKind.BEFORE_INSTANT           só dados anteriores ao instante
FitCutoffKind.BEFORE_EVALUATED_MATCH   só partidas anteriores à avaliada
FitCutoffKind.FULL_POPULATION          tudo — RETROSPECTIVO
```

---

## A identidade

```
NormalizerIdentity = key + version + impressão(método, escopo, corte, parâmetros)
```

**O corte é IDENTIDADE, e não parâmetro de execução.** Dois normalizadores com
o mesmo método e a mesma população, um ajustado até março e outro até maio,
produzem escalas diferentes para o mesmo valor. Se o corte fosse parâmetro, os
dois teriam a mesma impressão — e um `+0.3 desvio` de cada seria comparado como
se fosse a mesma medida.

---

## A guarda

```python
normalizer.assert_usable_for_live_comparable()
```

Ela exige as **duas** condições, e a mensagem diz qual falhou — porque as
correções são diferentes:

| falha | correção |
|-------|----------|
| corte retrospectivo | declarar um instante ou usar `BEFORE_EVALUATED_MATCH` |
| escopo global | escolher a competição |

---

## O normalizador de referência da V1

```
key        competition_median_iqr
method     MEDIAN_IQR
scope      COMPETITION
cutoff     BEFORE_EVALUATED_MATCH
```

**Mediana e IQR, e não média e desvio**: futebol tem 7 a 1. Uma medida sensível
a extremo faz um jogo atípico reescrever a escala de toda a competição.

Ele é **declarado, não ajustado**. Nenhuma estatística foi calculada.

---

## Normalizador congelado

Quando um normalizador for treinado sobre um corpus e congelado, ele declara:

```
fit_corpus_fingerprint   em QUE conteúdo foi ajustado
fit_cutoff               até quando ele enxergou
fingerprint              a identidade dele
```

Sem o primeiro, «este normalizador foi ajustado em quê?» deixa de ter resposta
no instante em que o corpus avança.

---

## O que NÃO existe aqui

```
z-score calculado          fase posterior
mediana/IQR ajustados      fase posterior
imputação                  §101 — nem média, nem zero, nem forward-fill
```

Qualquer imputação futura será **explícita e versionada**, e a procedência do
valor dirá `IMPUTED` — que é o que impede um valor preenchido de se passar por
observado.

---

## Relacionados

- [Modelo de vazamento temporal](TEMPORAL_LEAKAGE_MODEL.md) — o sétimo vazamento
- [Espaço de features](FEATURE_SPACE_V1.md)
- [Contrato de feature](FEATURE_CONTRACT_V1.md)
