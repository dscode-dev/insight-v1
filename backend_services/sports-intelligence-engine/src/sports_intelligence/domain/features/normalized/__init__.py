"""A representação NORMALIZADA do dataset histórico de features.

O PACOTE SE CHAMA `normalized` E NÃO `normalization`, e a diferença não é
estética: `domain/features/normalization.py` já existe desde o PR-05.1 e
carrega a DECLARAÇÃO do normalizador — método, escopo, corte. Este pacote
carrega a APLICAÇÃO dela a um dataset inteiro.

    normalization.py     COMO normalizar          (PR-05.1)
    fitting/             o que o ajuste ENCONTROU (PR-05.4)
    normalized/          o dataset TRANSFORMADO   (PR-05.5.2)

O QUE ELE NÃO É. Não é vetor, não é embedding, não é índice de similaridade. As
cento e cinco dimensões continuam sendo as mesmas cento e cinco, na mesma
ordem, com os mesmos nomes — o que muda é a escala de vinte e nove delas.
"""
