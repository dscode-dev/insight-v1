# ADR-0008 — Versionamento de features e engines

**Status:** aceito · **Data:** 2026-08-12

## Contexto

Um vetor do espaço v3 e outro do v4 têm dimensões diferentes, escalas
diferentes, ou as duas. A distância entre eles é perfeitamente calculável e
completamente sem sentido.

Nada falha: as normas existem, o cosseno retorna, o vizinho aparece.

## Decisão

Quatro Value Objects versionados: `DatasetVersion`, `FeatureSpaceVersion`,
`EngineVersion`, `NormalizerVersion`.

**A versão viaja com o artefato**, e comparar artefatos de versões diferentes
é **recusado** — `assert_comparable` levanta `VersionMismatchError`.

Semântica reduzida a `major.minor`, sem patch: um espaço de features não tem
"correção que não muda nada". Ou mudou — e os vetores precisam ser refeitos —
ou não mudou.

## Consequências

**Ganhamos:** impossível comparar por engano, e regressão mede mudança de
comportamento em vez de mudança de código.

**Pagamos:** mudar o espaço obriga reconstruir o índice. É o custo real da
mudança, agora visível em vez de silencioso.

## Alternativas consideradas

**Converter entre versões.** Rejeitado: a conversão inventa os valores das
dimensões que não existiam, e um valor inventado é indistinguível de um medido.

**Comparar só o major.** Rejeitado: um minor pode acrescentar dimensão — nada
antigo quebra, então o major segue igual — e um vetor com uma dimensão a mais
já não vive no mesmo espaço.

