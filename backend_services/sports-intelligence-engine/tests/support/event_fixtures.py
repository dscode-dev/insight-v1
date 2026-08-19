"""O cenário sintético de eventos — controlado, e realista onde importa.

O QUE ELE COBRE, e cada item é um §:

    GOAL, SHOT, CARD, SUBSTITUTION    os quatro tipos do §84
    dois eventos no mesmo minuto      a ordem determinística do §86
    id de provedor repetido           a idempotência do §87
    correção e cancelamento           as revisões do §88
    tipo desconhecido                 o §89
    jogador faltando                  o §90
    evento sem jogador exigido        o §91
    com e sem coordenada              os §92 e §93
    `xg=0.00` e `xg` ausente          o §94

TUDO DERIVADO, NADA SORTEADO. `uuid5` sobre chave natural em toda parte: a
identidade canônica do evento é derivada da chave da fonte, e um cenário com
ids aleatórios faria o teste de reprocessamento passar ou falhar por acidente.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from sports_intelligence.domain.events.records import (
    EventRevisionKind,
    HistoricalEventRecord,
    RawEventClock,
    RawEventPoint,
)
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.events.typing_map import EventTypeMapping
from sports_intelligence.domain.shared.identity import (
    DatasetId,
    MatchId,
    PlayerId,
    ProviderId,
    TeamId,
)
from sports_intelligence.domain.shared.temporal import Period
from sports_intelligence.domain.sources.records import DatasetRecordRef

PROVEDOR: Final[ProviderId] = ProviderId("fonte_de_eventos")
DATASET: Final[DatasetId] = DatasetId.derive("pr0441", "eventos")
ARQUIVO: Final[str] = str(DatasetId.derive("pr0441", "arquivo"))

#: A partida do cenário, no vocabulário do provedor e no nosso.
REF_DA_PARTIDA: Final[str] = "prov-match-1001"
PARTIDA: Final[MatchId] = MatchId.derive("pr0441", "partida-1001")

REF_DO_TIME: Final[str] = "prov-team-77"
TIME: Final[TeamId] = TeamId.derive("pr0441", "time-77")
REF_DO_OUTRO_TIME: Final[str] = "prov-team-88"
OUTRO_TIME: Final[TeamId] = TeamId.derive("pr0441", "time-88")

REF_DO_ARTILHEIRO: Final[str] = "prov-player-9"
ARTILHEIRO: Final[PlayerId] = PlayerId.derive("pr0441", "jogador-9")
REF_DO_RESERVA: Final[str] = "prov-player-19"
RESERVA: Final[PlayerId] = PlayerId.derive("pr0441", "jogador-19")
#: Um jogador que a fonte cita e a resolução NUNCA provou. É o §90.
REF_DO_DESCONHECIDO: Final[str] = "prov-player-404"


def tabela_de_tipos(version: int = 1) -> EventTypeMapping:
    """A tradução do provedor. Explícita — nenhum rótulo entra por heurística.

    `corner_won` NÃO ESTÁ AQUI de propósito: ele é o tipo desconhecido do §89,
    e o teste prova que ele não vira `CORNER` por parecer com um.
    """
    return EventTypeMapping(
        provider_id=PROVEDOR,
        entries={
            "goal": EventType.GOAL,
            "shot": EventType.SHOT,
            "card": EventType.CARD,
            "substitution": EventType.SUBSTITUTION,
            "period_end": EventType.PERIOD_END,
        },
        version=version,
    )


def ref(linha: int) -> DatasetRecordRef:
    return DatasetRecordRef(dataset_id=DATASET, file_id=ARQUIVO, record_number=linha)


def evento(
    linha: int,
    *,
    tipo: str,
    minuto: int,
    periodo: Period = Period.FIRST_HALF,
    acrescimo: int = 0,
    sequencia: int | None = None,
    id_do_evento: str | None = None,
    time: str | None = REF_DO_TIME,
    jogador: str | None = None,
    x: str | None = None,
    y: str | None = None,
    revisao: EventRevisionKind = EventRevisionKind.NEW,
    substitui: str | None = None,
    detalhes: dict[str, str] | None = None,
) -> HistoricalEventRecord:
    """Um registro de evento, como a fonte o entregaria."""
    return HistoricalEventRecord(
        record_ref=ref(linha),
        provider_id=PROVEDOR,
        match_reference=REF_DA_PARTIDA,
        raw_type=tipo,
        clock=RawEventClock(period=periodo, minute=minuto, stoppage=acrescimo),
        provider_event_id=id_do_evento if id_do_evento is not None else f"ev-{linha}",
        sequence=sequencia,
        team_reference=time,
        player_reference=jogador,
        start_point=(
            RawEventPoint(x=Decimal(x), y=Decimal(y)) if x is not None and y is not None else None
        ),
        revision=revisao,
        supersedes_reference=substitui,
        details=detalhes or {},
    )


def gol(linha: int = 1, *, minuto: int = 23, **kwargs: object) -> HistoricalEventRecord:
    """Um gol COM coordenada e COM xG medido em `0.12`."""
    padrao: dict[str, object] = {
        "tipo": "goal",
        "minuto": minuto,
        "jogador": REF_DO_ARTILHEIRO,
        "x": "0.88",
        "y": "0.52",
        "detalhes": {"EVENT_OUTCOME": "GOAL", "EVENT_XG": "0.12"},
    }
    padrao.update(kwargs)
    return evento(linha, **padrao)  # type: ignore[arg-type]


def chute_sem_xg(linha: int = 2, *, minuto: int = 23) -> HistoricalEventRecord:
    """Um chute cujo xG a fonte NÃO publicou. `xg` ausente ≠ `xg = 0` (§94)."""
    return evento(
        linha,
        tipo="shot",
        minuto=minuto,
        jogador=REF_DO_ARTILHEIRO,
        detalhes={"EVENT_OUTCOME": "OFF_TARGET", "EVENT_XG": ""},
    )


def chute_com_xg_zero(linha: int = 3, *, minuto: int = 31) -> HistoricalEventRecord:
    """Um chute cujo xG a fonte MEDIU e deu zero. É observação, não ausência."""
    return evento(
        linha,
        tipo="shot",
        minuto=minuto,
        jogador=REF_DO_ARTILHEIRO,
        x="0.30",
        y="0.10",
        detalhes={"EVENT_OUTCOME": "OFF_TARGET", "EVENT_XG": "0.00"},
    )


def cartao(linha: int = 4, *, minuto: int = 55) -> HistoricalEventRecord:
    return evento(
        linha,
        tipo="card",
        minuto=minuto,
        jogador=REF_DO_ARTILHEIRO,
        detalhes={"EVENT_CARD_TYPE": "YELLOW"},
    )


def substituicao(linha: int = 5, *, minuto: int = 70) -> HistoricalEventRecord:
    """Substituição: os DOIS jogadores vêm no detalhe (§34)."""
    return evento(
        linha,
        tipo="substitution",
        minuto=minuto,
        detalhes={
            "EVENT_PLAYER_OUT_PROVIDER_ID": REF_DO_ARTILHEIRO,
            "EVENT_PLAYER_IN_PROVIDER_ID": REF_DO_RESERVA,
        },
    )


def fim_de_periodo(linha: int = 6) -> HistoricalEventRecord:
    """Um evento SEM time e SEM jogador (§59, §91). O apito não é de ninguém."""
    return evento(linha, tipo="period_end", minuto=45, acrescimo=2, time=None)


def tipo_desconhecido(linha: int = 7) -> HistoricalEventRecord:
    """§89. `corner_won` não está na tabela — e não vira `CORNER`."""
    return evento(linha, tipo="corner_won", minuto=12)


def chute_sem_jogador_resolvido(linha: int = 8) -> HistoricalEventRecord:
    """§90. `SHOT` EXIGE executante, e a referência não resolve.

    O TIPO É `SHOT` E NÃO `GOAL`, e a escolha é do domínio: `EventType.GOAL`
    não está em `_COM_JOGADOR` desde o PR-01 — um gol contra ou não atribuído
    existe, e exigir executante nele obrigaria a inventar um. `SHOT` está, e é
    ele que exercita a recusa (§58, §59).
    """
    return evento(
        linha,
        tipo="shot",
        minuto=80,
        jogador=REF_DO_DESCONHECIDO,
        detalhes={"EVENT_OUTCOME": "SAVED"},
    )


def gol_sem_jogador(linha: int = 12) -> HistoricalEventRecord:
    """Um gol SEM executante declarado. Ele é legítimo (§58)."""
    return evento(linha, tipo="goal", minuto=88, jogador=None, detalhes={"EVENT_OUTCOME": "GOAL"})
