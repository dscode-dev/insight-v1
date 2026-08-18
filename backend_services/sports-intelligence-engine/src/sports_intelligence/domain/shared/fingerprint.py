"""A impressão de um CONJUNTO que não cabe na memória.

O PROBLEMA. `FusedMatchCandidate.fingerprint` imprime UM objeto, e o PR-03
imprimiu o conjunto de uma execução ordenando todos os candidatos e
encadeando os digests. Funciona quando o conjunto cabe em memória.

Aqui ele não cabe: a avaliação de qualidade e a construção canônica varrem
dezenas de milhares de partidas em lotes, e materializar tudo para ordenar
seria exatamente o pico que o §67 proíbe.

DUAS SAÍDAS, e a segunda é esta:

    ordenar tudo e encadear    exige o conjunto inteiro em memória
    combinar de forma          cada item entra quando chega, em qualquer
    COMUTATIVA                 ordem, com memória constante

`XOR` sobre os digests é comutativo e associativo, então a impressão passa a
não depender da ordem dos lotes — que é uma propriedade mais forte que a
anterior, e não mais fraca: duas execuções que particionem os mesmos itens em
lotes diferentes têm de produzir a mesma impressão, senão ela não prova
reprodutibilidade nenhuma (§53).

O QUE `XOR` CUSTA, dito por extenso: ele não é resistente a colisão da mesma
forma que um hash encadeado — um adversário que escolhesse os itens poderia
construir dois conjuntos com a mesma impressão. NÃO É O MODELO DE AMEAÇA
AQUI. Esta impressão responde «duas execuções nossas produziram o mesmo
conjunto?», sobre dado que nós mesmos geramos. A integridade contra
adversário é do `ContentHash` do objeto bruto, que é encadeado e continua
sendo.

O ITEM REPETIDO SE CANCELA, e é a armadilha do XOR: incluir o mesmo item duas
vezes devolve a impressão de sem ele. Por isso `add` recusa duplicata — o
conjunto é de itens distintos, e a duplicata seria um defeito de quem chama.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final, Protocol, final, runtime_checkable

from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.shared.errors import ValidationError

#: Tamanho do digest em bytes. Nomeado porque ele aparece em três lugares.
_DIGEST_BYTES: Final[int] = 32


@runtime_checkable
class HasCanonicalForm(Protocol):
    """Qualquer coisa que sabe se serializar de forma determinística.

    As políticas do motor implementam isto — `as_canonical` ordena chaves,
    arredonda floats e converte enums para o valor textual, justamente para
    que a impressão não dependa de ordem de `dict`, de `repr` de objeto nem de
    endereço de memória (§38).
    """

    def as_canonical(self) -> dict[str, object]: ...


def policy_fingerprint(policy: HasCanonicalForm) -> ContentHash:
    """A impressão do CONTEÚDO de uma política.

    POR QUE A VERSÃO NÃO BASTA. Ela pega a mudança DECLARADA. A impressão pega
    a que ninguém declarou: alguém edita um piso, uma família descartável ou um
    escopo e esquece de subir o número — e as duas execuções ficam rotuladas
    `1.0` decidindo coisas diferentes. «Sob qual política esta partida
    reprovou» passa a ter duas respostas com o mesmo nome.

        identidade de configuração = versão + impressão do conteúdo

    UMA FUNÇÃO PARA TODAS AS POLÍTICAS, e não um método por classe: duas
    implementações da mesma serialização divergiriam no primeiro ajuste, e a
    divergência apareceria como duas execuções idênticas com impressões
    diferentes — que é o oposto do que ela existe para responder.

    A SERIALIZAÇÃO É DETERMINÍSTICA POR CONSTRUÇÃO: `sort_keys` ordena, o
    separador é fixo, e `ensure_ascii=False` mantém o texto estável em vez de
    depender de escape.
    """
    bruto = json.dumps(
        policy.as_canonical(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return ContentHash(hashlib.sha256(bruto).hexdigest())


@final
class SetFingerprint:
    """A impressão determinística de um conjunto, acumulada item a item.

    NÃO É `frozen`: ela é um acumulador por definição. O que é imutável é o
    RESULTADO — `value` devolve um `ContentHash`, e o objeto que o produziu
    não viaja para lugar nenhum.
    """

    __slots__ = ("_acumulado", "_chaves")

    def __init__(self) -> None:
        self._acumulado = 0
        self._chaves: set[str] = set()

    def add(self, key: str, payload: Any) -> None:
        """Acrescenta um item. `key` o identifica; `payload` é o conteúdo.

        A CHAVE É SEPARADA DO CONTEÚDO porque ela serve a duas coisas: entra
        no digest (dois itens de conteúdo igual e identidade diferente são
        dois itens) e detecta a duplicata que o XOR cancelaria em silêncio.
        """
        if key in self._chaves:
            raise ValidationError(
                f"item {key!r} acrescentado duas vezes à mesma impressão — com XOR "
                "a segunda cancelaria a primeira, e o conjunto pareceria não tê-lo",
                context={"key": key},
            )
        self._chaves.add(key)
        bruto = json.dumps(
            {"key": key, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        self._acumulado ^= int.from_bytes(hashlib.sha256(bruto).digest(), "big")

    @property
    def count(self) -> int:
        return len(self._chaves)

    @property
    def value(self) -> ContentHash | None:
        """A impressão, ou `None` quando nada entrou.

        `None` E NÃO O HASH DO VAZIO. Um conjunto vazio não tem impressão: ele
        não foi produzido, e um hash constante o faria parecer um resultado.
        """
        if not self._chaves:
            return None
        return ContentHash(self._acumulado.to_bytes(_DIGEST_BYTES, "big").hex())
