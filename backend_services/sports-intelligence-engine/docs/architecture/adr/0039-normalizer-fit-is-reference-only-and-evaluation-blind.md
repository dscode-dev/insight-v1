# ADR-0039 — O ajuste do normalizador é só sobre REFERÊNCIA, e cego para a AVALIAÇÃO

**Status:** aceito · **Data:** 2026-08-25

## Contexto

O ADR-0036 dividiu o dataset em duas metades por uma fronteira temporal, atômica
por partida: toda linha de uma partida iniciada antes de
`reference_end_exclusive` é REFERÊNCIA; toda linha de uma partida iniciada em ou
depois é AVALIAÇÃO.

A divisão existe para uma coisa só: permitir avaliar o motor sobre partidas que
ele não usou para se calibrar. Ela é inútil se qualquer coisa da avaliação
vazar para a base de comparação.

O vazamento óbvio é ajustar sobre as duas metades. Ele é fácil de evitar e fácil
de testar.

**O vazamento que este ADR existe para impedir é outro, e ele não muda número
nenhum.** Considere um conjunto de artefatos cuja identidade inclua a impressão
de conteúdo do dataset cru:

```
raw_content_fingerprint      cobre REFERÊNCIA + AVALIAÇÃO
```

Acrescentar uma partida à avaliação muda essa impressão. As medianas continuam
idênticas — nenhuma observação nova entrou no ajuste —, mas o **conjunto de
artefatos passa a ter outra identidade**. E aí:

- «Estas duas versões normalizadas usam a mesma escala?» responde «não».
- Reajustar «porque o ajuste mudou» produz os mesmos números com outro id.
- A afirmação «a base de comparação não mudou entre estas duas publicações»
  deixa de ser verificável, porque a única impressão disponível mudou.

O defeito não produz um valor errado. Ele destrói a capacidade de AFIRMAR que
nada mudou — que é exatamente o que a divisão foi criada para permitir.

Há uma terceira forma, mais fina. Se a identidade do ajuste depender de um
agregado GLOBAL da referência, mexer na La Liga muda os artefatos da Premier
League. Nenhum número da Premier mudou; a identidade deles, sim.

## Decisão

**Nada que a AVALIAÇÃO toca entra na identidade de artefato nenhum. Nada que
OUTRA COMPETIÇÃO toca entra na identidade do pacote de uma competição.**

Formalmente:

```
FitPopulation ⊆ REFERENCE                  por construção, não por conferência
∂ ArtifactSet / ∂ EVALUATION  =  0
∂ Bundle(C)   / ∂ REFERENCE(C')  =  0      para todo C' ≠ C
```

Três decisões concretas sustentam isso, e errar em qualquer uma delas quebra a
invariante sem produzir número errado:

**1. Existe uma impressão de conteúdo só da REFERÊNCIA.**

```
raw_content_fingerprint                       REFERÊNCIA + AVALIAÇÃO   ← linhagem
reference_content_fingerprint                 só REFERÊNCIA            ← identidade
competition_reference_content_fingerprint(C)  só REFERÊNCIA, só C      ← pacote
```

Ela é calculada DURANTE a varredura do ajuste, e não numa passagem extra: o
ajuste já lê exatamente as linhas de referência.

**2. O `source_corpus_fingerprint` de cada artefato é a impressão da referência
DAQUELA COMPETIÇÃO.** Essa escolha tira a avaliação e as outras competições da
identidade do artefato de uma vez só.

**3. O corte do normalizador é `BEFORE_INSTANT(reference_end_exclusive)`, e não
`BEFORE_EVALUATED_MATCH`.** O segundo é o contrato do caminho AO VIVO, onde
«antes desta partida» é conhecível. Para o dataset ele seria N ajustes para N
partidas, e — mais importante — deixaria o ajuste da última partida da avaliação
enxergar as anteriores DA AVALIAÇÃO. O corte na fronteira não deixa nenhuma
linha de avaliação entrar em ajuste nenhum.

**A linhagem continua persistida, e é separada da identidade.** O
`NormalizerArtifactSet` carrega `source_version_id` e
`source_raw_content_fingerprint` num método `lineage()` próprio, fora de
`as_canonical()`. Linhagem responde «de onde veio»; identidade responde «é o
mesmo ajuste».

## Consequências

**A invariante é demonstrável, e é demonstrada.** Dois cenários com a mesma
REFERÊNCIA e avaliações diferentes — em tamanho e em valores — produzem
impressão de referência, artefatos, impressão de pacote, impressão de conjunto e
linhas normalizadas de referência **idênticos**. E produzem impressão global e
de avaliação **diferentes**, porque a diferença ali é real.

**O ajuste recusa uma linha de avaliação em vez de ignorá-la.** Ignorar em
silêncio faria um leitor mal configurado — um que esquecesse a poda de
partição — produzir um conjunto plausível sobre a população errada.

**A fronteira do normalizador é conferida contra a da divisão.** As duas são
independentes no código e têm de ser a mesma no domínio; um normalizador cortado
uma semana depois traria algumas partidas de avaliação para dentro da escala, e
as medianas continuariam plausíveis.

**Reajustar sobre a mesma referência é idempotente na identidade.** Dois ajustes
independentes produzem ids diferentes e a MESMA impressão — e é isso que permite
descobrir, com uma consulta, que não é preciso republicar nada.

**O custo é uma impressão a mais para calcular e três colunas a mais no
esquema.** Ela sai de graça na varredura que já acontece.

## Alternativas descartadas

**Usar a impressão crua global e «lembrar» de não reajustar.** É disciplina, e
disciplina não sobrevive a seis meses e a uma pessoa nova.

**Não ter impressão de referência e comparar as medianas número a número.**
Funciona para um eixo e não escala para 29 × N competições — e não responde
«mudou alguma coisa?» sem trazer tudo do banco.

**Ajustar por partida (`BEFORE_EVALUATED_MATCH`) também no histórico.** É mais
preciso e é N vezes mais caro, e não define UM conjunto de artefatos para o
dataset. Ele continua sendo o contrato do caminho ao vivo.
