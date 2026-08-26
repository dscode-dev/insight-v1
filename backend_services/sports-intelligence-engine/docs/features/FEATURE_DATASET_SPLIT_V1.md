# `TEMPORAL_MATCH_ATOMIC_SPLIT_V1` — a divisão do dataset histórico

**Status:** vigente desde o PR-05.5.1 · ver ADR-0036

---

## 1. O defeito que esta política existe para impedir

A divisão óbvia é **sortear linhas**: 80% para uma metade, 20% para a outra.
Sobre um dataset de snapshots ela produz um vazamento perfeito e invisível:

```
o minuto 62 do jogo X  →  REFERENCE
o minuto 63 do jogo X  →  EVALUATION
```

As duas linhas descrevem quase o mesmo estado. A avaliação passa a medir a
capacidade de reencontrar um vizinho que é **literalmente o mesmo jogo um minuto
depois** — e o número que sai disso é excelente e não significa nada.

---

## 2. As duas regras

```
ATÔMICA POR PARTIDA   todas as 91 linhas de uma partida na mesma metade
TEMPORAL              a fronteira é um INSTANTE, e não uma proporção
```

**As duas são necessárias.** A atômica sozinha não basta: dois jogos da mesma
rodada, um em cada metade, ainda compartilham contexto de calendário e mercado
formado com a mesma informação. A temporal sozinha não basta: sem atomicidade,
um jogo que cruzasse a meia-noite da fronteira teria minutos dos dois lados.

---

## 3. A regra

```
REFERENCE    kickoff <  reference_end_exclusive
EVALUATION   kickoff >= reference_end_exclusive
```

O `kickoff` é o **pontapé canônico** — o mesmo que a grade usa
(`canonical_kickoff`). A fronteira é **exclusiva**: a partida exatamente nela cai
na avaliação.

A convenção é arbitrária como toda convenção de intervalo; o que importa é ela
ser **uma**, e estar escrita.

---

## 4. A fronteira é declarada, não derivada

`reference_end_exclusive` é um **instante que o operador declara**. Não existe
percentil, não existe proporção, e o tipo não tem onde guardá-las:

```python
FeatureDatasetSplitPolicy.__dataclass_fields__
# {"reference_end_exclusive", "name", "version"}
```

Um percentil faria a fronteira **mudar quando o corpus cresce** — e dois
datasets «80/20» construídos com um mês de diferença passariam a ter fronteiras
diferentes sob o mesmo nome. O instante é o que torna a divisão reproduzível.

Uma fronteira sem fuso horário é recusada: «01/06 às 00:00» é um instante
diferente em cada fuso, e a divisão mudaria conforme onde o build rodasse.

---

## 5. `REFERENCE` e não `TRAIN`

Nada é treinado aqui. A metade de referência é a **população que o motor
consulta** — a base de vizinhos, e a base sobre a qual escalas serão ajustadas
num PR futuro. `train` traria consigo a expectativa de gradiente, época e
validação, e nenhuma delas existe.

`DatasetSplit.REFERENCE.is_fittable` é `True`; `EVALUATION.is_fittable` é
`False`. A pergunta já tem resposta aqui para que o PR que ajusta normalizador
não precise reinventá-la.

**Não existem `VALIDATION` nem `TEST`.** Uma terceira metade exige uma segunda
fronteira e uma decisão sobre o que ela serve — as duas seriam inventadas aqui
sem que ninguém precisasse delas ainda.

---

## 6. As contagens

`SplitCounts` carrega, **contadas e nunca estimadas**:

```
reference_matches   evaluation_matches
reference_rows      evaluation_rows
```

Elas somam exatamente o total da versão, e o banco recusa a linha quando não
somam (`hfdv_metades_fecham`). Um dataset cuja avaliação ficou vazia porque a
fronteira caiu depois do último jogo é um erro que precisa ser **visível no
manifesto**, e não uma proporção plausível calculada de antemão.

---

## 7. A identidade

A política é impressa, e a impressão entra:

- na `FeatureDatasetSpec` da versão, junto com as da grade e do espaço;
- na **cadeia de impressão do conteúdo** — as mesmas linhas sob divisões
  diferentes produzem impressões diferentes, porque a metade é conteúdo da
  linha e não etiqueta do arquivo;
- na partição do object store: `split=REFERENCE/competition=…/season=…`.

A metade vem **primeiro** no caminho porque é o predicado mais grosso e o mais
usado: «a população de referência» tem de podar a avaliação inteira sem abrir
arquivo nenhum.

---

## 8. O que esta decisão NÃO fecha

Divisão por competição, validação cruzada temporal em janelas deslizantes e um
terceiro conjunto reservado continuam possíveis — cada um como política nova,
com nome e versão próprios.

---

## Referências

- ADR-0036 — grade e divisão são políticas versionadas
- `docs/features/SNAPSHOT_GRID_V1.md`
- `docs/features/HISTORICAL_FEATURE_DATASET_V1.md`
- `src/sports_intelligence/domain/features/dataset/split.py`
