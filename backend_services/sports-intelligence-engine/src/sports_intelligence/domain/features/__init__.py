"""O domínio de features — contratos, semântica temporal e guardas de vazamento.

O QUE MORA AQUI: as regras que decidem QUAIS FATOS um modelo poderia
legitimamente conhecer num instante, e sob qual contrato matemático eles viram
feature. O que NÃO mora aqui é cálculo de feature real, vetor, normalizador
treinado, distância ou índice — nada disso existe ainda.

A ENTRADA AUTORIZADA É UMA SÓ:

    FeatureBuilderInput = HistoricalCanonicalDatasetVersion

Nem arquivo bruto, nem `SourceRecord`, nem `FusionRun`, nem `ResolutionRun`.
Eles continuam alcançáveis pela auditoria — que percorre o caminho ao
contrário —, e não pelo caminho de cálculo.
"""
