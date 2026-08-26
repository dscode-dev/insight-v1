"""Mapeamentos e aliases — a memória das decisões já tomadas.

O QUE ELES SÃO. Um `ProviderEntityMapping` é uma decisão de identidade
CONGELADA: «o provedor `football_data` chama de `MCI` a entidade que nós
chamamos de `TeamId(9f2b…)`». Um `EntityAlias` é mais fraco: «este texto já
foi visto se referindo a esta entidade».

POR QUE ISSO É A EVIDÊNCIA MAIS FORTE QUE EXISTE. Porque não é uma inferência:
alguém — um humano na fila de revisão, ou um resolver sob uma política
declarada — já decidiu isto, e a decisão ficou registrada com evidência,
versão e ator. Reusá-la não é adivinhar de novo; é lembrar.

MAPEAMENTO NÃO NASCE MAGICAMENTE (§13). Não existe `ProviderRef.to_entity_id()`
e nunca vai existir. Todo mapeamento aponta para a `ResolutionDecision` que o
originou — o campo é obrigatório —, e um mapeamento sem decisão que o explique
é indistinguível de um mapeamento inventado.

ALIASES FICAM FORA DE `Team` (§17). A entidade descreve o clube; o alias
descreve como as fontes o chamam, e são coisas de ciclo de vida diferente: um
clube tem um nome canônico e ganha aliases pelo resto da vida, um por fonte,
alguns com janela de validade. Guardá-los dentro da entidade faria toda
leitura de clube carregar uma lista que quase nenhum caminho usa.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Final, Self, final

from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.versions import NormalizerVersion
from sports_intelligence.domain.shared.errors import ConflictError, ValidationError
from sports_intelligence.domain.shared.identity import EntityId, ProviderId, ProviderRef
from sports_intelligence.domain.shared.temporal import Instant

MAX_ALIAS_LENGTH: Final[int] = 160


@final
@dataclass(frozen=True, slots=True)
class ProviderEntityMapping:
    """A tradução persistida entre a referência de um provedor e a nossa.

    A JANELA DE VALIDADE EXISTE PORQUE PROVEDOR RECICLA ID. Não é comum e
    acontece: uma fonte reorganiza o catálogo e o id 4417, que era do
    Manchester City, passa a ser de outro clube. Sem janela, todo dado antigo
    seria relido sob a tradução nova, e o histórico do City ganharia jogos de
    outro time — em silêncio.

    `valid_from = None` significa «desde sempre», e é o caso normal.
    """

    id: str
    provider_id: ProviderId
    entity_type: SubjectType
    provider_entity_id: str
    canonical_entity_id: EntityId
    #: A decisão que originou este mapeamento. OBRIGATÓRIA.
    resolution_decision_id: str
    created_at: Instant
    created_by: str
    valid_from: Instant | None = None
    valid_to: Instant | None = None

    def __post_init__(self) -> None:
        texto = self.provider_entity_id.strip()
        if not texto:
            raise ValidationError("mapeamento sem id do provedor")
        if len(texto) > MAX_ALIAS_LENGTH:
            raise ValidationError(
                f"id de provedor com {len(texto)} caracteres, acima de {MAX_ALIAS_LENGTH}"
            )
        object.__setattr__(self, "provider_entity_id", texto)
        if not self.resolution_decision_id.strip():
            raise ValidationError(
                "mapeamento sem decisão que o explique: ele seria indistinguível "
                "de um mapeamento inventado"
            )
        if not self.created_by.strip():
            raise ValidationError("mapeamento sem autor")
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_to < self.valid_from
        ):
            raise ValidationError("janela de validade invertida no mapeamento")

    @classmethod
    def create(
        cls,
        *,
        provider_ref: ProviderRef,
        entity_type: SubjectType,
        canonical_entity_id: EntityId,
        resolution_decision_id: str,
        at: Instant,
        created_by: str,
        valid_from: Instant | None = None,
        valid_to: Instant | None = None,
    ) -> Self:
        return cls(
            id=str(uuid.uuid4()),
            provider_id=provider_ref.provider,
            entity_type=entity_type,
            provider_entity_id=provider_ref.external_id,
            canonical_entity_id=canonical_entity_id,
            resolution_decision_id=resolution_decision_id,
            created_at=at,
            created_by=created_by,
            valid_from=valid_from,
            valid_to=valid_to,
        )

    def covers(self, moment: Instant) -> bool:
        """Se este mapeamento vale no instante dado."""
        if self.valid_from is not None and moment < self.valid_from:
            return False
        return not (self.valid_to is not None and moment > self.valid_to)

    @property
    def is_current(self) -> bool:
        return self.valid_to is None

    @property
    def lookup_key(self) -> str:
        """A chave de busca em memória, durante um lote.

        Existe para que o cache de execução tenha uma chave só e determinística
        — três `f"{a}:{b}:{c}"` espalhados divergem no primeiro que alguém
        ajusta.
        """
        return f"{self.provider_id}|{self.entity_type}|{self.provider_entity_id}"

    def __str__(self) -> str:
        janela = "" if self.is_current else f" (até {self.valid_to})"
        return f"{self.provider_id}:{self.provider_entity_id} → {self.canonical_entity_id}{janela}"


def mapping_lookup_key(provider: ProviderId, entity_type: SubjectType, external_id: str) -> str:
    """A mesma chave, para quem ainda não tem o mapeamento em mãos."""
    return f"{provider}|{entity_type}|{external_id.strip()}"


@final
@dataclass(frozen=True, slots=True)
class EntityAlias:
    """Um nome pelo qual uma entidade já foi vista.

    O NORMALIZADO É A CHAVE DE BUSCA E O ORIGINAL É O QUE O HUMANO LÊ. Os
    dois são guardados porque servem a coisas diferentes: `manchester city`
    casa; `Manchester City FC` é o que aparece na fila de revisão.

    `normalizer_version` VIAJA JUNTO porque o normalizador muda. Quando ele
    mudar, os aliases gravados sob a versão antiga precisam ser reindexados —
    e a versão gravada é o que torna possível saber quais. Sem ela, a única
    saída seria reindexar tudo, sempre.
    """

    id: str
    entity_type: SubjectType
    entity_id: EntityId
    alias_original: str
    alias_normalized: str
    normalizer_version: NormalizerVersion
    created_at: Instant
    created_by: str
    #: De qual provedor veio este alias, quando ele é específico de um.
    #: `None` = alias geral, válido para qualquer fonte.
    provider_id: ProviderId | None = None
    valid_from: Instant | None = None
    valid_to: Instant | None = None
    #: A decisão que o originou, quando houve uma. Aliases semeados no
    #: catálogo inicial não têm — e é honesto que não tenham.
    resolution_decision_id: str | None = None

    def __post_init__(self) -> None:
        for campo in ("alias_original", "alias_normalized"):
            valor = getattr(self, campo).strip()
            if not valor:
                raise ValidationError(f"{campo} vazio")
            if len(valor) > MAX_ALIAS_LENGTH:
                raise ValidationError(
                    f"{campo} com {len(valor)} caracteres, acima de {MAX_ALIAS_LENGTH}"
                )
            object.__setattr__(self, campo, valor)
        if not self.created_by.strip():
            raise ValidationError("alias sem autor")

    def covers(self, moment: Instant) -> bool:
        if self.valid_from is not None and moment < self.valid_from:
            return False
        return not (self.valid_to is not None and moment > self.valid_to)

    @property
    def lookup_key(self) -> str:
        return alias_lookup_key(self.entity_type, self.alias_normalized)

    def __str__(self) -> str:
        origem = f" [{self.provider_id}]" if self.provider_id else ""
        return f"{self.alias_original!r} → {self.entity_id}{origem}"


def alias_lookup_key(entity_type: SubjectType, normalized: str) -> str:
    return f"{entity_type}|{normalized}"


def assert_mapping_is_consistent(
    existing: ProviderEntityMapping | None,
    proposed: ProviderEntityMapping,
) -> None:
    """Recusa reapontar um mapeamento para outra entidade.

    O CASO QUE ISTO PEGA É O MAIS CARO DESTE PR. Um mapeamento existente
    aponta `MCI → Manchester City`; uma execução nova, sob resolver novo,
    conclui `MCI → Melbourne City`. Sobrescrever silenciosamente faria todo o
    histórico já resolvido passar a apontar para o clube errado — e nada
    falharia.

    A saída certa é conflito explícito: alguém precisa decidir qual dos dois
    está errado, e a decisão vira uma janela de validade ou uma correção
    registrada. Nunca um `UPDATE` que ninguém vê.
    """
    if existing is None:
        return
    if existing.canonical_entity_id == proposed.canonical_entity_id:
        return
    raise ConflictError(
        f"o mapeamento {existing.provider_id}:{existing.provider_entity_id} já aponta "
        f"para {existing.canonical_entity_id} e agora apontaria para "
        f"{proposed.canonical_entity_id}. Reapontar em silêncio reescreveria todo o "
        "histórico já resolvido sob a tradução antiga — decida qual está errado e "
        "registre a correção com janela de validade.",
        context={
            "provider": str(existing.provider_id),
            "external_id": existing.provider_entity_id,
            "current": str(existing.canonical_entity_id),
            "proposed": str(proposed.canonical_entity_id),
        },
    )
