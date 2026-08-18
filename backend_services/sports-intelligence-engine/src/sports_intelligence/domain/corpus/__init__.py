"""O corpus histórico versionado — a diferença entre «existe» e «foi publicado».

O QUE ESTE PACOTE EXISTE PARA SEPARAR (PR-04.3 §3):

    fato canônico persistido    está no registro. É verdade sobre o mundo.
    membro de um corpus         faz parte da versão X do histórico oficial.

As duas coisas são independentes, e confundi-las custa as duas garantias que o
PR-04 inteiro construiu. Um `Match` no registro pode ter sido construído por um
build de pesquisa e não pertencer a nenhum corpus comercial; o mesmo `Match`
pode pertencer a três versões diferentes do corpus, cada uma com um conjunto
de famílias distinto.

    CanonicalFacts  ≠  PublishedHistoricalCorpus

A unidade que este pacote introduz responde à pergunta que ninguém conseguia
fazer antes:

    «qual conjunto EXATO de fatos canônicos constitui o corpus histórico
     versão 1.0, e como eu provo isso seis meses depois?»

E o limite, dito por extenso (§4):

    HISTORICAL_CANONICAL_READY  ≠  HISTORICAL_VECTOR_ACTIVE

Um corpus pronto é um corpus que o PR-05 pode LER. Não há feature, não há
vetor, não há similaridade — e não haverá neste pacote.
"""
