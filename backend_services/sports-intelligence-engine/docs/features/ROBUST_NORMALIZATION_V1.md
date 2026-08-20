# Normalização robusta — V1

> `(x - mediana) / IQR`, por competição, com ajuste **exato** e artefato
> identificável. Nenhum espaço de produção normalizado existe ainda.

---

## 1. O que este PR entrega — e o que não

```
ENTREGA    o runtime: população com digest, ajustador puro, artefato imutável,
           transformador
NÃO ENTREGA  qual população histórica usar, qual grade de cortes, qual divisão
           de treino e avaliação
```

Sem essas três decisões, «ajustar o normalizador» não tem população
cientificamente definida — e elas são o **PR-05.5**.

Por isso `MATCH_STATE_RAW_V2` continua **cru**: nenhuma definição declara
normalizador, e nenhum caminho do motor aplica um. A normalização é um
**segundo passo explícito**, e não um efeito colateral da extração.

---

## 2. Isto não é z-score

```
z-score          (x - média)  / desvio-padrão
robust scaling   (x - mediana) / IQR
```

O nome importa porque `z` carrega uma expectativa: média zero, desvio um,
distribuição aproximadamente normal. `(x - mediana) / IQR` não tem nenhuma das
três. Chamá-lo de z-score faria alguém aplicar a régua de três sigmas a uma
escala que não a sustenta.

O método declarado é `MEDIAN_IQR_ROBUST_SCALE_V1`, e o campo `method` viaja
dentro de cada valor produzido.

**Por que robusto e não z-score.** Futebol tem 7 a 1. Uma média e um
desvio-padrão sobre uma distribuição com cauda longa produzem uma escala onde a
partida atípica define o que é «normal».

---

## 3. O ajuste é EXATO

Nada de t-digest, GK ou mediana em fluxo. A população é ordenada e indexada:

```
tempo     O(N log N)
memória   O(N)
```

Isso é uma **decisão declarada**, não um descuido. Exatidão sobre uma população
arbitrária exige a população: não há como saber o valor do percentil 25 sem ter
visto todos os candidatos. Um esboço probabilístico resolveria a memória e
trocaria a identidade da escala por uma aproximação com erro dependente da
ordem de chegada.

**O ajuste é offline.** A memória é o recurso barato aqui. O dia em que não
for, a troca por um esboço será um método novo com versão nova — e não uma
otimização silenciosa.

O método de quantil é o mesmo do consenso de mercado:
`LINEAR_INTERPOLATED_QUANTILE_V1`, em `Decimal`.

---

## 4. A população

```
FeaturePopulation(competition_id, feature_key, observations)
FeatureObservation(match_id, as_of, value, corpus_fingerprint)
```

**A competição é do CONJUNTO**, e não de cada membro. Isso torna a regra de
escopo estrutural: uma população é de uma competição só, e misturar duas
exigiria construir duas e uni-las — o que o ajustador recusa.

**`value = None` é uma observação indisponível.** Ela entra na população —
porque a contagem total é auditável — e **não entra na distribuição**. O
artefato registra os dois números:

```
population_count   32    o total
available_count    30    os que formaram a distribuição
```

**Observação repetida é erro.** A mesma partida no mesmo corte entrando duas
vezes deslocaria a mediana em direção a ela sem que nada denunciasse. Ela não é
filtrada em silêncio.

**`corpus_fingerprint` entra na identidade.** O mesmo jogo no mesmo corte pode
ter valores diferentes em corpus diferentes — uma republicação corrige um
evento, e a feature muda. Dois ajustes sobre corpus diferentes não são o mesmo
ajuste.

### 4.1 O digest

`population_digest` é o SHA-256 da população canonizada e **ordenada**:

```
mesmos membros em ordem diferente   →  MESMO digest
um membro a mais                    →  outro digest
um valor diferente                  →  outro digest
outro corpus                        →  outro digest
```

A ordem é a canônica da observação — derivada do texto da identidade, e não da
ordem de leitura. `MatchId` e `FeatureAsOf` não têm ordem total, e nem
deveriam: «uma partida menor que outra» não significa nada.

---

## 5. O artefato

`NormalizerFitArtifact` é imutável e carrega tudo que explica os dois números:

```
feature       key + version + fingerprint
normalizer    key + fingerprint
população     competition_id + counts + digest
origem        corpus fingerprint + space fingerprint
corte         a forma canônica do fit cutoff
status        FITTED | INSUFFICIENT_SAMPLE | DEGENERATE_SCALE
parâmetros    median, q1, q3, iqr
```

**O que NÃO entra na identidade:** carimbo de criação, id de execução, id de
processo. Eles mudam entre dois ajustes do mesmo conteúdo, e um artefato que
mudasse de identidade por ter sido recalculado não serviria para comparar nada.

A impressão muda quando muda: a população, um único valor dela, a competição, o
corte de ajuste, ou o corpus de origem. Cada um desses tem um teste.

---

## 6. Os três estados do ajuste

Nenhum deles é exceção — os três são **resultados**.

### `FITTED`

Amostra suficiente e `IQR > 0`. A transformação funciona.

### `INSUFFICIENT_SAMPLE`

Menos observações disponíveis que o mínimo declarado. **A mediana não é
publicada**: calculá-la sobre uma amostra declarada inadequada seria produzir o
número e negar a própria política.

O mínimo é `30` por padrão, e vem da **declaração do normalizador**, não deste
código — `parameters["minimum_available_samples"]`. Trinta tem motivo: abaixo
disso o IQR de uma distribuição de futebol — assimétrica, com cauda — varia
mais entre amostras que entre competições, e a escala passa a descrever o acaso
da amostra em vez da liga.

### `DEGENERATE_SCALE`

Amostra suficiente e `IQR = 0`. **A mediana É publicada** — ela é observação
válida —, e a escala não existe.

---

## 7. IQR zero: sem epsilon, sem fallback

```python
scale = max(iqr, 1e-6)     # ❌ PROIBIDO
```

Isso faz o código parar de quebrar e **inventa uma escala**: uma distribuição
sem dispersão passa a produzir valores normalizados enormes, e eles parecem
sinal.

```python
if iqr == 0: usar mean/std   # ❌ PROIBIDO
```

Trocar de método sem versionar produziria dois significados sob o mesmo nome.

**O que acontece:** o artefato fica `DEGENERATE_SCALE`, a transformação devolve
indisponível com motivo, e o **valor cru continua válido**. Um normalizador que
não conseguiu normalizar não invalida o número: ele só não produziu o segundo.

Há um teste de arquitetura que falha se `epsilon`, `1e-6`, `max(iqr` ou
`stdev` aparecerem no **código** do pacote — a varredura ignora docstrings,
porque esta documentação cita cada um deles pelo nome.

---

## 8. A transformação

```
Normalized(x) = (x - mediana) / IQR
```

`NormalizedFeatureValue` carrega os três juntos:

```
raw                    o valor cru — ele continua sendo o fato
scaled                 o valor escalado — o que o modelo consome
artifact_fingerprint   a escala só significa algo junto com a população
```

**Normalizar não muta o cru.** A transformação produz um objeto novo; o
original é imutável e sobrevive. Isso não é formalidade: seis meses depois,
«este `+1,4` veio de que número?» tem resposta, e ela está no mesmo objeto.

### 8.1 As recusas

```
feature errada       LEVANTA — o artefato de shots_home_5m não normaliza xg_home_5m
competição errada    LEVANTA — o de Premier League não normaliza La Liga
```

As duas levantam em vez de devolver indisponível: são **defeito de quem
chamou**, e devolver `None` esconderia o defeito atrás de uma ausência que
parece normal. A comparação de feature é por **impressão**, e não por chave —
duas versões da mesma feature têm a mesma chave e escalas diferentes.

```
valor cru ausente    →  SOURCE_UNAVAILABLE   (não é defeito)
amostra insuficiente →  INSUFFICIENT_COVERAGE
dispersão nula       →  NOT_APPLICABLE
```

### 8.2 O que a transformação não faz

| ausente | por quê |
|---|---|
| clipping | se a conta dá `-12,4`, o valor é `-12,4` |
| winsorização | cortar caudas é decisão estatística própria |
| log | idem |

Um valor extremo é informação sobre a partida. Achatá-lo esconde exatamente o
que se quer detectar.

---

## 9. Escopo e corte

```
NormalizationScope.COMPETITION          ✅ a V1
NormalizationScope.GLOBAL               ❌ recusado na construção do ajustador
```

`GLOBAL` existe no catálogo **para ser recusado**. Ligas diferentes jogam
futebol diferente, e uma escala comum apaga justamente a diferença que se quer
medir.

O corte de ajuste é parte da **identidade** do normalizador (PR-05.1), e não um
parâmetro de execução. Dois ajustes com o mesmo método e a mesma população, um
até março e outro até maio, produzem escalas diferentes — se o corte fosse
parâmetro, os dois teriam a mesma impressão.

```
BEFORE_EVALUATED_MATCH   ✅ o padrão da V1 — causal
BEFORE_INSTANT           ✅ causal
FULL_POPULATION          ❌ recusado para espaço comparável ao vivo
```

---

## 10. Custo medido

```
população          100.000 valores (95.000 disponíveis)
duração do ajuste  ~4 s
throughput         ~24.000 valores/s
pico               ~136 MB
```

A memória é `O(N)` por decisão (seção 3). A impressão do artefato é O(1) — ela
é o hash de um documento com contagens e parâmetros, e não da população.

---

## 11. Documentos relacionados

- ADR-0035 — a decisão e as alternativas rejeitadas
- `NORMALIZATION_CONTRACT_V1.md` — a declaração (PR-05.1), que este PR executa
- `CANONICAL_MARKET_FEATURES_V1.md` — o mesmo método de quantil, outro uso
- `RAW_FEATURE_CATALOG_V2.md` — o espaço cru sobre o qual isto poderá operar
