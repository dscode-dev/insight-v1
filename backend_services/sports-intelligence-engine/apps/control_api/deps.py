"""As dependências do FastAPI: contêiner e ator.

O QUE NÃO ESTÁ AQUI. A composição — ela mora em `apps/composition.py`, porque
a CLI monta exatamente o mesmo grafo e importá-lo de dentro do pacote da API
faria a CLI depender da API para existir. Este arquivo só liga o que já foi
montado ao mecanismo de injeção do FastAPI.

O ATOR VEM DE QUEM AUTENTICOU, NUNCA DO CORPO. `X-Actor-Id` é aceito porque o
chamador já provou quem é pelo token interno; um `actor` dentro do JSON seria
campo de texto livre, e a trilha de auditoria passaria a registrar o que o
cliente quis dizer sobre si mesmo. Sem ator, a requisição é recusada — não há
operador global embutido no código.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header, Request

from apps.composition import Container
from sports_intelligence.config.settings import SecuritySettings
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.errors import UnauthorizedError
from sports_intelligence.observability.logging import bind_context


def get_container(request: Request) -> Container:
    contêiner = getattr(request.app.state, "container", None)
    if contêiner is None:  # pragma: no cover — só se o startup não rodou
        raise RuntimeError("o contêiner não foi montado no startup da aplicação")
    return contêiner  # type: ignore[no-any-return]


def get_actor(
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-Id")] = None,
    x_actor_kind: Annotated[str | None, Header(alias="X-Actor-Kind")] = None,
    x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
) -> Actor:
    """Quem está pedindo. Recusa sem token e sem identificação.

    DUAS COISAS SEPARADAS, e é comum confundi-las: o TOKEN prova que a chamada
    vem de dentro do Insight; o ATOR diz quem, lá dentro, mandou fazer. Um
    token compartilhado por um serviço inteiro não identifica pessoa nenhuma,
    e uma trilha em que toda promoção foi feita por `console-api` responde
    "qual serviço" quando a pergunta é "quem".

    A comparação do token usa `secrets.compare_digest`: comparar segredo com
    `==` vaza o tamanho do prefixo correto pelo tempo de resposta.
    """
    esperado = SecuritySettings.from_env().internal_token.get_secret_value()
    if not x_internal_token or not secrets.compare_digest(x_internal_token, esperado):
        raise UnauthorizedError("token interno ausente ou inválido")
    if not x_actor_id:
        raise UnauthorizedError(
            "X-Actor-Id ausente: toda mutação administrativa tem autor, e ele vem de "
            "quem autenticou — nunca do corpo da requisição"
        )
    try:
        kind = ActorKind(x_actor_kind) if x_actor_kind else ActorKind.HUMAN_OPERATOR
    except ValueError as erro:
        raise UnauthorizedError(f"X-Actor-Kind {x_actor_kind!r} desconhecido") from erro
    ator = Actor(id=x_actor_id, kind=kind)
    bind_context(actor_id=ator.id)
    return ator


ContainerDep = Annotated[Container, Depends(get_container)]
ActorDep = Annotated[Actor, Depends(get_actor)]
