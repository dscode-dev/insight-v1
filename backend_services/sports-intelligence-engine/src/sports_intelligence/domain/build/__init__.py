"""A construção canônica — o que sai de uma decisão de qualidade e vira fato.

A SEPARAÇÃO QUE ESTE PACOTE EXISTE PARA IMPOR (ADR-0024):

    QualityAssessment   o dado PODE ser usado?
    CanonicalBuild      então construa — com o que a política deste build
                        permite, e registrando o que ficou de fora e por quê

O construtor NÃO RECALCULA QUALIDADE. Ele consome `MatchQualityRecord` e
`CanonicalBuildPolicy`, e nada mais decide elegibilidade. Duas implementações
da mesma regra divergem no primeiro ajuste — e a divergência aqui significa
um fato canônico construído sob um critério que ninguém declarou.

DUAS POLÍTICAS SOBRE A MESMA AVALIAÇÃO PRODUZEM CORPUS DIFERENTES, e isso é
o comportamento correto: um build de pesquisa inclui odds `RESEARCH_ONLY`; um
comercial as exclui. A identidade da partida é a MESMA nos dois (§19) — o que
muda é o conjunto de famílias materializadas.
"""
