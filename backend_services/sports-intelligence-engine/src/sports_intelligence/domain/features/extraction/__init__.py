"""Da representacao estrutural do estado aos primeiros numeros de producao.

    FeatureSnapshot_t = Extract(HistoricalMatchState_t, EffectiveEvents_t, FeatureSpace)

O QUE MORA AQUI: a regua das janelas moveis, o catalogo de features de
producao, o espaco ordenado que elas formam, e o extrator puro que os junta.

O QUE NAO MORA: normalizacao executada, vetor, similaridade, distancia,
pressao, momentum, forca de time. O PR-05.3 produz numeros CRUS e
deterministicos; o que eles significam pertence as fases seguintes.

    HistoricalMatchState  «como a partida ESTAVA»
    FeatureSnapshot       «que numeros descrevem isso»
"""
