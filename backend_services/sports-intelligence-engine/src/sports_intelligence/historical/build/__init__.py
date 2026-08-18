"""A construção canônica em execução — um construtor TIPADO por família.

O QUE ESTE PACOTE SE PROÍBE (§29, §30):

    um `build_everything(candidate)` com centenas de ramos
    `Match(**fused_fields)`
    `dict[str, Any]` atravessando a fronteira canônica

O primeiro é um método que ninguém consegue ler inteiro e que ganha um `if`
por fonte nova. Os dois seguintes fazem a mesma coisa por outro caminho:
transformam toda mudança no mapeamento de fonte numa mudança no agregado
canônico, sem que nenhum tipo perceba.

Então cada família tem o seu construtor, cada construtor recebe um contrato
TIPADO de `domain/build/facts.py`, e a tradução entre a saída da fusão e esses
contratos é explícita, campo a campo, com a ausência sobrevivendo como
ausência (§44).

NENHUM CONSTRUTOR DECIDE ELEGIBILIDADE. Todos recebem a `BuildDecision` já
tomada e recusam trabalhar sem ela — é assim que o §5 vira assinatura em vez
de convenção.
"""
