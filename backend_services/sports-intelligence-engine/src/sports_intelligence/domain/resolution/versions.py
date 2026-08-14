"""As versões que governam uma decisão de identidade — e por que são três.

TRÊS COISAS MUDAM INDEPENDENTEMENTE, e confundi-las apaga a informação que
torna o reprocessamento útil:

    ResolverVersion     a LÓGICA: que evidências são consultadas, em que
                        ordem, como o score é composto.

    NormalizerVersion   a preparação do TEXTO: como `Manchester City FC`
                        vira uma chave comparável. Mudá-la re-chaveia todo
                        alias e todo índice normalizado.

    PolicyVersion       os LIMIARES e PESOS: a partir de quanto se resolve
                        sozinho, a partir de quanto vai para revisão.

Um resolver melhorado com a mesma política produz decisões diferentes. Uma
política afrouxada com o mesmo resolver também. Com uma versão só, as duas
mudanças ficariam indistinguíveis — e a pergunta «por que este registro
resolveu agora e não antes» não teria resposta.

`NormalizerVersion` já existe desde o PR-00 (`domain/shared/versioning`) e é
reexportada aqui para que os três nomes apareçam juntos onde são usados.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final, final

from sports_intelligence.domain.shared.versioning import (
    NormalizerVersion,
    Version,
)

__all__ = [
    "CURRENT_FUSION_POLICY_VERSION",
    "CURRENT_MATCH_POLICY_VERSION",
    "CURRENT_NORMALIZER_VERSION",
    "CURRENT_RESOLUTION_POLICY_VERSION",
    "CURRENT_RESOLVER_VERSION",
    "NormalizerVersion",
    "PolicyVersion",
    "ResolverVersion",
]


@final
@dataclass(frozen=True, slots=True, order=True)
class ResolverVersion(Version):
    """A versão da lógica de resolução.

    SOBE QUANDO O RACIOCÍNIO MUDA — uma evidência nova consultada, uma ordem
    diferente, um critério de desempate. Não sobe quando um limiar muda: isso
    é `PolicyVersion`, e separá-los é o que permite medir qual das duas
    mudanças causou a diferença.
    """

    KIND: ClassVar[str] = "versão do resolver"


@final
@dataclass(frozen=True, slots=True, order=True)
class PolicyVersion(Version):
    """A versão de uma política — de resolução ou de fusão.

    UM TIPO SÓ PARA AS DUAS, e é deliberado: elas nunca são comparadas entre
    si, e criar `ResolutionPolicyVersion` e `FusionPolicyVersion` separadas
    produziria duas classes idênticas cuja única diferença seria o nome. Onde
    a distinção importa, o objeto que a carrega já diz qual é.
    """

    KIND: ClassVar[str] = "versão de política"


#: O que este PR entrega. Constantes nomeadas e não literais espalhados: uma
#: versão escrita em cinco lugares diverge no primeiro que alguém esquece.
#: 1.1 — PR-03.2. O RACIOCÍNIO MUDOU, e é por isso que a versão sobe (§55).
#:
#: Três mudanças, todas na lógica e nenhuma nos limiares:
#:
#:   1. o mapeamento de provedor passou a ser CONSULTADO pela execução em
#:      lote. Ele já existia no resolver e nenhum chamador passava
#:      `provider_ref` — os quatro índices da tabela terminaram o benchmark
#:      do PR-03.1 com zero usos;
#:   2. a resolução de jogador passou a ter chamador na cadeia operacional;
#:   3. o universo de candidatos de similaridade deixou de ser «o que o lote
#:      carregou» e passou a ser uma busca por nome.
#:
#: Sob a mesma versão, a mesma entrada passaria a produzir decisões
#: diferentes — e a pergunta «por que este registro resolveu agora e não
#: antes» ficaria sem resposta. É exatamente o que a versão existe para
#: impedir.
CURRENT_RESOLVER_VERSION: Final[ResolverVersion] = ResolverVersion(major=1, minor=1)
CURRENT_NORMALIZER_VERSION: Final[NormalizerVersion] = NormalizerVersion(major=1, minor=0)
CURRENT_RESOLUTION_POLICY_VERSION: Final[PolicyVersion] = PolicyVersion(major=1, minor=0)
CURRENT_MATCH_POLICY_VERSION: Final[PolicyVersion] = PolicyVersion(major=1, minor=0)
#: 1.1 — PR-03.2, e a decisão aqui foi menos óbvia que a do resolver (§54).
#:
#: A REGRA NÃO MUDOU. A política já declarava odds como conjunto de
#: observações, já proibia média e já dizia que casas diferentes são
#: observações distintas. O texto dela estava certo o tempo todo.
#:
#: O QUE MUDOU FOI A SAÍDA. O agrupamento descartava a segunda linha da mesma
#: fonte antes de a fusão de observações chegar a vê-la, então a política
#: correta era aplicada sobre um conjunto amputado. Um cenário com duas casas
#: produzia uma observação.
#:
#: SOBE MESMO ASSIM, porque é esta versão que alguém usa para explicar a
#: saída de uma execução — e duas execuções rotuladas `1.0` produzindo
#: contagens de observação diferentes tornariam o rótulo inútil. A versão
#: identifica o que foi produzido, não só o que estava escrito.
CURRENT_FUSION_POLICY_VERSION: Final[PolicyVersion] = PolicyVersion(major=1, minor=1)
