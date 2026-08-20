"""O contexto pre-jogo — calendario e carga recente, e nada de forca de time.

    Context(M) = f(partidas anteriores da MESMA competicao, kickoff < kickoff(M))

O QUE MORA AQUI: a politica versionada, os insumos tipados e a prova de que o
corpus alcanca o passado que a janela pede.

O QUE NAO MORA: forma, pontos recentes, saldo de gols, Elo, confronto direto.
O resultado da partida anterior prova que ela terminou; o VALOR dele nao vira
feature nesta fase (§11, §20).
"""
