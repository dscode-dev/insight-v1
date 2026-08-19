"""Os repositórios de eventos canônicos em SQL escrito à mão.

O QUE É PARTICULAR DESTE ARQUIVO:

A ESCRITA É EM MASSA E DEVOLVE DESFECHO POR EVENTO. `executemany` com
`ON CONFLICT DO NOTHING` grava o lote inteiro numa ida; a distinção entre
`BUILT` e `REUSED` vem de uma consulta ANTES da escrita, porque `ON CONFLICT`
não diz qual linha era nova e adivinhar pelo estado final erraria exatamente
quando o evento pré-existente fosse idêntico (§67).

O ÚNICO `UPDATE` MUDA `status`, e nunca conteúdo. `CORRECTED` e `CANCELLED`
são metadado sobre a linha; o fato que ela grava permanece byte a byte como
estava, e é isso que faz «o que sabíamos antes» continuar tendo resposta
(§22, §100). Um teste de arquitetura lê este arquivo e falha se aparecer outro.

A LEITURA É ORDENADA POR `ORDER BY` EXPLÍCITO, nunca pela ordem natural do
PostgreSQL (§66). Ela vai alimentar janelas móveis no PR-05, e uma janela
sobre ordem instável produz números diferentes a cada leitura dos mesmos fatos.

O DETALHE VAI E VOLTA PELO CONTRATO TIPADO. Nada escreve `jsonb` livre: a
serialização conhece `ShotDetail`, `CardDetail` e `SubstitutionDetail`, e o
`kind` gravado é o que permite reconstruir o tipo certo na volta (§62).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final, final

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.events.build import (
    EventBuildCounts,
    EventBuildRecord,
    EventBuildRecordStatus,
    EventExclusionReason,
)
from sports_intelligence.domain.events.canonical import CanonicalMatchEvent, EventStatus
from sports_intelligence.domain.events.coordinates import (
    CoordinateFrame,
    PitchCoordinate,
)
from sports_intelligence.domain.events.details import (
    BodyPart,
    CardDetail,
    CardType,
    EventDetail,
    ShotDetail,
    ShotOutcome,
    SubstitutionDetail,
)
from sports_intelligence.domain.events.runs import CanonicalEventBuildRun
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.resolution.runs import RunStatus
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.feature_value import FeatureValue, Unavailability
from sports_intelligence.domain.shared.identity import (
    DatasetId,
    MatchId,
    PlayerId,
    ProviderId,
    TeamId,
)
from sports_intelligence.domain.shared.provenance import (
    DataProvenance,
    LicenseClass,
    SourceType,
)
from sports_intelligence.domain.shared.quality import DataQuality
from sports_intelligence.domain.shared.temporal import (
    MatchClock,
    ObservationTimes,
    Period,
    instant,
)

#: Quantos eventos por rodada de `executemany`. Maior que o dos fatos de
#: partida porque a linha é menor e o volume é uma ordem de grandeza acima:
#: uma temporada tem centenas de partidas e centenas de MILHARES de eventos.
_EVENTOS_POR_RODADA: Final[int] = 2_000

#: O instante de referência para os carimbos de pipeline reconstruídos na
#: leitura. Ele NÃO descreve quando o evento aconteceu — isso é o `MatchClock`
#: — nem quando a fonte o observou: descreve que esta reconstrução não tem
#: essa informação, e um `now()` aqui faria toda releitura parecer ingestão
#: nova.
_EPOCA: Final = instant(datetime(2000, 1, 1, tzinfo=UTC))

_COLUNAS: Final[str] = (
    "id, match_id, event_type, period, minute, stoppage, sequence, team_id, "
    "player_id, start_x, start_y, end_x, end_y, coordinate_frame, detail, "
    "revision, supersedes_event_id, status, provider_id, source_event_key, "
    "record_ref, license_class, raw_event_type"
)


@final
class PostgresCanonicalEventWriter:
    """A escrita real de eventos no registro canônico."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def persist_events(
        self,
        events: Sequence[CanonicalMatchEvent],
        *,
        build_run_id: str,
        source_keys: Mapping[uuid.UUID, str],
    ) -> Mapping[uuid.UUID, EventBuildRecordStatus]:
        if not events:
            return {}
        desfechos: dict[uuid.UUID, EventBuildRecordStatus] = {}
        async with self._db.acquire() as conexao, conexao.transaction():
            for inicio in range(0, len(events), _EVENTOS_POR_RODADA):
                bloco = events[inicio : inicio + _EVENTOS_POR_RODADA]
                # QUAIS JÁ EXISTIAM, ANTES DE ESCREVER. É o que distingue
                # `BUILT` de `REUSED` sem heurística — `ON CONFLICT` não
                # devolve `RETURNING` para o que ele ignorou.
                ja_existiam = {
                    linha["id"]
                    for linha in await conexao.fetch(
                        "SELECT id FROM canonical_match_events WHERE id = ANY($1::uuid[])",
                        [e.id for e in bloco],
                    )
                }
                await conexao.executemany(
                    f"""
                    INSERT INTO canonical_match_events ({_COLUNAS}, created_by_build_run)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                            $13, $14, $15::jsonb, $16, $17, $18, $19, $20, $21,
                            $22, $23, $24)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    [
                        _para_linha(
                            evento,
                            uuid.UUID(build_run_id),
                            source_keys.get(evento.id, str(evento.id)),
                        )
                        for evento in bloco
                    ],
                )
                for evento in bloco:
                    desfechos[evento.id] = (
                        EventBuildRecordStatus.REUSED
                        if evento.id in ja_existiam
                        else EventBuildRecordStatus.BUILT
                    )
        return desfechos

    async def mark_superseded(self, transitions: Sequence[tuple[uuid.UUID, uuid.UUID]]) -> int:
        """`(anterior, sucessor)` → o anterior vira `CORRECTED`.

        A CONDIÇÃO `status = 'ACTIVE'` NÃO É DECORAÇÃO. Um evento já cancelado
        não se corrige — ele não aconteceu —, e a cláusula impede que uma
        segunda leitura do arquivo transforme um cancelamento em correção.
        """
        if not transitions:
            return 0
        async with self._db.acquire() as conexao, conexao.transaction():
            resultado = await conexao.executemany(
                """
                UPDATE canonical_match_events
                SET status = 'CORRECTED'
                WHERE id = $1 AND status = 'ACTIVE'
                """,
                [(anterior,) for anterior, _ in transitions],
            )
        _ = resultado
        return len(transitions)

    async def mark_cancelled(self, event_ids: Sequence[uuid.UUID]) -> int:
        if not event_ids:
            return 0
        async with self._db.acquire() as conexao, conexao.transaction():
            await conexao.execute(
                """
                UPDATE canonical_match_events
                SET status = 'CANCELLED'
                WHERE id = ANY($1::uuid[]) AND status <> 'CANCELLED'
                """,
                list(event_ids),
            )
        return len(event_ids)

    async def events_of_match(
        self, match_id: MatchId, *, include_superseded: bool = False
    ) -> Sequence[CanonicalMatchEvent]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                f"""
                SELECT {_COLUNAS}
                FROM canonical_match_events
                WHERE match_id = $1
                  AND ($2::boolean OR status <> 'CORRECTED')
                ORDER BY {_ORDEM_SQL}
                """,
                match_id.value,
                include_superseded,
            )
        return [_para_evento(linha) for linha in linhas]

    async def existing_ids(self, event_ids: Sequence[uuid.UUID]) -> frozenset[uuid.UUID]:
        if not event_ids:
            return frozenset()
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT id FROM canonical_match_events WHERE id = ANY($1::uuid[])",
                list(event_ids),
            )
        return frozenset(linha["id"] for linha in linhas)


@final
class PostgresCanonicalEventBuildRunRepository:
    """Execuções de canonicalização. Uma concluída é imutável."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def create(self, run: CanonicalEventBuildRun) -> CanonicalEventBuildRun:
        async with self._db.acquire() as conexao:
            await conexao.execute(
                """
                INSERT INTO canonical_event_build_runs (
                    id, dataset_id, quality_run_id, provider_id, scope,
                    policy_version, type_mapping_version, status, started_at,
                    triggered_by, triggered_by_kind
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                uuid.UUID(run.id),
                run.dataset_id.value,
                uuid.UUID(run.quality_run_id) if run.quality_run_id else None,
                str(run.provider_id),
                run.scope.value,
                run.policy_version,
                run.type_mapping_version,
                run.status.value,
                run.started_at,
                run.triggered_by.id,
                run.triggered_by.kind.value,
            )
        return run

    async def finish(self, run: CanonicalEventBuildRun) -> bool:
        """A ÚNICA escrita sobre uma execução, e ela é condicional ao estado."""
        async with self._db.acquire() as conexao:
            resultado = await conexao.execute(
                """
                UPDATE canonical_event_build_runs
                SET status = $2, completed_at = $3, failure_reason = $4,
                    records_read = $5, events_built = $6, events_reused = $7,
                    events_skipped = $8, events_review_required = $9,
                    events_failed = $10
                WHERE id = $1 AND status = 'RUNNING'
                """,
                uuid.UUID(run.id),
                run.status.value,
                run.completed_at,
                run.failure_reason,
                run.counts.records_read,
                run.counts.events_built,
                run.counts.events_reused,
                run.counts.events_skipped,
                run.counts.events_review_required,
                run.counts.events_failed,
            )
        partes = str(resultado).split()
        return bool(partes and partes[-1] == "1")

    async def by_id(self, run_id: str) -> CanonicalEventBuildRun | None:
        async with self._db.acquire() as conexao:
            linha = await conexao.fetchrow(
                f"SELECT {_COLUNAS_DE_EXECUCAO} FROM canonical_event_build_runs WHERE id = $1",
                uuid.UUID(run_id),
            )
        return _para_execucao(linha) if linha else None

    async def for_dataset(
        self, dataset_id: DatasetId, *, limit: int = 20
    ) -> Sequence[CanonicalEventBuildRun]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                f"SELECT {_COLUNAS_DE_EXECUCAO} FROM canonical_event_build_runs "
                "WHERE dataset_id = $1 ORDER BY started_at DESC LIMIT $2",
                dataset_id.value,
                limit,
            )
        return [_para_execucao(linha) for linha in linhas]


@final
class PostgresEventBuildRecordRepository:
    """A linhagem por evento. APPEND-ONLY — não há `update` aqui."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def append_many(self, records: Sequence[EventBuildRecord]) -> int:
        if not records:
            return 0
        async with self._db.acquire() as conexao, conexao.transaction():
            for inicio in range(0, len(records), _EVENTOS_POR_RODADA):
                bloco = records[inicio : inicio + _EVENTOS_POR_RODADA]
                await conexao.executemany(
                    """
                    INSERT INTO canonical_event_build_records (
                        id, build_run_id, match_id, source_key, record_ref,
                        status, event_id, reason, raw_event_type, detail
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (build_run_id, source_key) DO NOTHING
                    """,
                    [
                        (
                            uuid.UUID(r.id),
                            uuid.UUID(r.build_run_id),
                            r.match_id.value,
                            r.source_key,
                            r.record_ref,
                            r.status.value,
                            r.event_id,
                            r.reason.value if r.reason else None,
                            r.raw_type,
                            r.detail,
                        )
                        for r in bloco
                    ],
                )
        return len(records)

    async def for_match(self, match_id: MatchId) -> Sequence[EventBuildRecord]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT id, build_run_id, match_id, source_key, record_ref, status,
                       event_id, reason, raw_event_type, detail
                FROM canonical_event_build_records
                WHERE match_id = $1
                ORDER BY created_at, source_key
                """,
                match_id.value,
            )
        return [_para_linhagem(linha) for linha in linhas]

    async def by_source_keys(
        self, build_run_id: str, source_keys: Sequence[str]
    ) -> Sequence[EventBuildRecord]:
        if not source_keys:
            return []
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT id, build_run_id, match_id, source_key, record_ref, status,
                       event_id, reason, raw_event_type, detail
                FROM canonical_event_build_records
                WHERE build_run_id = $1 AND source_key = ANY($2::text[])
                ORDER BY source_key
                """,
                uuid.UUID(build_run_id),
                list(source_keys),
            )
        return [_para_linhagem(linha) for linha in linhas]


# ============================================================== mapeamento ==

#: A ORDEM CANÔNICA DE LEITURA, escrita uma vez. Duas cópias em duas consultas
#: divergiriam, e a divergência apareceria como janelas móveis discordando
#: sobre os mesmos fatos.
_ORDEM_SQL: Final[str] = (
    "CASE period "
    "WHEN 'PRE_MATCH' THEN 0 WHEN 'FIRST_HALF' THEN 1 WHEN 'HALF_TIME' THEN 2 "
    "WHEN 'SECOND_HALF' THEN 3 WHEN 'EXTRA_TIME_FIRST' THEN 4 "
    "WHEN 'EXTRA_TIME_BREAK' THEN 5 WHEN 'EXTRA_TIME_SECOND' THEN 6 "
    "WHEN 'PENALTY_SHOOTOUT' THEN 7 ELSE 8 END, "
    "minute, stoppage, sequence, id"
)


_COLUNAS_DE_EXECUCAO: Final[str] = (
    "id, dataset_id, quality_run_id, provider_id, scope, policy_version, "
    "type_mapping_version, status, started_at, completed_at, failure_reason, "
    "records_read, events_built, events_reused, events_skipped, "
    "events_review_required, events_failed, triggered_by, triggered_by_kind"
)


def _para_execucao(linha: Any) -> CanonicalEventBuildRun:
    return CanonicalEventBuildRun(
        id=str(linha["id"]),
        dataset_id=DatasetId(linha["dataset_id"]),
        provider_id=ProviderId(linha["provider_id"]),
        scope=UsageScope(linha["scope"]),
        policy_version=linha["policy_version"],
        type_mapping_version=linha["type_mapping_version"],
        status=RunStatus(linha["status"]),
        started_at=instant(linha["started_at"]),
        triggered_by=Actor(id=linha["triggered_by"], kind=ActorKind(linha["triggered_by_kind"])),
        quality_run_id=(str(linha["quality_run_id"]) if linha["quality_run_id"] else None),
        counts=EventBuildCounts(
            records_read=linha["records_read"],
            events_built=linha["events_built"],
            events_reused=linha["events_reused"],
            events_skipped=linha["events_skipped"],
            events_review_required=linha["events_review_required"],
            events_failed=linha["events_failed"],
        ),
        completed_at=(instant(linha["completed_at"]) if linha["completed_at"] else None),
        failure_reason=linha["failure_reason"],
    )


def _para_linha(
    evento: CanonicalMatchEvent, build_run_id: uuid.UUID, source_key: str
) -> tuple[Any, ...]:
    inicio, fim = evento.start_location, evento.end_location
    algum = inicio if inicio is not None else fim
    referencial = algum.frame.value if algum is not None else None
    return (
        evento.id,
        evento.match_id.value,
        evento.type.value,
        evento.clock.period.value,
        evento.clock.minute,
        evento.clock.stoppage,
        evento.sequence,
        evento.team_id.value if evento.team_id else None,
        evento.player_id.value if evento.player_id else None,
        inicio.x if inicio else None,
        inicio.y if inicio else None,
        fim.x if fim else None,
        fim.y if fim else None,
        referencial,
        _detalhe_para_json(evento.detail),
        evento.revision,
        evento.supersedes,
        evento.status.value,
        str(evento.provenance.provider_id or ""),
        # A CHAVE DO PROVEDOR e o REFERENCIAL DA LINHA são colunas diferentes
        # porque respondem perguntas diferentes: a primeira identifica o
        # evento no vocabulário da fonte, a segunda diz de qual linha ele veio.
        source_key,
        evento.provenance.source_record_id or "",
        evento.provenance.license_class.value,
        evento.type.value,
        build_run_id,
    )


def _detalhe_para_json(detail: EventDetail | None) -> str | None:
    """Serializa o detalhe TIPADO. `kind` diz qual contrato o produziu.

    SEM `kind`, A VOLTA É ADIVINHAÇÃO: um `jsonb` com `outcome` poderia ser
    finalização ou passe, e escolher pelo formato do dicionário quebraria no
    primeiro contrato que ganhasse um campo parecido.
    """
    if detail is None:
        return None
    if isinstance(detail, ShotDetail):
        return json.dumps(
            {
                "kind": "SHOT",
                "outcome": detail.outcome.value,
                "body_part": detail.body_part.value if detail.body_part else None,
                # xG AUSENTE VIRA `null`, e nunca `0`: zero é uma medida.
                "xg": (
                    detail.xg.require("xg")
                    if detail.xg is not None and detail.xg.is_available
                    else None
                ),
                "xg_absent_reason": _motivo_da_ausencia(detail.xg),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    if isinstance(detail, CardDetail):
        return json.dumps(
            {"kind": "CARD", "card_type": detail.card_type.value},
            sort_keys=True,
            separators=(",", ":"),
        )
    if isinstance(detail, SubstitutionDetail):
        return json.dumps(
            {
                "kind": "SUBSTITUTION",
                "player_out": str(detail.player_out),
                "player_in": str(detail.player_in),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    # OS DEMAIS CONTRATOS EXISTEM E NÃO TÊM PAPÉIS SEMÂNTICOS DECLARADOS neste
    # PR. Serializá-los por reflexão produziria um formato que ninguém decidiu.
    return None


def _motivo_da_ausencia(valor: FeatureValue | None) -> str | None:
    """O motivo da ausência do xG, quando há ausência.

    `None` PARA OS DOIS OUTROS CASOS — campo inexistente e valor medido —, e
    a distinção entre eles vive em `xg`: um `null` com motivo é «não publicou»,
    um número é medida, e nenhum motivo com nenhum número é «não trabalha
    com xG».
    """
    if valor is None or valor.is_available:
        return None
    motivo = valor.reason
    return motivo.value if motivo is not None else None


def _detalhe_de_json(bruto: Any) -> EventDetail | None:
    if bruto is None:
        return None
    documento = json.loads(bruto) if isinstance(bruto, str) else dict(bruto)
    tipo = documento.get("kind")
    if tipo == "SHOT":
        return ShotDetail(
            outcome=ShotOutcome(documento["outcome"]),
            body_part=(BodyPart(documento["body_part"]) if documento.get("body_part") else None),
            xg=_xg_de_json(documento),
        )
    if tipo == "CARD":
        return CardDetail(card_type=CardType(documento["card_type"]))
    if tipo == "SUBSTITUTION":
        return SubstitutionDetail(
            player_out=PlayerId(uuid.UUID(documento["player_out"])),
            player_in=PlayerId(uuid.UUID(documento["player_in"])),
        )
    return None


def _xg_de_json(documento: dict[str, Any]) -> FeatureValue | None:
    if documento.get("xg") is not None:
        return FeatureValue.of(float(documento["xg"]))
    motivo = documento.get("xg_absent_reason")
    if motivo is not None:
        return FeatureValue.absent(Unavailability(motivo))
    return None


def _para_evento(linha: Any) -> CanonicalMatchEvent:
    referencial = (
        CoordinateFrame(linha["coordinate_frame"])
        if linha["coordinate_frame"]
        else CoordinateFrame.ATTACKING
    )
    return CanonicalMatchEvent(
        id=linha["id"],
        match_id=MatchId(linha["match_id"]),
        type=EventType(linha["event_type"]),
        clock=MatchClock(
            period=Period(linha["period"]),
            minute=linha["minute"],
            stoppage=linha["stoppage"],
        ),
        sequence=linha["sequence"],
        provenance=DataProvenance(
            source_type=SourceType.OPEN_DATA,
            provider_id=ProviderId(linha["provider_id"]) if linha["provider_id"] else None,
            source_record_id=linha["record_ref"],
            # OS CARIMBOS DE PIPELINE não são reconstruídos a partir de nada:
            # a linha guarda `created_at`, e ele descreve quando NÓS gravamos.
            times=ObservationTimes.at_once(_EPOCA),
            license_class=LicenseClass(linha["license_class"]),
        ),
        quality=DataQuality(
            completeness=1.0, consistency=1.0, freshness=1.0, identity_confidence=1.0
        ),
        team_id=TeamId(linha["team_id"]) if linha["team_id"] else None,
        player_id=PlayerId(linha["player_id"]) if linha["player_id"] else None,
        start_location=(
            PitchCoordinate(x=linha["start_x"], y=linha["start_y"], frame=referencial)
            if linha["start_x"] is not None
            else None
        ),
        end_location=(
            PitchCoordinate(x=linha["end_x"], y=linha["end_y"], frame=referencial)
            if linha["end_x"] is not None
            else None
        ),
        detail=_detalhe_de_json(linha["detail"]),
        revision=linha["revision"],
        supersedes=linha["supersedes_event_id"],
        status=EventStatus(linha["status"]),
    )


def _para_linhagem(linha: Any) -> EventBuildRecord:
    return EventBuildRecord(
        id=str(linha["id"]),
        build_run_id=str(linha["build_run_id"]),
        match_id=MatchId(linha["match_id"]),
        source_key=linha["source_key"],
        record_ref=linha["record_ref"],
        status=EventBuildRecordStatus(linha["status"]),
        event_id=linha["event_id"],
        reason=(EventExclusionReason(linha["reason"]) if linha["reason"] else None),
        raw_type=linha["raw_event_type"],
        detail=linha["detail"],
    )
