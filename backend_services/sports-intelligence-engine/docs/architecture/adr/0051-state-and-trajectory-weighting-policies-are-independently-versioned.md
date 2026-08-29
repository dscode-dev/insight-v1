# ADR-0051 — As políticas de ponderação de estado e trajetória são versionadas de forma independente

**Estado:** aceito · **PR:** 06.5

## Contexto

O ADR-0050 fixou o núcleo `exp(-λd)`. Falta decidir `λ` — e decidir se ele é
**um** valor ou **dois**.

A resposta parece administrativa e não é. `λ` controla a concentração dos pesos,
e a concentração que um dado `λ` produz depende inteiramente da **escala das
distâncias** sobre as quais ele age. Estado e trajetória medem coisas
diferentes:

```
D    média da diferença de NÍVEL sobre m eixos                 (PR-06.2)
D_T  média da diferença de MOVIMENTO sobre n = 3m células      (PR-06.3)
```

Duas médias, sobre grandezas diferentes, com números de termos diferentes. Não
há razão a priori para que tenham o mesmo espalhamento — e a medição diz que
não têm.

## Como `λ` foi escolhido — e como não foi

**Só pela geometria do retrieval.** Nenhum rótulo de resultado, nenhum evento
futuro, nenhuma acurácia de previsão otimizada, nenhuma lente de inteligência
avaliada, nenhum ajuste supervisionado.

Isto não é escrúpulo: escolher `λ` porque ele «acerta mais gols» faria a
agregação deixar de ser uma transformação e passar a ser um modelo — não
declarado, não avaliado, e escondido dentro de uma constante.

Duas linhas de evidência independentes foram usadas, e **as duas convergiram**.

### Evidência A — o espalhamento local do top-K

Para que o vizinho mais distante do top-K receba `1/10` da massa do mais
próximo, é preciso `exp(λ · espalhamento) = 10`, ou seja
`λ = ln(10) / espalhamento`.

```
                espalhamento p50     λ para 10:1
ESTADO              0,2710              8,50
TRAJETÓRIA          0,1434             16,06
```

### Evidência B — a concentração sobre a população real

Varrendo `λ` sobre as distâncias reais e observando `N_eff`, peso máximo e massa
do topo:

```
                λ      N_eff p50 / K=20     peso máx     uniforme
ESTADO         8,0      12,34  (62% de K)     0,115        0,05
TRAJETÓRIA    16,0      13,66  (68% de K)     0,092        0,05
```

Os dois evitam os dois extremos que o contrato manda evitar: nem quase uniforme
(`λ = 0,25` dá `N_eff = 19,99`), nem dominado por um vizinho (`p10` fica em 8,24
e 8,25, muito acima de 1).

### O contrafactual — por que um `λ` só não serve

```
λ = 8 aplicado à TRAJETÓRIA  →  N_eff p50 = 16,50 / 20
```

Quase uniforme. O **mesmo número** produziria comportamentos agregativos
diferentes nos dois caminhos, por acidente de escala e não por decisão.

## Decisão

Manter duas políticas, com identidade e impressão próprias:

```
STATE_DISTANCE_WEIGHTING_V1         λ = 8,0
TRAJECTORY_DISTANCE_WEIGHTING_V1    λ = 16,0
```

A impressão de cada uma amarra: nome, versão, tipo de recuperação, núcleo, `λ`,
impressão da definição de distância, estratégia de normalização e fronteira
numérica.

`λ` participa da identidade semântica. Trocar `8,0` por `2,0` não é «afinar um
número»: é outra semântica de ponderação sobre exatamente os mesmos vizinhos, e
dois agregados sob `λ` diferentes não se comparam.

### A relação 2:1 é observação, e não regra

`λ_trajetória ≈ 2 × λ_estado` porque o espalhamento de trajetória é cerca de
metade do de estado. **Isso não cria a regra** `λ_T = 2 λ_S`. É evidência da
diferença de escala, e as duas políticas evoluem separadamente: mudar uma exige
nova versão, nova impressão e nova justificativa medida — e não arrasta a outra.

## Como a primeira grade quase produziu a resposta errada

A varredura inicial ia de `0,25` a `4,0` e mostrava `N_eff ≈ K` em toda ela. A
leitura fácil era «nenhum `λ` diferencia — a ponderação não ajuda aqui».

A leitura estava errada, e o que a desfez foi medir o **espalhamento** em vez de
olhar a tabela: com espalhamento mediano de `0,2710`, o `λ` necessário era
`8,50` — mais que o dobro do maior valor da grade. A grade é que não alcançava a
resposta. Escolher `4,0` por ser o maior valor presente teria sido escolher pelo
formato da grade, e não pelos dados.

## Consequências e limites conhecidos

**`λ` está congelado para a V1.** Novos sweeps para «melhorar números» são
proibidos. Qualquer mudança exige nova versão de política, nova impressão e nova
justificativa medida.

**O `λ` de trajetória repousa sobre uma população mais fraca que o de estado, e
isso está registrado.** No corpus de cenário usado para medir, o top-20 de
trajetória tem **3 valores de distância distintos** na mediana, contra 14 no de
estado — porque o gerador de cenário produz partidas a partir de três formas de
movimento, e trajetórias da mesma forma saem idênticas bit a bit.

A aritmética que produziu `λ = 16` está correta sobre a população medida. O que
não se pode afirmar é que essa população represente a geometria de trajetória em
produção. Registrado como `TRAJECTORY_CORPUS_DUPLICATE_DEGENERACY`, e detalhado
em `PR06_5_AGGREGATION_BASELINE.md`.

Isto **não reabre** a escolha — `λ = 16` permanece congelado — e **não é
bloqueador**: é a delimitação honesta do que a medição sustenta, e o gatilho
para revalidar quando houver corpus representativo.
