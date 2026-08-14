"""O resultado de uma evidência, num módulo só para quebrar o ciclo.

`evidence` precisa de `EvidenceOutcome`; `decisions` precisa de `evidence`;
`policy` precisa dos dois. Um enum de três valores num módulo próprio é mais
barato que um import tardio dentro de função — que funcionaria e esconderia a
dependência de quem lê o topo do arquivo.

TRÊS RESULTADOS, E O TERCEIRO É O QUE IMPORTA. `MATCHED` e `MISMATCHED` são
óbvios. `UNAVAILABLE` é a aplicação, à resolução de identidade, da regra que
o PR-00 estabeleceu para features: **ausente nunca é zero**. Uma fonte que
não traz data de nascimento não está discordando da data canônica — ela não
disse nada, e tratar silêncio como divergência puniria fontes incompletas por
serem incompletas.
"""

from __future__ import annotations

from enum import StrEnum


class EvidenceOutcome(StrEnum):
    """O que a consulta a uma evidência produziu."""

    MATCHED = "MATCHED"
    MISMATCHED = "MISMATCHED"
    #: Não havia o que comparar — a fonte não trouxe, ou o canônico não tem.
    #: Contribui com peso zero, e NÃO conta como divergência.
    UNAVAILABLE = "UNAVAILABLE"
