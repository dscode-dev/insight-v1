# A extração de features, passo a passo

> Como `FeatureSnapshot` sai do corpus publicado — e o que a extração
> deliberadamente não faz.

---

## 1. O pipeline

```
corpus publicado (versão READY)
      │
      ▼  5 consultas por LOTE — as MESMAS do PR-05.2
CanonicalMatchStateInput
      │
      ▼  EffectiveEventProjection            ← UMA vez, e só uma
ProjectionOutcome  ──┬────────────────────┐
                     │                    │
                     ▼                    │
        HistoricalMatchState               │
                     │                    │
                     └──────┬─────────────┘
                            ▼
            MatchFeatureExtractionContext
                            │
                            ▼  MatchStateFeatureExtractor (puro)
                     FeatureSnapshot
```

**A extração não acrescenta consulta nenhuma.** Ela consome o que a
reconstrução de estado já carregou. Uma consulta por feature daria 75 por corte
e 750.000 num lote de dez mil — e o benchmark afirma o número exato justamente
para que isso não apareça por acidente.

---

## 2. Uma projeção só

A invariante mais importante deste PR:

```
              ┌── HistoricalMatchState
EffectiveEventProjection(as_of) ──┤
              └── Rolling Feature Extraction
```

e **não**:

```
eventos ──┬── projeção A → estado
          └── projeção B → features
```

**Como isso é garantido estruturalmente.** `MatchStateBuildResult` carrega o
estado **e** a projeção que o produziu. `MatchFeatureExtractionContext.of()`
recebe esse resultado e nada mais — não há como montar um contexto com uma
projeção diferente da que o estado usou.

**Por que importa.** Duas projeções concordariam em todo caso fácil e
divergiriam no difícil — a correção cujo carimbo está na fronteira do corte. A
divergência apareceria como um estado que diz `1-1` ao lado de uma feature que
contou dois gols, e nada no resultado explicaria qual está certo.

---

## 3. As quatro conferências

`MatchFeatureExtractionContext` recusa combinações de artefatos
semanticamente diferentes:

| conferência | o que impede |
|---|---|
| mesma `match_id` | o estado de um jogo com os eventos de outro |
| mesmo `FeatureAsOf` | o estado dos 63' com a extração declarando 70' |
| mesmo corpus | o estado de uma versão com a origem de outra |
| mesma política temporal | um estado `AS_KNOWN` com extração retrospectiva |

Mais uma: o espaço e o catálogo precisam descrever **o mesmo conjunto na mesma
ordem**. O extrator usa o catálogo para saber **o que** calcular e o espaço para
saber **em que ordem** — os dois têm de concordar.

Sem essas conferências nada impediria alguém de passar objetos válidos que não
pertencem juntos: o cálculo terminaria, e o snapshot descreveria um jogo que
nunca existiu.

---

## 4. A ligação definição → cálculo é tipada

A forma barata seria olhar o nome:

```python
if key.startswith("shots_home_"):   # NÃO
```

Ela é frágil de um jeito específico: o dia em que alguém renomear uma chave, o
cálculo silenciosamente para de acontecer e a feature vira indisponível sem que
nada explique.

Aqui cada definição vem acompanhada de um **especificador**:

```python
RollingFeatureSpec(definition=…, family=SHOT, side=HOME, window=5m)
StateFeatureSpec(definition=…, kind=SCORE_HOME)
```

O extrator lê `spec.family`, `spec.side`, `spec.window` — três valores
tipados — em vez de decompor `"shots_on_target_diff_10m"` procurando
sublinhados.

---

## 5. Uma varredura, não sessenta

A forma ingênua — para cada feature, percorrer todos os eventos — custa
`O(E × F)`: com 400 eventos e 75 features são 30.000 comparações por corte, e
10.000 cortes fariam disso 300 milhões.

**O que a extração faz:**

```
1. percorre os eventos efetivos UMA vez
2. para cada um, calcula a distância até o corte no eixo local do período
3. as janelas são aninhadas e ordenadas: o conjunto que contém o evento é um
   SUFIXO da lista — uma busca binária acha onde ele começa
4. o evento é lançado nos baldes (janela, lado) de todas as janelas dali
5. as 75 features leem os baldes
```

Custo: `O(E × W + F)`, com `W = 4`.

Os baldes guardam **ids**, e não eventos: a procedência precisa das
referências, e manter os eventos inteiros multiplicaria a memória pelo número
de janelas em que cada um cabe.

**O que a extração não faz.** Não constrói array de todos os minutos da
partida, não mantém estado deslizante entre cortes, e não pré-computa nada. O
mesmo extrator funciona para um corte arbitrário — que é o requisito real,
porque os cortes vêm de fora.

---

## 6. Fail-closed

Quando o extrator não sabe se pode calcular, o resultado é **indisponível com
motivo tipado**. Nunca zero.

```
não publica EVENT               →  NOT_DECLARED
história de eventos incompleta  →  INSUFFICIENT_COVERAGE
período sem cronômetro          →  NOT_APPLICABLE
finalização sem ShotDetail      →  PARTIAL_INPUT
finalização sem xG              →  PARTIAL_INPUT
fato de time que não joga       →  PARTIAL_INPUT
componente de estado degradado  →  herda a disponibilidade do componente
```

**A degradação é local.** Um `xg_home_3m` `PARTIAL_INPUT` não derruba
`shots_home_3m`, nem `xg_home_1m` — apenas a janela e o lado atingidos.

**Um fato creditado a um time que não joga a partida** torna aquela família
daquela janela `PARTIAL_INPUT` nos dois lados: creditar ao acaso inventaria a
resposta, e ignorar em silêncio produziria uma contagem menor sem explicação.

---

## 7. Os casos de uso

```python
BuildHistoricalFeatureSnapshot     # uma partida, um corte
BuildHistoricalFeatureSnapshots    # muitas partidas, muitos cortes
```

Os dois compartilham o mesmo núcleo — ler, projetar, reduzir, extrair —
porque duas orquestrações divergiriam, e a divergência apareceria como «pelo
lote dá outro snapshot».

**Uma leitura por partida, N cortes.** Cinco cortes da mesma partida
reaproveitam o mesmo insumo dentro do lote. Recarregar por corte multiplicaria
as consultas por cinco sem trazer fato novo nenhum. O reaproveitamento é
**dentro da execução**, e não um cache: nada sobrevive ao fim do lote, porque
um cache persistente precisaria de invalidação quando o corpus fosse
republicado — decisão que não foi tomada.

**A saída em lote é limitada.** Dez mil snapshots de 75 features cada, todos
vivos numa lista, fariam o pico seguir o corpus. O que volta é:

```
built                   contagem exata
complete                quantos têm todas as dimensões
feature_values          total de valores produzidos
available_values        quantos deles existem
snapshots               AMOSTRA, com teto
sample_truncated        se a amostra não é o conjunto
unavailable_by_reason   diagnóstico agregado por motivo
```

---

## 8. O que a extração NÃO faz

| não faz | onde isso vive |
|---|---|
| reconstruir estado | `HistoricalMatchStateBuilder` — o estado chega pronto |
| reprojetar eventos | `EffectiveEventProjection` — a projeção chega pronta |
| ler o banco | a camada de aplicação |
| ler `MatchResult` | o estado o usa para conferência pós-jogo, e só |
| normalizar | nenhum PR executa normalizador ainda |
| imputar | indisponível continua indisponível |
| clipar ou transformar | nenhuma das duas |
| produzir vetor | a ordem do espaço basta; o vetor vem depois |
| calcular similaridade | PR-06 |
| persistir | o snapshot é reconstruído, como o estado (ADR-0031) |

Cada linha tem um teste de arquitetura que falha se ela deixar de valer.

---

## 9. Determinismo

```
mesmo corpus + mesmo estado + mesmos fatos efetivos + mesmo espaço
    ⇒ mesmo FeatureSnapshot
```

Entram na impressão: o corte, o espaço (nome, versão, impressão), a origem do
corpus, a política temporal, os valores e a procedência de cada feature.

**Não entram:** id de execução, carimbo de criação, id de processo, id de linha
de banco. Um snapshot que mudasse de identidade por ter sido calculado de novo
não serviria para comparar nada.

A ordem da entrada não importa: a projeção impõe a ordem canônica, e a seleção
de janela também. Provado por permutação exaustiva.

---

## 10. Documentos relacionados

- `RAW_FEATURE_CATALOG_V1.md` — as 75 features, uma a uma
- `ROLLING_WINDOW_SEMANTICS_V1.md` — a régua das janelas
- `HISTORICAL_MATCH_STATE_V1.md` — a entrada estrutural
- `MATCH_STATE_RECONSTRUCTION.md` — como o estado é reconstruído
- `TEMPORAL_LEAKAGE_MODEL.md` — o guarda que decide visibilidade
- ADR-0031, ADR-0032
