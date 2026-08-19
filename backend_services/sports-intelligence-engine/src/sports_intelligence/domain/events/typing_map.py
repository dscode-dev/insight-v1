"""A tradução `tipo do provedor → EventType`. Explícita, e recusa o que não sabe.

TRÊS DESENHOS INGÊNUOS, e o que cada um custa:

**Aceitar a string do provedor dentro do evento canônico.** `CanonicalMatchEvent`
passaria a conter `"Goal"`, `"GOAL"`, `"goal_scored"` e `"1"` como se fossem
tipos, e toda contagem por tipo viraria uma normalização ad-hoc espalhada por
quem lê. O `EventType` é um catálogo fechado justamente para isso não acontecer.

**Traduzir por heurística** — minúsculas, remover underscore, comparar prefixo.
Funciona em noventa e nove tipos e casa `PENALTY_GOAL` com `GOAL` no
centésimo, silenciosamente, e o corpus passa a ter gols que foram pênaltis
perdidos.

**Mandar o desconhecido para `OTHER`.** O catálogo NÃO TEM `OTHER`, e a
ausência é uma decisão do PR-01: um balde de «resto» acumula tudo que ninguém
mapeou e vira, com o tempo, a maior categoria do corpus — descrevendo nada.

O QUE ESTE MÓDULO FAZ: uma tabela declarada por provedor, e um resultado
TIPADO para o que não está nela (§14). O tipo cru sobrevive na procedência,
então «o que era esse evento que não entrou» continua tendo resposta.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, final

from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import ProviderId


@final
@dataclass(frozen=True, slots=True)
class TypeResolution:
    """O resultado de traduzir um tipo. Ou é canônico, ou diz que não é.

    DOIS CAMPOS E NÃO UM `EventType | None`. O `raw` viaja junto porque a
    mensagem que importa não é «tipo desconhecido» — é «`corner_won` não está
    mapeado para o provedor `statsbomb`», que já contém o conserto.
    """

    raw: str
    canonical: EventType | None = None

    @property
    def is_mapped(self) -> bool:
        return self.canonical is not None

    def require(self) -> EventType:
        if self.canonical is None:
            raise ValidationError(
                f"tipo de evento {self.raw!r} não mapeado — construir um evento "
                "canônico com ele exigiria escolher um tipo por conta própria"
            )
        return self.canonical

    def __str__(self) -> str:
        return f"{self.raw} → {self.canonical or 'NÃO MAPEADO'}"


@final
@dataclass(frozen=True, slots=True)
class EventTypeMapping:
    """A tabela de um provedor. Declarada, versionada, sem heurística.

    A CHAVE É NORMALIZADA SÓ NO CASO E NOS ESPAÇOS — `Goal`, `GOAL` e ` goal `
    são o mesmo rótulo escrito por mãos diferentes. O que ela NÃO faz é
    aproximar: `penalty_goal` continua sendo outra chave, e é exatamente a
    aproximação que produziria gols que foram pênaltis perdidos.
    """

    provider_id: ProviderId
    entries: dict[str, EventType]
    version: int = 1

    def __post_init__(self) -> None:
        if not self.entries:
            raise ValidationError(
                f"tabela de tipos vazia para {self.provider_id}: nenhum evento "
                "desta fonte teria como virar canônico"
            )
        if self.version < 1:
            raise ValidationError(f"versão de tabela inválida: {self.version}")
        normalizadas = {_chave(k) for k in self.entries}
        if len(normalizadas) != len(self.entries):
            raise ValidationError(
                "a tabela tem dois rótulos que normalizam para a mesma chave — "
                "qual dos dois traduziria não estaria definido"
            )
        # AS CHAVES SÃO NORMALIZADAS NA CONSTRUÇÃO, e não só na consulta. Com
        # a normalização só de um lado, uma tabela declarada com `"goal"` nunca
        # casaria com a busca por `"GOAL"` — e o sintoma seria «nada mapeia»,
        # que manda procurar no lugar errado.
        object.__setattr__(self, "entries", {_chave(k): v for k, v in self.entries.items()})

    def resolve(self, raw: str) -> TypeResolution:
        """Traduz. NÃO levanta: quem chama decide o que fazer com o não mapeado.

        Levantar aqui faria um único tipo desconhecido derrubar o lote inteiro,
        e a política de `UNMAPPED_TYPE` é da construção — pular, revisar ou
        recusar são decisões diferentes que a mesma tabela precisa permitir.
        """
        return TypeResolution(raw=raw, canonical=self.entries.get(_chave(raw)))

    @property
    def known(self) -> frozenset[str]:
        return frozenset(_chave(k) for k in self.entries)

    def with_entries(self, extra: dict[str, EventType]) -> EventTypeMapping:
        """Uma tabela nova com mais rótulos. A versão SOBE."""
        return EventTypeMapping(
            provider_id=self.provider_id,
            entries={**self.entries, **extra},
            version=self.version + 1,
        )


def _chave(raw: str) -> str:
    return raw.strip().upper().replace("-", "_").replace(" ", "_")


#: A tabela de referência do motor, para fontes que usam o vocabulário do
#: catálogo canônico — e para os fixtures.
#:
#: ELA NÃO É UM PADRÃO SILENCIOSO: nenhum provedor a recebe por omissão. Um
#: default global faria uma fonte com vocabulário próprio parecer mapeada, e o
#: primeiro rótulo coincidente entraria com o significado errado.
CANONICAL_TYPE_LABELS: Final[dict[str, EventType]] = {tipo.value: tipo for tipo in EventType}


def canonical_mapping(provider: ProviderId) -> EventTypeMapping:
    """A tabela identidade — para fontes que já falam o catálogo canônico."""
    return EventTypeMapping(provider_id=provider, entries=dict(CANONICAL_TYPE_LABELS))
