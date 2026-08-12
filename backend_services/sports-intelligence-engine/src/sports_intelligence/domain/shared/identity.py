"""Identidade: o que é do domínio e o que é do provedor.

A DISTINÇÃO QUE ESTE MÓDULO EXISTE PARA IMPOR. Um id do domínio identifica uma
coisa real — uma partida, um clube. Um id de provedor identifica o REGISTRO
que um provedor tem sobre essa coisa. Três provedores olhando a mesma partida
produzem três ids; a partida continua sendo uma.

Confundir os dois é a falha mais cara que um motor destes comete, e ela é
silenciosa: nada quebra, os números só ficam errados. Contar a mesma partida
três vezes num histórico infla ranking, confronto direto e tabela sem
disparar nenhum erro.

Por isso `ProviderRef` não é um `EntityId`. Não há conversão entre os dois, e
a passagem de um para o outro é uma decisão de resolução de identidade, que é
uma etapa explícita do pipeline — nunca um cast.

DERIVAÇÃO DETERMINÍSTICA, QUANDO HOUVER. Ids do domínio nascem de duas formas:
sorteados (uuid4) para coisas que o motor cria, ou derivados (uuid5) de uma
chave natural para coisas que precisam ter o mesmo id em duas execuções. A
segunda forma é o que permite reprocessar um dataset e obter as mesmas linhas.
`derive` deixa isso explícito, e o namespace é por tipo para que a mesma chave
sob tipos diferentes não colida.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import ClassVar, Self, final

#: Raiz de todos os namespaces determinísticos do motor. Mudá-la re-chaveia
#: tudo que já foi derivado, então ela é uma constante de versão, não um
#: detalhe: qualquer alteração aqui é uma migração de dados.
ROOT_NAMESPACE: uuid.UUID = uuid.UUID("9f2b6f3e-6a1f-4d2c-9c4a-1e5b7d8f0a31")


@dataclass(frozen=True, slots=True)
class EntityId:
    """Um identificador do domínio interno. Nunca o id de um provedor."""

    #: Cada subclasse tem o seu, para que `derive("liverpool")` como time e
    #: como competição produzam valores diferentes.
    NAMESPACE: ClassVar[uuid.UUID] = ROOT_NAMESPACE

    value: uuid.UUID

    def __post_init__(self) -> None:
        if not isinstance(self.value, uuid.UUID):
            raise TypeError(
                f"{type(self).__name__} exige um UUID, recebeu {type(self.value).__name__}"
            )

    @classmethod
    def new(cls) -> Self:
        """Um id novo, para uma coisa que o motor está criando agora."""
        return cls(uuid.uuid4())

    @classmethod
    def derive(cls, *parts: str) -> Self:
        """O MESMO id para a MESMA chave natural, em qualquer execução.

        É o que torna a reconstrução de um dataset idempotente: reprocessar a
        mesma entrada produz as mesmas linhas, com as mesmas chaves, em vez de
        um conjunto novo indistinguível do anterior.

        As partes são unidas por `|`, então nenhuma delas pode conter esse
        caractere — senão ("a|b", "c") e ("a", "b|c") derivariam o mesmo id.
        """
        if not parts:
            raise ValueError("derive exige pelo menos uma parte da chave natural")
        limpas: list[str] = []
        for parte in parts:
            texto = parte.strip()
            if not texto:
                raise ValueError("parte vazia na chave natural: a chave ficaria ambígua")
            if "|" in texto:
                raise ValueError(
                    f"parte {texto!r} contém '|', que é o separador — a chave ficaria ambígua"
                )
            limpas.append(texto)
        return cls(uuid.uuid5(cls.NAMESPACE, "|".join(limpas)))

    @classmethod
    def parse(cls, raw: str) -> Self:
        try:
            return cls(uuid.UUID(raw))
        except (ValueError, AttributeError, TypeError) as erro:
            raise ValueError(f"{raw!r} não é um {cls.__name__} válido") from erro

    def __str__(self) -> str:
        return str(self.value)


def _ns(nome: str) -> uuid.UUID:
    return uuid.uuid5(ROOT_NAMESPACE, nome)


@final
@dataclass(frozen=True, slots=True)
class CompetitionId(EntityId):
    NAMESPACE: ClassVar[uuid.UUID] = _ns("competition")


@final
@dataclass(frozen=True, slots=True)
class SeasonId(EntityId):
    NAMESPACE: ClassVar[uuid.UUID] = _ns("season")


@final
@dataclass(frozen=True, slots=True)
class TeamId(EntityId):
    NAMESPACE: ClassVar[uuid.UUID] = _ns("team")


@final
@dataclass(frozen=True, slots=True)
class PlayerId(EntityId):
    NAMESPACE: ClassVar[uuid.UUID] = _ns("player")


@final
@dataclass(frozen=True, slots=True)
class MatchId(EntityId):
    NAMESPACE: ClassVar[uuid.UUID] = _ns("match")


@final
@dataclass(frozen=True, slots=True)
class DatasetId(EntityId):
    NAMESPACE: ClassVar[uuid.UUID] = _ns("dataset")


@final
@dataclass(frozen=True, slots=True)
class SnapshotId(EntityId):
    NAMESPACE: ClassVar[uuid.UUID] = _ns("snapshot")


@final
@dataclass(frozen=True, slots=True)
class ProviderId:
    """QUEM é o provedor — não o que ele diz.

    Um slug e não um UUID: provedores são poucos, nomeados, e aparecem em
    configuração e em log, onde `football_data` é legível e um UUID não é.
    """

    value: str

    def __post_init__(self) -> None:
        texto = self.value.strip()
        if not texto:
            raise ValueError("ProviderId não pode ser vazio")
        if not texto.replace("_", "").isalnum() or not texto[0].isalpha():
            raise ValueError(
                f"ProviderId {self.value!r} inválido: use minúsculas, dígitos e underscore, "
                "começando por letra"
            )
        if texto != texto.lower():
            raise ValueError(f"ProviderId {self.value!r} deve ser minúsculo")
        object.__setattr__(self, "value", texto)

    def __str__(self) -> str:
        return self.value


@final
@dataclass(frozen=True, slots=True)
class ProviderRef:
    """O id que UM provedor usa para UMA coisa.

    DELIBERADAMENTE INCONVERSÍVEL PARA `EntityId`. Não existe `.to_entity_id()`
    aqui, e a ausência é o ponto: transformar a referência de um provedor na
    identidade do domínio é resolução de identidade, uma etapa do pipeline com
    regras próprias e capaz de falhar. Oferecer um atalho faria dela um cast.
    """

    provider: ProviderId
    external_id: str

    def __post_init__(self) -> None:
        texto = self.external_id.strip()
        if not texto:
            raise ValueError(f"ProviderRef de {self.provider} sem external_id")
        object.__setattr__(self, "external_id", texto)

    def __str__(self) -> str:
        return f"{self.provider}:{self.external_id}"
