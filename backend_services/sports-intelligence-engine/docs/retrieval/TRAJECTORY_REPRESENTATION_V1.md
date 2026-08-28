# `ROBUST_MULTI_HORIZON_DISPLACEMENT_TRAJECTORY_V1` — a representação

**PR:** 06.3 · **ADR:** [0045](../architecture/adr/0045-same-period-multi-horizon-displacement-trajectory.md)

> **ISTO NÃO É A SIMILARIDADE FINAL DO INSIGHT, e nem metade dela.** A
> trajetória é um sinal INDEPENDENTE do estado. Combiná-los é do PR-06.5.

## A representação errada, e por que ela é a óbvia

```
[ x(t-5), x(t-3), x(t-1), x(t) ]
```

Quatro cópias quase iguais do mesmo **nível**. Três quartos do vetor repetem o
que o estado já mede, e a distância resultante seria dominada pelo nível — o
PR-06.2 outra vez, com quatro vezes o custo.

## A representação deste PR

```
Δ_{h,i}(x) = x_i(t) − x_i(t−h)
```

«Quanto aquela dimensão se moveu nos últimos `h` minutos». O nível atual já
pertence à recuperação de estado; o que sobra aqui é o **movimento**.

### A ortogonalidade é por construção

```
A:  10 → 12        B:  20 → 22
níveis diferentes  ·  movimento IDÊNTICO (Δ = +2)
```

O estado separa os dois. A trajetória os reconhece como a mesma forma. **As
duas coisas estão certas**, e medem perguntas diferentes.

E o inverso:

```
query:        −2 → 0     Δ = +2
candidato A:  −2 → 0     Δ = +2     mesma direção
candidato B:  +2 → 0     Δ = −2     direção OPOSTA
```

O estado empata A e B — os dois estão em zero **agora**. A trajetória os separa,
e é exatamente para isso que o PR existe.

Verificado como golden: com `m = 5`, `D_T(q, A) = 0,0` e
`D_T(q, B) = 130/15 = 8,667`.

## A célula é `(horizonte, eixo)`

```
n = |H| · m = 3m
```

A ordem canônica é **horizonte primeiro**, eixo depois, e é a mesma na
impressão, na máscara, na evidência e na serialização:

```
perfil de 3 eixos, horizontes 1/3/5     →  9 posições
"111"  "111"  "000"                     →  o horizonte de 5 min está fora
```

### O denominador NÃO encolhe

Se um horizonte inteiro estiver fora do período, as `m` células dele ficam
indisponíveis e **continuam** no divisor:

```
remover o horizonte     uma trajetória com UM minuto de história pareceria
                        tão evidenciada quanto uma com cinco
manter no denominador   ela tem no máximo `2m/3m = 2/3` de cobertura
```

## A célula é utilizável quando

```
1. o slot `t-h` está estruturalmente disponível
2. a feature está AVAILABLE na ÂNCORA
3. a feature está AVAILABLE em `t-h`
4. os dois valores existem
5. os dois são `float64` finitos
```

**Os dois extremos são exigidos.** Um extremo só não produz meio deslocamento —
e usar o valor da âncora no lugar do que falta fabricaria `Δ = 0`, que é
estabilidade inventada.

Qualquer inconsistência entre máscara e valor **para a montagem**, como no
PR-06.2.

## Sem velocidade, e a decisão é deliberada

Não dividimos por `h`. O deslocamento preserva a unidade — desvios em IQR da
competição —, e é isso que mantém a penalidade `p = 1` interpretável: uma célula
ausente custa «um IQR de incerteza». `Δ/h` custaria «um IQR por minuto», que é
outra grandeza.

O catálogo `TrajectoryRepresentationMethod` tem **um** membro, e há teste de que
`VELOCITY`, `ACCELERATION` e `LEVEL_CONCATENATION` não estão nele.

## Os eixos são os do estado

```
Axes_trajectory = Axes_state-AA
```

O perfil de trajetória **compõe** o do PR-06.2 em vez de o substituir: `base` é
`ROBUST_AVAILABILITY_AWARE_EXACT_V1`, e é dele que saem os eixos. Não há segunda
seleção, logo não há como divergir da primeira — e `resolve()` recusa um perfil
resolvido que tenha vindo de outra regra.

Isso não é economia de digitação: é a condição para que a comparação entre
estado e trajetória meça **só a pergunta**.

As impressões dos dois perfis resolvidos são **diferentes**, e devem ser: os
números que eles produzem não se comparam.

## Os dois contratos

```
HistoricalTrajectory      a âncora, os slots e a linhagem
                          — quais INSTANTES a trajetória alcança
TrajectoryRepresentation  os deslocamentos sobre o perfil
                          — o que ela MEDE
```

A separação tem motivo: dois perfis diferentes sobre a mesma âncora alcançam os
**mesmos** instantes, e só depois divergem em quais eixos usam.

## A impressão

A da trajetória cobre âncora, política, e cada slot com o digesto da linha de
origem. A da representação cobre a trajetória inteira mais as células em ordem,
cada uma com disponibilidade e deslocamento canônico.

**E nenhuma das duas cobre** chave de objeto, grupo de linhas, ordem de leitura
ou carimbo de tempo. Duas gravações do mesmo conteúdo são a mesma trajetória.

## As duas invariantes centrais

### Imunidade ao futuro

Alterar `t+1`, `t+3` ou `t+5` **não muda nada**. Verificado da forma mais direta:
as linhas do futuro são construídas com valores absurdos e entregues ao montador
junto com as do passado; as impressões continuam idênticas.

E há três guardas estruturais: o catálogo de direção com um membro, a expressão
`anchor.minute - horizonte`, e o construtor que recusa alvo não anterior.

### Invariância de nível

```
(x_t + k) − (x_{t−h} + k)  =  x_t − x_{t−h}
```

Somar a mesma constante a todos os extremos não muda deslocamento nenhum.

**E a igualdade é EXATA quando as somas são exatas em `binary64`.** Com valores
diádicos — `8 + 2`, `0 + 2`, meios e quartos — os deslocamentos são idênticos
bit a bit e `D_T = 0`. Com valores quaisquer a propriedade vale a menos do
arredondamento, e o teste de propriedade a verifica assim, de propósito.

> Essa distinção não é pedantismo: a primeira versão do cenário interpolava com
> passos de `1/5` e produzia `D_T = 2,1e-31` em vez de zero. O número era um
> artefato do CENÁRIO, e não do motor — e um golden que o aceitasse com
> tolerância teria escondido a diferença entre os dois casos.
