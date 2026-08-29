# Ponderação por distância — V1

> **O que este documento define:** como a dissimilaridade exata de um vizinho
> vira a massa relativa que ele carrega dentro do conjunto recuperado.
>
> **O que ele não define:** o que essa massa implica sobre a partida
> consultada. Isso é PR-06.6, e é outra camada.

## O núcleo

```
u_i = exp(-λ (d_i - d_min))

p_i = u_i / Σ_j u_j
```

`d_i` é a dissimilaridade **exata** produzida pelos recuperadores dos PRs
anteriores — `neighbor.dissimilarity` no estado, `trajectory_dissimilarity` na
trajetória. É a única entrada permitida.

Não entram: distância proxy, distância recalculada, função de distância nova,
multiplicador de cobertura, multiplicador de confiança, desfecho.

### Por que o deslocamento por `d_min`

É **estabilidade numérica, e não semântica**. O deslocamento cancela na razão:

```
exp(-λ(d_i - c))     exp(-λd_i) · exp(λc)     exp(-λd_i)
────────────────  =  ────────────────────  =  ──────────
Σ exp(-λ(d_j - c))   Σ exp(-λd_j) · exp(λc)   Σ exp(-λd_j)
```

O resultado é idêntico ao de `exp(-λd)` normalizado — mas o maior expoente vira
sempre `exp(0) = 1`, o que impede o subfluxo que `exp(-λd)` sofreria com `λ`
grande e `d` moderado.

A invariância vale **matematicamente**; em `float64` ela vale até a precisão
medida. Com `c = 0` o resultado é bit a bit idêntico; com `c = 1000` o erro
relativo medido chega a `6,8e-14`, e a tolerância declarada nos testes é
`rel = 1e-12`. Números medidos, e não arredondados para parecerem exatos.

## A fronteira numérica

```
IEEE754_FLOAT64_FSUM_V1
```

`binary64` em toda parte, e a soma por `math.fsum` — que é exata para a soma de
uma sequência de `float64`. Com `K = 1000` e pesos muito desiguais, a soma
ingênua acumularia erro justamente onde o denominador precisa ser confiável.

## As recusas

| Entrada | Comportamento |
|---|---|
| `d < 0` | recusada |
| `d = NaN` | recusada |
| `d = ±Inf` | recusada |
| `λ <= 0` | recusada |
| `λ = NaN` ou `±Inf` | recusada |
| vizinho repetido | recusado — a mesma partida receberia massa duas vezes |
| conjunto vazio | `NO_NEIGHBORS`, sem números fabricados |

`λ = 0` é recusado e não «tratado como uniforme»: com zero todos os pesos ficam
iguais, e aceitar isso calado faria a linha de base uniforme entrar por acidente
sob o nome da política exponencial. `λ < 0` é pior — o vizinho **mais distante**
passaria a pesar mais.

## O que o núcleo garante

```
Σ p_i = 1                              soma um (§33)
d_i < d_j  ⟹  p_i > p_j                monotonicidade (§34)
d_i = d_j  ⟹  p_i = p_j                empate (§35)
d'_i = d_i + c  ⟹  p' = p              invariância a deslocamento (§36)
p_i / p_j = exp(-λ(d_i - d_j))         a razão é o núcleo (§38)
λ ↑  ⟹  N_eff não aumenta              concentração (§37)
```

Todas varridas como propriedades sobre centenas de vetores gerados por semente
fixa, incluindo os casos que a aritmética odeia: todos iguais, diferenças de
`1e-15`, diferenças de `200`, um só elemento.

## As políticas

```
STATE_DISTANCE_WEIGHTING_V1         λ = 8,0     kernel EXPONENTIAL_KERNEL_V1
TRAJECTORY_DISTANCE_WEIGHTING_V1    λ = 16,0    kernel EXPONENTIAL_KERNEL_V1
UNIFORM_WEIGHTING_BASELINE_V1       λ = 0,0     só para goldens
```

A impressão de cada política amarra nome, versão, tipo de recuperação, núcleo,
`λ` (pelo `repr` do float, e não por formatação truncada), impressão da
definição de distância, normalização e fronteira numérica.

A **impressão da distância entra aqui** porque os pesos são função da
dissimilaridade, e a dissimilaridade é definida por uma régua com impressão
própria. Sem amarrá-la, dois agregados calculados sob réguas diferentes teriam a
mesma identidade de política.

A escolha de `λ` está no ADR-0051 e a medição em
`PR06_5_AGGREGATION_BASELINE.md`. `λ` está **congelado** para a V1.

### `λ` nunca é implícito

Não há `lam=1.0` num corpo de função em lugar nenhum. As fábricas
`state_weighting()` e `trajectory_weighting()` resolvem constantes **nomeadas e
documentadas** que entram na impressão — trocá-las muda a identidade da
política. Nenhuma execução pode esconder qual `λ` usou: a CLI o imprime, o
agregado o carrega, a impressão o amarra.

## O que a ponderação não faz

**Não fabrica diferença.** Ela amplifica diferenças que existem. Onde as
distâncias chegam iguais, os pesos saem iguais — para qualquer `λ`, inclusive
`1024`. Isso está medido, e é o assunto de
`TRAJECTORY_TOP5_GEOMETRIC_FLATNESS`.

**Não conta a cobertura duas vezes.** A distância exata já cobra a ausência. As
formas abaixo são proibidas:

```
peso = exp(-λd) × cobertura
peso = exp(-λd) × razão_de_eixos_compartilhados
```

**Não funde estado com trajetória.** Não há peso composto, `N_eff` composto nem
média ponderada dos dois. `D` e `D_T` são grandezas diferentes, e o catálogo
fechado de tipos faz a troca falhar alto em vez de sair calada.
