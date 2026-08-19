"""O evento COMO A FONTE O DESCREVE — antes de virar fato canônico.

ELE É O DEGRAU QUE FALTAVA. Entre a linha do CSV e o `CanonicalMatchEvent` há
duas coisas que precisam acontecer, e elas são de naturezas diferentes:

    ler          texto → valores tipados, com o papel de cada coluna
    resolver     referências do provedor → ids canônicos, com evidência

`HistoricalEventRecord` é o resultado da PRIMEIRA e a entrada da segunda. Ele
carrega o que a fonte disse, tipado e validado estruturalmente, e NENHUM id
canônico — porque a essa altura eles ainda não foram provados.

POR QUE ELE NÃO É UM `dict`. Um dicionário livre atravessaria o pipeline
inteiro sem que ninguém soubesse quais chaves existem, e o primeiro `KeyError`
apareceria dentro do construtor canônico — longe da linha que o causou. Aqui
cada campo tem tipo e a ausência é `None`, que é diferente de zero.

O QUE ELE NÃO FAZ, e a lista é o ponto:

    não resolve identidade      isso é o PR-03, e reimplementá-lo aqui criaria
                                um segundo resolvedor com outras regras
    não decide elegibilidade    isso é a qualidade
    não constrói evento         isso é o `CanonicalEventBuilder`
    não funde provedores        isso não existe, e é deliberado (§25)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import final

from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import ProviderId
from sports_intelligence.domain.shared.temporal import Period
from sports_intelligence.domain.sources.records import DatasetRecordRef


@final
class EventRevisionKind(StrEnum):
    """O que a fonte diz que ESTA linha é.

    ELA É DECLARADA, NUNCA DEDUZIDA (§21). Inferir «correção» de um id
    repetido faria toda reingestão da mesma fonte parecer uma cadeia de
    correções, e a segunda leitura de um arquivo imutável produziria revisões
    que ninguém emitiu.
    """

    NEW = "NEW"
    CORRECTION = "CORRECTION"
    CANCELLATION = "CANCELLATION"

    @property
    def references_predecessor(self) -> bool:
        """Se esta linha precisa dizer QUAL evento ela revisa.

        Uma correção sem predecessor é uma correção de nada — e o §22 exige
        que o anterior sobreviva, o que só é possível sabendo qual é ele.
        """
        return self is not EventRevisionKind.NEW


@final
@dataclass(frozen=True, slots=True)
class RawEventClock:
    """O relógio COMO A FONTE ESCREVEU. `45+3` continua sendo `45+3`.

    ACHATAR PARA `48` PERDE A SEMÂNTICA (§15). O terceiro minuto de acréscimo
    do primeiro tempo e o terceiro minuto do segundo tempo são momentos
    táticos opostos — um é o fim de uma etapa, o outro é o começo da seguinte
    —, e uma janela móvel que os confunde mistura os dois.
    """

    period: Period
    minute: int
    stoppage: int = 0

    def __post_init__(self) -> None:
        if self.minute < 0:
            raise ValidationError(f"minuto negativo na fonte: {self.minute}")
        if self.stoppage < 0:
            raise ValidationError(f"acréscimo negativo na fonte: {self.stoppage}")

    @property
    def label(self) -> str:
        return f"{self.minute}+{self.stoppage}" if self.stoppage else str(self.minute)

    def __str__(self) -> str:
        return f"{self.period}:{self.label}"


@final
@dataclass(frozen=True, slots=True)
class RawEventPoint:
    """Um ponto como a fonte o deu — normalizado, e ainda não canônico."""

    x: Decimal
    y: Decimal

    def __post_init__(self) -> None:
        for nome, valor in (("x", self.x), ("y", self.y)):
            if not Decimal(0) <= valor <= Decimal(1):
                raise ValidationError(
                    f"coordenada {nome}={valor} fora de [0,1]: o contrato pede "
                    "coordenada NORMALIZADA, e converter metros exigiria as "
                    "dimensões do campo, que a fonte não declara"
                )


@final
@dataclass(frozen=True, slots=True)
class HistoricalEventRecord:
    """UMA linha de uma fonte de eventos, lida e tipada.

    `provider_event_id` É `None` QUANDO A FONTE NÃO O DÁ, e a consequência é
    grande: sem ele o dataset não é reprocessável sem duplicar (§24), porque a
    identidade do evento passaria a depender da posição no arquivo. O contrato
    avisa disso na configuração; aqui o campo apenas diz a verdade.
    """

    #: De onde a linha veio — `dataset:arquivo:linha`. É o elo para o raw.
    record_ref: DatasetRecordRef
    provider_id: ProviderId
    #: A referência da PARTIDA no vocabulário do provedor.
    match_reference: str
    #: O tipo COMO A FONTE ESCREVEU. A tradução é explícita e vem depois.
    raw_type: str
    clock: RawEventClock
    provider_event_id: str | None = None
    sequence: int | None = None
    team_reference: str | None = None
    team_name: str | None = None
    player_reference: str | None = None
    player_name: str | None = None
    start_point: RawEventPoint | None = None
    end_point: RawEventPoint | None = None
    revision: EventRevisionKind = EventRevisionKind.NEW
    supersedes_reference: str | None = None
    #: Os detalhes crus, por papel. Fechado pelo mapeamento — o leitor só
    #: escreve aqui o que um `SemanticRole` de detalhe declarou.
    details: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.match_reference.strip():
            raise ValidationError(
                f"{self.record_ref}: evento sem referência de partida — ele não "
                "descreve fato nenhum, porque não se sabe de qual jogo é"
            )
        if not self.raw_type.strip():
            raise ValidationError(f"{self.record_ref}: evento sem tipo")
        if self.revision.references_predecessor and not (self.supersedes_reference or "").strip():
            raise ValidationError(
                f"{self.record_ref}: {self.revision} sem dizer QUAL evento revisa. "
                "Uma correção sem predecessor é uma correção de nada, e o anterior "
                "precisa sobreviver identificável (§22, §23)"
            )
        if self.sequence is not None and self.sequence < 0:
            raise ValidationError(f"{self.record_ref}: sequência negativa")

    @property
    def source_key(self) -> str | None:
        """A identidade DENTRO do provedor: `(provedor, id do evento)` (§19).

        `None` quando a fonte não dá id — e nesse caso não há identidade forte,
        só posição. O tipo diz isso em vez de inventar uma chave.
        """
        if self.provider_event_id is None:
            return None
        return f"{self.provider_id}:{self.provider_event_id}"

    @property
    def supersedes_key(self) -> str | None:
        if self.supersedes_reference is None:
            return None
        return f"{self.provider_id}:{self.supersedes_reference}"

    def detail(self, role: str) -> str | None:
        return self.details.get(role)

    def __str__(self) -> str:
        quem = self.player_reference or self.team_reference or "—"
        return (
            f"{self.raw_type}@{self.clock} [{quem}] "
            f"partida={self.match_reference} ({self.record_ref})"
        )


def ordering_key(record: HistoricalEventRecord) -> tuple[int, int, int, int, str]:
    """A ordem DETERMINÍSTICA de um evento dentro da partida (§17, §18).

    A ORDEM DO ARQUIVO NÃO ENTRA. Ela parece confiável e não é: um CSV
    reordenado por qualquer ferramenta produziria outra sequência canônica
    para os mesmos fatos, e dois processamentos do mesmo dado discordariam.

    O DESEMPATE É EM CASCATA, e cada degrau tem procedência:

        período       ordem do enum, que é a ordem do jogo
        minuto        o relógio
        acréscimo     `45+3` vem depois de `45`
        sequência     o que a fonte declara, quando declara
        id do evento  a última âncora estável que existe

    QUANDO NADA DISSO DESEMPATA, dois eventos ficam com a mesma chave e a
    ordem entre eles é a de leitura — o que é honesto: a fonte não disse.
    `EventContractReport.weak` avisa disso na configuração.
    """
    return (
        _ORDEM_DO_PERIODO.get(record.clock.period, 99),
        record.clock.minute,
        record.clock.stoppage,
        record.sequence if record.sequence is not None else 0,
        record.provider_event_id or "",
    )


#: A ordem dos períodos, escrita por extenso. `Period` é um `StrEnum` e a
#: ordem alfabética dele não é a ordem do jogo — `EXTRA_TIME_FIRST` viria
#: antes de `FIRST_HALF`, e a prorrogação apareceria antes do primeiro tempo.
_ORDEM_DO_PERIODO: dict[Period, int] = {
    Period.PRE_MATCH: 0,
    Period.FIRST_HALF: 1,
    Period.HALF_TIME: 2,
    Period.SECOND_HALF: 3,
    Period.EXTRA_TIME_FIRST: 4,
    Period.EXTRA_TIME_BREAK: 5,
    Period.EXTRA_TIME_SECOND: 6,
    Period.PENALTY_SHOOTOUT: 7,
    Period.FULL_TIME: 8,
}
