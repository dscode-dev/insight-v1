# ADR-0038 — O plano de normalização é explícito e semântico, nunca inferido do tipo

**Status:** aceito · **Data:** 2026-08-25

## Contexto

O `MATCH_STATE_RAW_V2` tem 105 dimensões, e elas não estão na mesma unidade.
Uma distância que as some está somando gols com cotações com minutos.

A saída óbvia é normalizar. A pergunta que ninguém faz antes de normalizar é
**quais** dimensões, e a resposta natural — «as numéricas» — é falsa nesta base
de um jeito que não aparece em teste nenhum.

Considere duas colunas do mesmo arquivo, as duas `double`:

```
market_1x2_home_median      2.35     uma cotação
market_1x2_home_support        7     quantas casas de apostas publicaram
```

Uma regra por tipo — `if dtype == float: normalize()` — reescala as duas. O
resultado da segunda é um número perfeitamente plausível: `(7 - 6) / 2 = 0.5`.
Ele parece um sinal e é ruído com unidade apagada. Nada no arquivo denuncia, e
nenhuma leitura posterior consegue desfazer, porque a informação de que aquilo
era uma contagem se perdeu na transformação.

O mesmo vale para o relógio. `minute` é `int64` no arquivo e é uma
**coordenada**, não uma medida: a grade existe justamente para que «minuto 45»
signifique a mesma coisa em todas as competições. Reescalá-lo pela mediana da
liga faria o minuto 45 da Premier ser um número diferente do minuto 45 da La
Liga — e a comparação entre estados equivalentes deixaria de ser possível.

E o inverso também acontece. `shots_home_5m` é uma contagem, e o instinto de
«contagens não se normalizam» está certo aqui: numa janela de cinco minutos ela
vale 0, 1 ou 2 na esmagadora maioria dos cortes, e o IQR é frequentemente zero.
Mas `xg_home_5m` é contínuo, tem escala que varia de liga para liga, e É preciso
reescalá-lo.

Não existe regra sintática que acerte os quatro casos.

## Decisão

**A decisão de normalização é uma tabela EXPLÍCITA, com uma entrada por
dimensão, derivada dos METADADOS SEMÂNTICOS do catálogo — nunca do tipo do
dado.**

O plano é um objeto de domínio versionado e impresso:

```
MATCH_STATE_NORMALIZATION_PLAN_V1@1.0
105 eixos · 76 PASS_THROUGH_V1 · 29 ROBUST_MEDIAN_IQR_V1
```

Cada entrada carrega quatro coisas: a chave da feature, a **impressão** da
definição dela, a estratégia e a **razão**.

A razão não é documentação. Ela é um catálogo fechado de nove membros, e é o
que permite auditar a classificação sem reler o código:

| razão | estratégia | exemplo |
|---|---|---|
| `CONTINUOUS_COMPETITION_SCALED` | ROBUST | `xg_home_5m` |
| `SPARSE_DISCRETE_COUNT` | PASS_THROUGH | `shots_home_5m` |
| `MARKET_PRICE_LEVEL` | ROBUST | `market_1x2_home_median` |
| `MARKET_PRICE_DISPERSION` | ROBUST | `market_1x2_home_iqr` |
| `BOOKMAKER_SUPPORT_COUNT` | PASS_THROUGH | `market_1x2_home_support` |
| `CALENDAR_INTERVAL_HOURS` | ROBUST | `prev_kickoff_gap_hours` |
| `CALENDAR_MATCH_COUNT` | PASS_THROUGH | `matches_last_7d` |
| `CLOCK_COORDINATE` | PASS_THROUGH | `minute` |
| `STRUCTURAL_MATCH_STATE` | PASS_THROUGH | `red_cards_home` |

**A classificação é uma FUNÇÃO dos metadados, e não uma lista literal.** Uma
tabela escrita à mão com 105 linhas envelheceria em silêncio: a feature nova
entraria no espaço e ficaria de fora do plano. Aqui a classificação lê
`RollingFamily`, `ContextFeatureKind` e `MarketFeatureKind` do catálogo, e o
construtor **confere que o conjunto de chaves do plano é exatamente o conjunto
de chaves do espaço** — nem um a mais, nem um a menos.

**Só duas estratégias existem, e o catálogo é fechado.** `PASS_THROUGH_V1` e
`ROBUST_MEDIAN_IQR_V1`. Não há z-score, min-max, log, winsorização, clipping,
Box-Cox nem quantile transform — e a ausência é verificada por guarda
arquitetural, não por disciplina.

## Consequências

**O plano tem identidade, e ela inclui o corte do ajuste.** O plano de um
ajuste até junho não é o plano de um ajuste até agosto (PR-05.1 §89): as
decisões por eixo são as mesmas, e a escala que sai delas não é. Duas
representações sob planos de impressões diferentes **não são comparáveis**, e a
impressão é o que torna essa descoberta uma comparação de strings em vez de uma
arqueologia.

**O manifesto carrega o plano por extenso.** «Este eixo foi reescalado?» é a
primeira pergunta de quem lê o dataset seis meses depois, e a impressão só
responde «é o mesmo plano de antes» — o que não ajuda quem nunca viu o de antes.

**Uma feature nova quebra a construção em vez de passar despercebida.** Ela
entra no catálogo, o plano a classifica pelos metadados dela, e se os metadados
não permitirem classificá-la o construtor levanta. O caminho em que ela chegaria
ao dataset sem decisão nenhuma não existe.

**O custo é uma decisão a mais por feature nova.** Quem acrescenta um eixo tem
de dizer o que ele é — e é exatamente esse o ponto.

## Alternativas descartadas

**Normalizar tudo.** Reescala contagens esparsas cujo IQR é zero na maioria das
competições, e reescala o relógio. As duas produzem números plausíveis e sem
significado.

**Normalizar nada.** A distância soma unidades diferentes, e o eixo de maior
magnitude domina o resultado — `market_1x2_away_median` na casa de 10 apagaria
todo o resto.

**Decidir por `dtype`.** É o defeito descrito no contexto, e é o motivo desta
ADR existir.

**Aprender a normalização.** Uma normalização aprendida dos dados é um modelo, e
um modelo ajustado sobre o conjunto inteiro carrega o futuro dentro da escala.
Fora de escopo por causalidade, e não por complexidade.
