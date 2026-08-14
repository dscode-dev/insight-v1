"""A EXECUÇÃO da avaliação de qualidade sobre candidatos fundidos.

O DOMÍNIO DIZ O QUE É QUALIDADE; este pacote OBSERVA. A divisão é a mesma que
o PR-04.1 impôs entre validador e política, agora um nível acima:

    `domain/quality`   o que é um eixo, o que é cobertura, o que a política pesa
    aqui               o que ESTE candidato de fato tem

Nada aqui atribui severidade, nada aqui compara com um piso. O assessor emite
observações — problemas com código, contagens de cobertura, licenças por
família — e entrega tudo para `MatchQualityAssessment.evaluate`, que é onde a
política decide. Um `if confianca < 0.9` neste pacote seria a decisão de
negócio escondida num laço que o §23 do PR-04.1 existe para não ter.
"""
