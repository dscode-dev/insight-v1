# Baseline da recuperação ciente de disponibilidade

Medido no **PR-06.2**, em **2026-08-27**. Este documento existe para que a
próxima execução tenha contra o que comparar, e **não** para declarar SLO.

---

## 1. O que estes números NÃO são

**Não são SLO** (§168). Força bruta offline não tem promessa de latência a
cumprir; ela é do caminho indexado, que é do PR-06.4.

**Não são o custo do insumo.** Corpus, dataset cru e normalização estão medidos
nos baselines do PR-05.

**Não são um resultado em escala de produção.** Noventa e seis partidas, uma
competição, uma temporada — ver §2.

**E a tabela de sensibilidade não escolhe nada** (§160, §162). Ela percorre cinco
pisos e **reporta**. Escolher um piso por otimização exigiria uma medida de
acerto, e não há rótulo de verdade com que construí-la antes do PR-06.5.

## O que eles afirmam

```
o universo é o MESMO do PR-06.1     mesma impressão, mesma contagem
a recuperação é POSITIVA            e o nome dela é «recuperação», não «ganho»
a memória segue o LOTE e o K        e não o universo
a atrição é aberta em TRÊS          cobertura, estrutura, elegíveis
o piso é tocado dos dois lados      há candidato acima, no piso, e abaixo
```

---

## 2. O cenário, e por que ele é o que é

```
partidas                 96
times                     6
chutes por time           4   por partida
cotações            2 casas   em dois terços das partidas
competições               1   Premier League
linhas do dataset     8.736   (4.277 referência + 4.459 avaliação)
perfil resolvido          6   eixos
universo por query       47   candidatos
```

**O cenário do PR-06.1 NÃO servia** (§146). Lá todo candidato tinha cobertura de
100 %: os oito eixos do perfil eram todos de xG em janela móvel, e a janela é
computável em todo corte de toda partida — ela vale zero quando não houve chute,
e zero é um valor medido. Um benchmark assim mediria latência e nada do que este
PR introduziu.

### A ausência veio do CONTEXTO, e não do mercado

A primeira hipótese foi o mercado, e ela **foi medida e desmentida**. O cenário
publica cotações de verdade — 72 observações canônicas chegam ao banco —, e todo
eixo de mercado continua saindo `INSUFFICIENT_SAMPLE` com `available_count = 0`.

```
uma cotação sem `observed_at`  →  FactKind.ODDS_CLOSING
                               →  TemporalAvailability.UNKNOWN
                               →  a guarda de vazamento recusa
                               →  TEMPORALLY_UNAVAILABLE em todo corte
```

E o caminho de ingestão **não tem papel semântico** para o carimbo de observação
de uma cotação — não há por onde declará-lo. Isto é o fail-closed do PR-05.1
funcionando, e significa que **a família de mercado é estruturalmente
indisponível de ponta a ponta hoje**: os catorze eixos de mercado
`INSUFFICIENT_SAMPLE` medidos no PR-05.5.2 não são artefato de corpus pequeno.

Há teste E2E que fixa esse comportamento.

A fonte que funciona é `ctx_same_comp_prev_gap_hours_*`: o gap até a partida
anterior não existe na estreia de um time na competição. Três mudanças foram
necessárias:

```
apitos IRREGULARES     sete dias fixos zeram o IQR do gap, e os três eixos de
                       contexto saem DEGENERATE_SCALE — indisponíveis para
                       TODO mundo, o que os tira do perfil
rodízio que GIRA       com `away = (i+1) % T` fixo, o visitante é sempre quem
                       estreia: `ctx_away` nunca tem observação
4 chutes, e não 10     ver a tabela abaixo
```

### A densidade de chutes, medida

```
10 chutes  ->  9 eixos de xG no perfil  ->  s >= 9 SEMPRE
 6 chutes  ->  5 eixos de xG            ->  s >= 5 sempre
 4 chutes  ->  3 eixos de xG            ->  s = 3, 4 ou 6
```

Só a última linha produz candidato abaixo do piso. Com xG computável em todo
corte, a fronteira só é alcançável quando os eixos de xG que cabem no perfil são
poucos o bastante.

**Isto não é fabricar ausência.** Uma liga real tem times estreando na competição
e partidas sem cotação; o cenário reproduz as duas coisas num corpus que cabe
num E2E.

---

## 3. Ambiente

```
CPU               Intel Core i9-14900KF · 32 threads
RAM               31 GB
SO                Windows 11 Pro (10.0.26200)
Python            3.14.6 (venv local)
PostgreSQL        17, em contêiner (porta 5433)
object store      sistema de arquivos local
memória medida    `tracemalloc` — alocação PYTHON, e não RSS
```

## 4. Configuração medida

```
política de candidatos  SAME_COMPETITION_REFERENCE_EXACT_TIMEPOINT_V1
perfil                  ROBUST_AVAILABILITY_AWARE_EXACT_V1
cobertura               MINIMUM_EVIDENCE_COVERAGE_V1  ·  3/5 e 4 eixos
distância               AVAILABILITY_AWARE_FIXED_PROFILE_IQR_PENALTY_V1
penalidade              p = 1  (IQR²)
denominador             FIXED_PROFILE_DENOMINATOR_V1
semântica float         IEEE754_FLOAT64_FSUM_V1
K                       10
```

Ajuste: **6 FITTED**, 9 `DEGENERATE_SCALE`, 14 `INSUFFICIENT_SAMPLE`.

Perfil resolvido: `xg_home_10m`, `xg_away_10m`, `xg_diff_10m`,
`ctx_same_comp_prev_gap_hours_{home,away,diff}`.

---

## 5. Uma query

```
competição              PREMIER_LEAGUE
instante                PRE_MATCH
universo                     47 candidatos
elegíveis                    46  (97,9 %)
sem cobertura                 1
estruturais                   0
K                          10/10
duração                   176,7 ms
memória                    13,3 MB
objetos lidos                 2
bytes lidos             883.399
```

## 6. Cem queries — as DUAS políticas por query

Cada iteração roda `CompareExactRetrievalPolicies`, que executa o caso completo
**e** a cobertura compartilhada sobre a MESMA leitura do universo. Os tempos
abaixo são desse par, e não de uma recuperação sozinha.

```
queries                    100
  comparáveis (AA)         100
  rejeitadas (AA)            0
  rejeitadas (CC)            0

p50                      303,3 ms
p95                      318,0 ms
p99                      330,4 ms
max                      330,4 ms
total                    48,30 s

memória do lote           13,7 MB
avaliações/s                 95
objetos lidos               840
bytes lidos         371.623.230
```

**A memória não cresce com o lote de queries**: 13,3 MB para uma, 13,7 MB para
cem — sobre um universo de 47 candidatos por query, com evidência montada para
`K = 10`. A alocação segue o lote e o `K`, e não o universo.

**371 MB lidos** é a dívida de releitura do PR-06.1, herdada e não resolvida
aqui por decisão (§118): não há cache, e o caminho exato continua sendo medido
sem atalho.

## 7. A recuperação de candidatos

```
universo somado          4.700
  caso completo          4.200
  ciente de disp.        4.600

recuperação absoluta      +400
recuperação relativa      +9,5 %
queries que saíam vazias      0
sem cobertura (somado)      100
estruturais (somado)          0
```

**«Recuperação», e não «melhoria»** (§77). Quatrocentos candidatos a mais
receberam distância. Isso **não** é o mesmo que quatrocentos vizinhos melhores —
não há rótulo de verdade com que afirmar a segunda coisa, e não haverá antes do
PR-06.5.

**Nenhuma query saiu do zero** neste cenário: o caso completo já devolvia
vizinhos para todas as cem. Num corpus com mais ausência isso mudaria, e o
número existe para ser comparado quando mudar.

## 8. As coberturas

```
query                min 1,00   p10 1,00   p50 1,00   p90 1,00   max 1,00   (n=100)
universo (pares)     min 0,50   p10 0,67   p50 1,00   p90 1,00   max 1,00   (n=940)
elegíveis            min 0,67   p10 1,00   p50 1,00   p90 1,00   max 1,00   (n=920)
top-K                min 0,67   p10 1,00   p50 1,00   p90 1,00   max 1,00   (n=1.000)
```

A cauda inferior do universo (`0,50`) é recusada pelo piso, e a dos elegíveis
começa em `0,67` — que é `4/6`, exatamente o mínimo absoluto.

## 9. A pressão do piso

```
elegíveis no piso        80 de 920    (8,7 %)
vizinhos no piso         18 de 1.000  (1,8 %)
```

**A leitura importa** (§157). Menos de dois por cento do top-K está colado na
fronteira, e a mediana da cobertura do top-K é 100 %. O ranking **não** está
sendo dominado pelo mínimo — se estivesse, seria sinal de que a política opera
perto demais da ausência, e a resposta seria reportar, não corrigir
automaticamente.

## 10. Observado contra incerteza

```
observado            min 0,00   p10 0,00   p50 0,13   p90 4,32   max 33,05  (n=1.000)
incerteza            min 0,00   p10 0,00   p50 0,00   p90 0,00   max 2,00   (n=1.000)
fração incerta       min 0,00   p10 0,00   p50 0,00   p90 0,00   max 0,94   (n=890)
```

A mediana da incerteza é **zero**: o vizinho típico deste cenário é de caso
completo. A cauda superior — `0,94` — é o vizinho cuja posição é quase toda
suposição, e é exatamente o número que o PR-06.7 vai precisar para não tratá-lo
como igual a um de 5 %.

## 11. A sobreposição com o caso completo

```
top-K comum          min 0,80   p10 0,90   p50 1,00   p90 1,00   max 1,00   (n=100)
```

**DIAGNÓSTICO, e não métrica de correção** (§78). Uma sobreposição baixa é o
comportamento **pretendido**: significa que a política de ausência trouxe
candidatos que o caso completo não podia ver. O número descreve quanto os dois
rankings se afastam, e não decide qual está certo.

## 12. A sensibilidade ao piso

| piso | queries | eleg. p10 | eleg. p50 | zeradas | cob. do K p50 |
|---|---|---|---|---|---|
| `1/2` | 30/30 | 46,0 | 46,0 | 0 | 100 % |
| **`3/5` ← V1** | **30/30** | **46,0** | **46,0** | **0** | **100 %** |
| `2/3` | 30/30 | 46,0 | 46,0 | 0 | 100 % |
| `3/4` | 30/30 | 42,0 | 42,0 | 0 | 100 % |
| `1/1` | 30/30 | 42,0 | 42,0 | 0 | 100 % |

**Neste cenário o `3/5` não é apertado nem frouxo**, e a razão é a granularidade:
com `m = 6`, os valores possíveis de `s` são poucos, e `1/2`, `3/5` e `2/3`
caem todos entre `s = 3` e `s = 4`. A diferença aparece em `3/4`, que passa a
exigir `s ≥ 5` e recusa mais quatro candidatos por query.

**Nenhuma query fica sem resposta em piso nenhum**, inclusive no caso completo
(`1/1`) — o cenário tem candidatos completos de sobra.

**A decisão fica em `3/5`** (§160). Ele não é patologicamente inviável — a taxa
de comparabilidade é 100 % —, e não há evidência de blocker operacional que
justifique mexer. Um corpus com mais ausência é o que vai testar essa escolha de
verdade.

## 13. A identidade

```
perfil          9e4f97e002bd7a25…
cobertura       ed825ca38fc24ce5…
distância       ab160a011cc4f28f…
universo        d12b73fa4608b225…
resultado       e05c8c822fb75cf5…
```

Duas execuções da mesma query produzem a mesma impressão de resultado **e** as
mesmas impressões de evidência — medido no benchmark e no E2E.

## 14. O custo de recusar uma query

```
                        recusa   só a query   varredura
objetos lidos                1            1           2
bytes lidos            182.591      182.591     353.510
duração                 43,3 ms
```

**A recusa custa exatamente o que custa achar a query, e nada além.**

Isso **não** saiu de graça, e o benchmark é quem encontrou o defeito. A primeira
versão do caso de uso escrevia:

```python
return retriever.retrieve(
    ...,
    candidates=await self.exact.candidates(contexto.resolution, batch_rows),
)
```

O argumento é avaliado **antes** da chamada, então a query incomparável pagava o
universo inteiro em objetos e bytes para só depois ser recusada. Medido: recusa
lendo 2 objetos e 353.510 bytes — exatamente o mesmo que a varredura completa.

A correção foi mover a conferência para antes da leitura
(`assert_query_admissible`), mantendo-a também dentro de `retrieve` como defesa
em profundidade para quem usar o domínio direto.

---

## 15. O que este baseline NÃO mede

- **escala de produção.** 96 partidas, 1 competição, 1 temporada.
- **múltiplas competições.** O §149 pede as cinco quando o corpus as tiver; este
  não tem, e misturá-las no universo é proibido de qualquer forma.
- **ausência de mercado.** Ela é estruturalmente inalcançável hoje — ver §2.
- **outra máquina.** Ver §3.
- **o caminho indexado.** É do PR-06.4, e é ele que terá SLO.
- **`Recall@K`.** Não há índice aproximado contra o que medir.

## 16. As dívidas de escala medidas

**A releitura por query (herdada do PR-06.1).** 371 MB para cem queries. Sem
cache, por decisão (§118). As saídas — cache de partição, reparticionamento por
instante, índice — são do PR-06.4.

**A busca da query por varredura (herdada do PR-06.1).** `load_query` varre a
metade de avaliação até achar a chave: 1 objeto e 182.591 bytes neste corpus.
Ela agora tem um segundo consumidor — a recusa por cobertura da query paga esse
custo e mais nada —, o que a torna o piso de latência do caminho barato.

**A latência do par de políticas.** 303 ms de p50 medem as DUAS recuperações
sobre a mesma leitura. Separá-las não é otimização pendente: a comparação existe
para rodar as duas juntas, e medi-las em execuções separadas é o que tornaria a
diferença não atribuível.

**A granularidade do piso num perfil pequeno.** Com `m = 6`, três pisos
diferentes produzem a mesma decisão. Isso não é defeito da política — é o perfil
que é pequeno —, e um corpus em que a família de mercado esteja disponível daria
`m` na casa das duas dezenas, onde os pisos se separam.
