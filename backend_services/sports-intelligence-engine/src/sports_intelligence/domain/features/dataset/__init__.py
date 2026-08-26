"""O dataset histórico de features — a grade, a divisão e a materialização.

ESTE PACOTE NÃO CALCULA FEATURE NENHUMA. Ele decide QUAIS cortes existem
(`grid`), a QUAL metade cada partida pertence (`split`), COMO uma linha
materializada é identificada (`keys`) e COMO se prova que duas execuções
produziram o mesmo dataset (`digest`, `manifest`). O cálculo continua sendo do
`MATCH_STATE_RAW_V2`.

ELE TAMBÉM NÃO NORMALIZA (PR-05.5.1, fronteira dura). Ajustar normalizador
exige uma população, e a população é justamente o que este PR produz — fazer
as duas coisas juntas faria a escala ser ajustada sobre um conjunto que ainda
não existe.
"""
