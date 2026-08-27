"""A leitura do dataset normalizado para recuperação histórica.

    reader.py   lê `split=REFERENCE/competition={liga}/`, projetado nos eixos
                do perfil resolvido

ELE FICA AQUI, e não em `historical/normalized/`, porque lê para uma finalidade
diferente. O leitor de lá entrega LINHAS INTEIRAS para construir o dataset
normalizado; este entrega uma FATIA — identidade mais os eixos de um perfil — e
poda por competição e instante. Juntá-los faria o leitor da construção crescer
para servir a um consumidor que ele não conhece.
"""
