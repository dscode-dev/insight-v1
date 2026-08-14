"""Quem pediu. O mínimo, e por que o mínimo é o certo agora.

O QUE ISTO NÃO É. Não é RBAC, não tem papel, não tem permissão, não tem
política. Construir um sistema de autorização antes de existir a segunda
operação que precisa de autorização diferente produz um sistema calibrado para
um caso hipotético — e ele fica no caminho quando o caso real chega.

O QUE ISTO É. A garantia de que toda operação administrativa tem AUTOR, e que
o autor não é um padrão global. Um `created_by = "system"` embutido no código
é indistinguível de "ninguém sabe quem fez", e é o que se encontra em toda
trilha de auditoria que foi construída depois do fato.

Então: o ator é obrigatório, vem da fronteira, e a fronteira o deriva de quem
autenticou. Ele nunca vem do corpo da requisição — deixar o cliente declarar
quem é ele transforma a trilha de auditoria em campo de texto livre.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self, final

from sports_intelligence.domain.shared.errors import UnauthorizedError, ValidationError


class ActorKind(StrEnum):
    """A natureza de quem pediu. Governa o que se espera do id."""

    #: Uma pessoa operando o Control Plane.
    HUMAN_OPERATOR = "HUMAN_OPERATOR"
    #: Outro serviço do Insight, autenticado por token interno.
    SERVICE = "SERVICE"
    #: A CLI, rodando na máquina de alguém. Distinta do operador humano na
    #: API porque o caminho de autenticação é outro, e a trilha precisa
    #: distinguir "aprovou pelo console" de "rodou um comando local".
    CLI = "CLI"
    #: Um processo do próprio motor: worker, reconciliação, migração.
    SYSTEM = "SYSTEM"

    @property
    def is_human(self) -> bool:
        return self in (ActorKind.HUMAN_OPERATOR, ActorKind.CLI)


#: O `:` entra desde o PR-03 para a convenção `user:<uuid>` — que torna a
#: trilha legível sem consulta cruzada. Ele é seguro aqui: este identificador
#: nunca vira caminho de arquivo nem chave de objeto; ele é gravado numa
#: coluna e comparado por igualdade.
_ID_DE_ATOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:-]{1,127}$")

#: Identificadores que parecem autoria e não são. Recusados por nome porque
#: cada um deles, encontrado numa trilha de auditoria dois anos depois,
#: significa exatamente "não sabemos quem fez" — e é melhor falhar no momento
#: da configuração do que descobrir isso durante uma investigação.
_PROIBIDOS: Final[frozenset[str]] = frozenset(
    {"system", "admin", "root", "unknown", "anonymous", "none", "null", "default", "-"}
)


@final
@dataclass(frozen=True, slots=True)
class Actor:
    """Quem está executando a operação."""

    id: str
    kind: ActorKind

    def __post_init__(self) -> None:
        texto = self.id.strip()
        if not _ID_DE_ATOR.match(texto):
            raise ValidationError(
                f"identificador de ator {self.id!r} inválido: 2 a 128 caracteres, "
                "letras, dígitos, ponto, arroba, hífen e underscore"
            )
        if texto.lower() in _PROIBIDOS and self.kind is not ActorKind.SYSTEM:
            raise ValidationError(
                f"{texto!r} não identifica ninguém. Uma trilha de auditoria com este "
                "autor responde 'quando' e não responde 'quem', que é a pergunta.",
                context={"actor": texto},
            )
        object.__setattr__(self, "id", texto)

    @classmethod
    def system(cls, process: str) -> Self:
        """Um processo do motor. O nome do processo É a identificação.

        `Actor.system("dataset-reconciler")` é acionável — diz qual código
        fez. `Actor("system")` não é, e é por isso que o construtor genérico
        recusa o literal.
        """
        return cls(id=process, kind=ActorKind.SYSTEM)

    @classmethod
    def service(cls, name: str) -> Self:
        """Um serviço identificado pelo que ele É, não por «system».

            Actor.service("historical-resolution-worker")

        A DISTINÇÃO ENTRE HUMANO E SERVIÇO É O QUE O PR-03 EXIGE, e ela não é
        cosmética: uma decisão de identidade tomada por um worker sob política
        declarada e uma tomada por uma pessoa na fila de revisão são coisas
        diferentes, com garantias diferentes. `ResolutionDecision` recusa a
        combinação errada — método manual com ator de serviço, e vice-versa.
        """
        return cls(id=name, kind=ActorKind.SERVICE)

    @classmethod
    def human(cls, user_id: str) -> Self:
        """Uma pessoa. O identificador é opaco e vem de quem autenticou.

            Actor.human("user:9f2b6f3e-6a1f-4d2c-9c4a-1e5b7d8f0a31")

        O PREFIXO `user:` NÃO É EXIGIDO e é a convenção recomendada: ele
        torna a trilha legível sem consulta cruzada. O que É exigido está no
        construtor — o identificador não pode ser um nome genérico.
        """
        return cls(id=user_id, kind=ActorKind.HUMAN_OPERATOR)

    @property
    def is_automated(self) -> bool:
        """Se quem decidiu foi código.

        `CLI` CONTA COMO HUMANO, e é a resposta certa: quem digitou o comando
        foi uma pessoa, e `getpass.getuser()` a identifica. O que a distingue
        de `HUMAN_OPERATOR` é o caminho — «rodou um comando local» contra
        «aprovou pelo console» —, não a natureza.
        """
        return not self.kind.is_human

    @property
    def is_service(self) -> bool:
        """Se é um processo automático identificado pelo próprio nome."""
        return self.kind in (ActorKind.SERVICE, ActorKind.SYSTEM)

    def __str__(self) -> str:
        return f"{self.id}({self.kind})"


def require_actor(actor: Actor | None) -> Actor:
    """Recusa a operação sem autor, com a categoria de erro certa.

    `UnauthorizedError` E NÃO `ValidationError`: a ausência de ator não é um
    campo mal preenchido, é uma requisição que não provou quem é. A distinção
    chega ao cliente como 401 em vez de 422, e a diferença muda o que ele faz
    a respeito.
    """
    if actor is None:
        raise UnauthorizedError(
            "operação administrativa sem ator identificado — "
            "toda mutação do Control Plane tem autor, e ele vem de quem autenticou"
        )
    return actor
