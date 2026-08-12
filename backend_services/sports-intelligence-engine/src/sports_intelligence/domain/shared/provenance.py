"""De onde veio cada dado, e o que se pode fazer com ele.

DUAS PERGUNTAS QUE PRECISAM DE RESPOSTA ANTES DE QUALQUER CÁLCULO.

A primeira é de confiança: um placar de fonte aberta e um de provedor
comercial não valem o mesmo quando discordam, e a regra de desempate precisa
estar escrita em algum lugar antes de o desempate acontecer. Aqui.

A segunda é jurídica, e ela costuma ser lembrada tarde demais: uma base
`RESEARCH_ONLY` não pode alimentar um produto pago. Descobrir isso depois de
o dado estar dentro do índice histórico significa reconstruir o índice.
`license_class` viaja com o dado desde a primeira linha para que a pergunta
"posso publicar isto?" tenha resposta sem arqueologia.

`INSIGHT_NATIVE` É O DESTINO, NÃO UMA ORIGEM A MAIS. O motor começa com dado
público de bootstrap e passa a produzir o próprio histórico, partida ao vivo
por partida ao vivo. Um dado nativo é o único que nasce sem provedor externo
e sem restrição de licença — e é por isso que ele é o objetivo do ciclo
descrito em ADR-0006.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Self, final

from sports_intelligence.domain.shared.identity import ProviderId, ProviderRef
from sports_intelligence.domain.shared.temporal import ObservationTimes


class SourceType(StrEnum):
    """A natureza da origem. Governa precedência quando fontes discordam."""

    OPEN_DATA = "OPEN_DATA"
    COMMERCIAL_PROVIDER = "COMMERCIAL_PROVIDER"
    #: Produzido pelo próprio motor, a partir de partidas que ele processou
    #: ao vivo. Ver ADR-0006.
    INSIGHT_NATIVE = "INSIGHT_NATIVE"
    MANUAL = "MANUAL"


class LicenseClass(StrEnum):
    """O que se pode fazer com o dado. `UNKNOWN` é o default seguro."""

    PUBLIC_DOMAIN = "PUBLIC_DOMAIN"
    ATTRIBUTION_REQUIRED = "ATTRIBUTION_REQUIRED"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    COMMERCIAL_ALLOWED = "COMMERCIAL_ALLOWED"
    #: Licença não declarada. Trata-se como a mais restritiva possível: o
    #: default de uma licença desconhecida NUNCA pode ser "pode tudo".
    UNKNOWN = "UNKNOWN"

    @property
    def allows_commercial_use(self) -> bool:
        return self in (LicenseClass.PUBLIC_DOMAIN, LicenseClass.COMMERCIAL_ALLOWED)

    @property
    def requires_attribution(self) -> bool:
        return self is LicenseClass.ATTRIBUTION_REQUIRED


@final
@dataclass(frozen=True, slots=True)
class DataProvenance:
    """A ficha de origem de um dado. Viaja com ele até o fim.

    NÃO É METADADO DECORATIVO. É o que responde três perguntas operacionais
    que aparecem sempre e sempre tarde: de quem é este número, quando ele foi
    observado, e temos direito de publicá-lo.
    """

    source_type: SourceType
    provider_id: ProviderId | None
    source_record_id: str | None
    times: ObservationTimes
    license_class: LicenseClass = LicenseClass.UNKNOWN

    def __post_init__(self) -> None:
        # Um dado de provedor sem provedor é um dado órfão: quando ele
        # discordar de outro, não haverá como decidir qual vence.
        externa = (SourceType.OPEN_DATA, SourceType.COMMERCIAL_PROVIDER)
        if self.source_type in externa and self.provider_id is None:
            raise ValueError(
                f"{self.source_type} exige provider_id — sem ele não há precedência possível"
            )
        # O nativo é produzido aqui: um provedor externo nele é contradição.
        if self.source_type is SourceType.INSIGHT_NATIVE and self.provider_id is not None:
            raise ValueError(
                "INSIGHT_NATIVE não tem provedor externo: o dado é produzido pelo próprio motor"
            )

    @property
    def provider_ref(self) -> ProviderRef | None:
        """A referência do provedor, quando os dois lados existem."""
        if self.provider_id is None or self.source_record_id is None:
            return None
        return ProviderRef(provider=self.provider_id, external_id=self.source_record_id)

    @property
    def is_native(self) -> bool:
        return self.source_type is SourceType.INSIGHT_NATIVE

    @classmethod
    def native(cls, times: ObservationTimes, source_record_id: str | None = None) -> Self:
        """Dado nascido do próprio motor: sem provedor, sem trava de licença."""
        return cls(
            source_type=SourceType.INSIGHT_NATIVE,
            provider_id=None,
            source_record_id=source_record_id,
            times=times,
            license_class=LicenseClass.COMMERCIAL_ALLOWED,
        )


#: PRECEDÊNCIA ENTRE ORIGENS, quando duas descrevem o mesmo fato.
#:
#: DECLARADA, e não aprendida a partir de qual fonte acerta mais no corpus
#: atual. Uma precedência ajustada pelos dados muda quando os dados mudam — e
#: a pergunta "de quem é este placar" precisa ter a mesma resposta amanhã.
#:
#: O nativo vem primeiro porque foi observado pelo próprio motor, com os
#: quatro carimbos de tempo que ele mesmo produziu; o manual vem por último
#: porque é a correção de um humano, que entra por exceção e não por volume.
SOURCE_PRECEDENCE: tuple[SourceType, ...] = (
    SourceType.INSIGHT_NATIVE,
    SourceType.COMMERCIAL_PROVIDER,
    SourceType.OPEN_DATA,
    SourceType.MANUAL,
)


def precedence_rank(source_type: SourceType) -> int:
    """Posição na precedência. Menor vence."""
    return SOURCE_PRECEDENCE.index(source_type)
