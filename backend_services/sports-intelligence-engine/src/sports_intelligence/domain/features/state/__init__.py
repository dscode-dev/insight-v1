"""O estado histórico de uma partida num instante — reduzido de fatos efetivos.

    HistoricalMatchState_t = Reduce(InitialState, EffectiveCanonicalFacts<=t)

O QUE MORA AQUI: a representação ESTRUTURAL e tipada de como a partida estava
— placar, quem está em campo, cartões, substituições aplicadas, cotações
conhecidas —, mais o reducer puro que a produz.

O QUE NÃO MORA: nenhuma feature. Contagem em janela, xG acumulado, pressão e
ritmo são o PR-05.3, e a diferença não é de tamanho:

    State    «como a partida ESTAVA»          fato estrutural
    Feature  «que número descreve isso»       interpretação matemática

    HistoricalMatchState  ≠  MatchStateVector
"""
