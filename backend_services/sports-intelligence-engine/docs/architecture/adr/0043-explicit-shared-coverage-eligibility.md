# ADR-0043 — A elegibilidade é por cobertura compartilhada, com piso explícito

**Status:** aceito · **Data:** 2026-08-27

## Contexto

O PR-06.1 recusava o par inteiro quando UM eixo faltava (ADR-0042). Isso é o
mais restritivo que existe, e foi a decisão certa para um oráculo — mas o
PR-05.5.2 mediu que **40,7 % das células dos eixos robustos saem sem escala**, e
recusar todo par incompleto joga fora uma população grande de candidatos que
tinham dimensões em comum de sobra.

Afrouxar isso sem regra produz o defeito oposto, e ele é **pior**, porque não
falha: um candidato com UM eixo em comum, idêntico à query naquele eixo, teria
discrepância observada zero e ocuparia o primeiro lugar — por não ter sido
medido em mais nada.

    ausência não pode virar similaridade barata

A decisão que este ADR toma é sobre **quem pode ser comparado**. A decisão sobre
**como o número é calculado** é o [ADR-0044](0044-fixed-profile-iqr-missingness-penalty.md),
e as duas juntas formam o PR-06.2.

## Decisão

**A elegibilidade é decidida por uma política imutável, fechada e impressa:**

```
MINIMUM_EVIDENCE_COVERAGE_V1
```

### 1. O perfil é FIXO, e o denominador é ele

```
A = eixos do ResolvedRetrievalProfile        m = |A|
Q = { i ∈ A : q_i utilizável }
C = { i ∈ A : c_i utilizável }
S = Q ∩ C                                    s = |S|
```

**`Coverage_shared = s / m`, e nunca `s / |Q|` nem `s / |C|`.** Esta é a decisão
que impede a fraude aritmética: com denominador variável, um candidato com duas
dimensões teria `2/2 = 100 %` de cobertura e pareceria tão bem sustentado
quanto um com vinte.

**E O PERFIL NÃO ENCOLHE.** Nada de `profile = Q`, nada de `profile = Q ∩ C`. `S`
é uma **máscara de evidência**, e não um espaço de features novo. Reduzir o
perfil faria cada par medir uma grandeza diferente, e dois resultados deixariam
de ser comparáveis entre si sem que nada no objeto dissesse isso.

**Duas queries da mesma competição usam o MESMO perfil resolvido**, com
disponibilidades diferentes.

### 2. Os eixos são os mesmos do PR-06.1

`ResolvedAxes(ROBUST_COMPLETE_CASE_EXACT_BASELINE_V1)` e
`ResolvedAxes(ROBUST_AVAILABILITY_AWARE_EXACT_V1)` são **iguais**, para toda
competição — há teste de propriedade. A `axis_selection` é a mesma
(`ROBUST_FITTED`), e a única diferença entre os dois perfis é a
`missing_policy`.

Isso não é economia de digitação: é o que permite atribuir a diferença entre os
dois resultados à política de ausência, **e a nada mais**. Se os eixos também
mudassem, a comparação mediria duas coisas ao mesmo tempo.

As impressões dos dois perfis resolvidos são **diferentes**, e devem ser: os
números que eles produzem não se comparam.

### 3. O piso tem DUAS partes, e as duas são necessárias

```
piso ABSOLUTO      s ≥ 4
piso RELATIVO      5s ≥ 3m          (isto é, s/m ≥ 3/5)
```

Nenhum dos dois é redundante, e há teste para cada caso:

| caso | absoluto | relativo | resultado |
|---|---|---|---|
| `m = 4`, `s = 3` | recusa | admite (15 ≥ 12) | **recusado** |
| `m = 20`, `s = 4` | admite | recusa (20 < 60) | **recusado** |
| `m = 10`, `s = 6` | admite | admite (30 = 30) | admitido, no piso |

O absoluto impede comparação sobre três dimensões num perfil pequeno; o
relativo impede quatro dimensões de cem.

O mesmo par de pisos vale para a QUERY (`|Q|`), com tipo de erro próprio.

### 4. Os limiares são RACIONAIS, e o motivo não é um defeito medido

```
5 * s >= 3 * m        aritmética INTEIRA, em `int` de precisão arbitrária
```

**A justificativa fácil é falsa, e foi medida.** «`0.6` não existe em `float64`,
logo a comparação erra na fronteira» — não erra. Para todo `(s, m)` com `m` até
duzentos mil, e em três formulações naturais
(`s/m >= num/den`, `s >= (num/den)*m`, `(s*den)/m >= num`), sobre quatro pisos
diferentes, o resultado em ponto flutuante coincide com o exato **em todos os
casos**. Na fronteira, `s/m` e `num/den` são a mesma razão e arredondam para o
mesmo `float64`; fora dela, a distância entre os dois lados é ordens de grandeza
maior que o erro.

O motivo verdadeiro é de **contrato**: a comparação inteira é exata por
construção e não precisa desse argumento. A versão em `float` é correta **sob**
uma propriedade do arredondamento que teria de ser reestabelecida a cada
mudança de piso, de tamanho de perfil, ou de forma de escrever a comparação.

> Este é o mesmo padrão do `fsum` no ADR-0042: a razão fácil era falsa, e a
> razão verdadeira é não depender de um detalhe que hoje funciona. A medição
> que desmente a razão fácil ficou como teste.

**As frações continuam existindo** — `query_coverage`, `candidate_coverage`,
`shared_profile_coverage`, `shared_query_coverage` — e vão para o relatório. O
que elas não fazem é decidir.

### 5. O piso não cede

Se `m < minimum_profile_axes`, a **competição inteira** é recusada com
`PROFILE_INSUFFICIENT_EVIDENCE_AXES`. Não se baixa o mínimo até ela caber: um
piso que cede à pressão do dado não é piso, e a liga passaria a devolver top-K
sobre três dimensões com a mesma cara de um sobre trinta.

Se `|Q|` não alcança o piso, a query é recusada com
`QUERY_INSUFFICIENT_COVERAGE` — **antes de qualquer leitura de candidato**.

Se `s` não alcança o piso, o candidato **pertence ao universo**, é contado como
`INSUFFICIENT_SHARED_COVERAGE`, e não recebe distância.

## Consequências

**O universo não mudou.** `CandidateUniverse_PR06.1 == CandidateUniverse_PR06.2`
para a mesma query — mesma impressão, mesma contagem, mesmas identidades. A
política de candidatos é a mesma, e os dois caminhos leem pelo mesmo código
(`resolve_base` e `candidates`). Há teste E2E que compara as duas impressões.

**A atrição passou a ser aberta em TRÊS**, e não em duas:

```
coverage_eligible      recebeu distância
coverage_ineligible    está no universo e não alcançou o piso — NORMAL
structural_ineligible  mesma partida, representação divergente — NÃO deveria
```

Somá-las faria uma queda de integridade se disfarçar de ausência de dado. E a
ordem das perguntas é parte do contrato: o estrutural é perguntado **antes** da
cobertura, senão um defeito inflaria o número que este PR existe para medir.

**Um candidato quase vazio nunca ocupa o primeiro lugar**, e há sentinela: um
candidato com um eixo em comum, exato naquele eixo, é recusado antes de receber
distância.

**A pressão do piso é reportada, e não corrigida.** Quantos elegíveis e quantos
vizinhos do top-K estão exatamente na fronteira sai em todo benchmark. Se a
maioria estiver colada no mínimo, isso é sinal de que a política está operando
perto demais da ausência — e é para o humano decidir, não para um otimizador.

**O `3/5` NÃO foi escolhido por otimização**, e não poderia ter sido: não há
rótulo de verdade com que construir uma medida de acerto antes do PR-06.5.
Escolher o piso por otimizador produziria o valor que maximiza uma métrica
inventada. O estudo de sensibilidade percorre `1/2, 3/5, 2/3, 3/4, 1/1` e
**reporta**.

## Alternativas descartadas

**Manter o caso completo.** É a régua, e continua executável ao lado — mas como
política única ela descarta candidatos com dezenove de vinte dimensões em comum.

**Denominador na interseção.** Descrito acima: é a fraude aritmética que o
denominador fixo existe para impedir.

**Reduzir o perfil à query.** Cada query mediria uma grandeza diferente.

**Só o piso relativo, ou só o absoluto.** A tabela acima mostra um caso em que
cada um deles é o único a recusar.

**Um limiar em `float` (`0.6`).** Correto em tudo que foi medido, e correto por
um motivo que precisa ser reconferido a cada mudança.

**Escolher o piso por otimização.** Sem rótulo, não há o que otimizar.
