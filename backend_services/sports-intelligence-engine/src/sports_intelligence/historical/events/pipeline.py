"""A canonicalização de UM lote — cada estágio separado e testável (§79).

    resolver referências   →   decidir elegibilidade   →   construir   →   linhagem

O QUE ESTE MÓDULO É: a costura entre os quatro, sem infraestrutura. Ele recebe
os registros já lidos e as traduções já buscadas, e devolve os eventos prontos
mais o rastro do que aconteceu com cada linha. Persistir é do caso de uso.

A SEQUÊNCIA CANÔNICA É ATRIBUÍDA AQUI, e é uma das duas coisas que só existem
no lote inteiro: um evento sozinho não sabe que posição ocupa dentro do
período. A outra é a cadeia de revisão — uma correção precisa encontrar o
predecessor, e ele pode estar na mesma leva.

O QUE ELE NÃO FAZ: não fala com banco, não lê arquivo, não decide política.
É o que permite testá-lo com dez registros em memória e provar as quatro
propriedades que importam sem subir nada.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import final

from sports_intelligence.domain.events.build import (
    EventBuildRecord,
    EventBuildRecordStatus,
    EventExclusionReason,
    EventOutcome,
    source_key_of,
)
from sports_intelligence.domain.events.canonical import CanonicalMatchEvent
from sports_intelligence.domain.events.records import (
    EventRevisionKind,
    HistoricalEventRecord,
    ordering_key,
)
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.provenance import (
    DataProvenance,
    LicenseClass,
    SourceType,
)
from sports_intelligence.domain.shared.temporal import Instant, ObservationTimes
from sports_intelligence.historical.events.builder import (
    CanonicalEventBuilder,
    canonical_event_id,
)
from sports_intelligence.historical.events.eligibility import (
    EventEligibilityEvaluator,
)
from sports_intelligence.historical.events.references import EventReferences


@final
@dataclass(frozen=True, slots=True)
class EventBatchOutcome:
    """O que saiu de um lote: eventos, linhagem e transições de revisão."""

    events: tuple[CanonicalMatchEvent, ...] = ()
    records: tuple[EventBuildRecord, ...] = ()
    #: `(predecessor, sucessor)` — o anterior vira `CORRECTED` (§22).
    superseded: tuple[tuple[uuid.UUID, uuid.UUID], ...] = ()
    #: Os que a fonte ANULOU. `CANCELLED` ≠ `CORRECTED` (§23).
    cancelled: tuple[uuid.UUID, ...] = ()
    #: `id canônico → chave da fonte`. Ela não cabe na procedência — que
    #: responde «de qual linha veio» —, e sem ela a coluna que identifica o
    #: evento no vocabulário do provedor guardaria um número de linha (§19).
    source_keys: dict[uuid.UUID, str] = field(default_factory=dict)
    records_read: int = 0


@final
@final
@dataclass(frozen=True, slots=True)
class PredecessorRef:
    """O MÍNIMO que a cadeia de revisão precisa saber do evento anterior.

    A cadeia consulta duas coisas e só duas: QUAL evento a correção substitui
    (`id`) e EM QUE REVISÃO ele está (`revision`, para que a próxima seja a
    seguinte). Guardar o evento inteiro para responder isso seria pagar o
    custo de todo o resto — procedência, detalhes tipados, coordenadas — por
    um dado que nunca é lido.
    """

    id: uuid.UUID
    revision: int


@dataclass(slots=True)
class EventBatchCanonicalizer:
    """Canonicaliza um lote. Sem estado entre lotes, exceto a sequência.

    A SEQUÊNCIA É POR `(partida, período)` E SOBREVIVE ENTRE LOTES, porque um
    período pode atravessar a fronteira do lote. Se ela reiniciasse, dois
    eventos do mesmo tempo teriam a mesma posição — e a ordem determinística
    que o PR-05 precisa deixaria de existir exatamente onde o lote quebrou.
    """

    evaluator: EventEligibilityEvaluator
    builder: CanonicalEventBuilder
    build_run_id: str
    ingested_at: Instant
    _proxima_sequencia: dict[tuple[str, str], int] = field(default_factory=dict)
    #: O QUE JÁ FOI CONSTRUÍDO NESTA EXECUÇÃO, por chave de origem.
    #:
    #: ELE ATRAVESSA LOTES, e essa é a razão de existir. Uma fonte emite o gol
    #: na linha 1 e a correção na linha 200; com lote de 100 os dois caem em
    #: leituras diferentes, e um índice local ao lote faria a correção não
    #: encontrar o predecessor — virando `DANGLING_REVISION` por um motivo que
    #: é do arnês, não do dado. O tamanho do lote deixaria de ser detalhe de
    #: execução e passaria a mudar o resultado (§104).
    #:
    #: ELE GUARDA A REFERÊNCIA, NÃO O EVENTO, e a diferença é de ordem de
    #: grandeza: reter o `CanonicalMatchEvent` inteiro faria o pico de memória
    #: seguir o VOLUME DO ARQUIVO em vez do tamanho do lote — cem mil eventos
    #: com procedência, relógio, coordenadas e detalhes tipados custam duas
    #: ordens de grandeza mais que cem mil pares `(id, revisão)`, que é tudo
    #: que a cadeia de revisão realmente consulta (§69, §109).
    _construidos: dict[str, PredecessorRef] = field(default_factory=dict)

    def canonicalize(
        self,
        records: Sequence[HistoricalEventRecord],
        *,
        references: EventReferences,
        eligible_matches: frozenset[MatchId],
        license_class: LicenseClass,
    ) -> EventBatchOutcome:
        if not records:
            return EventBatchOutcome()

        # A ORDEM CANÔNICA VEM ANTES DE TUDO. A sequência atribuída depende
        # dela, e atribuí-la sobre a ordem do arquivo faria dois
        # processamentos do mesmo dado produzirem sequências diferentes (§17).
        ordenados = sorted(records, key=ordering_key)

        eventos: list[CanonicalMatchEvent] = []
        chaves: dict[uuid.UUID, str] = {}
        linhagem: list[EventBuildRecord] = []
        substituidos: list[tuple[uuid.UUID, uuid.UUID]] = []
        anulados: list[uuid.UUID] = []
        vistos: set[str] = set()

        for registro in ordenados:
            chave = source_key_of(registro)

            # DUPLICATA DENTRO DO MESMO LOTE (§28). A mesma chave duas vezes
            # com o mesmo conteúdo é idempotência; construir as duas produziria
            # o mesmo id derivado e a segunda seria descartada pelo banco em
            # silêncio — melhor registrar que ela foi vista.
            if chave in vistos:
                linhagem.append(
                    self._linha(
                        registro,
                        chave,
                        references,
                        EventBuildRecordStatus.SKIPPED,
                        reason=EventExclusionReason.IDENTITY_CONFLICT,
                        detail="chave de origem repetida dentro do mesmo lote",
                    )
                )
                continue
            vistos.add(chave)

            veredito = self.evaluator.evaluate(
                registro,
                references=references,
                eligible_matches=eligible_matches,
                license_class=license_class,
            )
            if veredito.outcome is not EventOutcome.INCLUDED:
                linhagem.append(
                    self._linha(
                        registro,
                        chave,
                        references,
                        EventBuildRecordStatus.REVIEW_REQUIRED
                        if veredito.outcome is EventOutcome.REVIEW_REQUIRED
                        else EventBuildRecordStatus.SKIPPED,
                        reason=veredito.reason,
                        detail=veredito.detail,
                    )
                )
                continue

            partida = references.match_for(registro)
            assert partida is not None  # a elegibilidade já garantiu
            tipo = self.evaluator.types.resolve(registro.raw_type).require()

            predecessor = self._predecessor(registro, self._construidos, partida)
            if registro.revision.references_predecessor and predecessor is None:
                linhagem.append(
                    self._linha(
                        registro,
                        chave,
                        references,
                        EventBuildRecordStatus.REVIEW_REQUIRED,
                        reason=EventExclusionReason.DANGLING_REVISION,
                        detail=(
                            f"revisa {registro.supersedes_reference!r}, que não está "
                            "neste conjunto — aplicar a correção sem o anterior "
                            "deixaria a cadeia quebrada"
                        ),
                    )
                )
                continue

            # O CANCELAMENTO NÃO CRIA EVENTO NOVO (§23). Ele anula o que já
            # existe: um gol anulado pelo VAR não é um gol corrigido, e criar
            # uma revisão «cancelada» faria o registro ter dois gols, um deles
            # anulado — quando houve um só, que não valeu.
            if registro.revision is EventRevisionKind.CANCELLATION:
                assert predecessor is not None
                anulados.append(predecessor.id)
                linhagem.append(
                    self._linha(
                        registro,
                        chave,
                        references,
                        EventBuildRecordStatus.REUSED,
                        event_id=predecessor.id,
                        detail="cancelamento aplicado ao evento anterior",
                    )
                )
                continue

            revisao = 1 if predecessor is None else predecessor.revision + 1
            evento = self.builder.build(
                registro,
                match_id=partida,
                event_type=tipo,
                references=references,
                provenance=self._procedencia(registro, license_class),
                source_key=chave,
                sequence=self._sequencia(partida, registro),
                revision=revisao,
                supersedes=predecessor.id if predecessor is not None else None,
            )
            eventos.append(evento)
            chaves[evento.id] = chave
            self._construidos[chave] = PredecessorRef(id=evento.id, revision=revisao)
            if predecessor is not None:
                substituidos.append((predecessor.id, evento.id))
            linhagem.append(
                self._linha(
                    registro,
                    chave,
                    references,
                    EventBuildRecordStatus.BUILT,
                    event_id=evento.id,
                )
            )

        return EventBatchOutcome(
            events=tuple(eventos),
            records=tuple(linhagem),
            superseded=tuple(substituidos),
            cancelled=tuple(anulados),
            source_keys=chaves,
            records_read=len(records),
        )

    # ---------------------------------------------------------- internos --

    def _sequencia(self, match_id: MatchId, record: HistoricalEventRecord) -> int:
        """A posição do evento DENTRO do período. Monotônica por partida.

        ELA NÃO É A SEQUÊNCIA DO PROVEDOR, e não deve ser: provedores numeram
        a partir de zero, de um, ou globalmente por temporada. O que o domínio
        precisa é uma ordem local densa, e a do provedor já foi usada — no
        desempate de `ordering_key`, que é onde ela vale.
        """
        chave = (str(match_id), record.clock.period.value)
        proxima = self._proxima_sequencia.get(chave, 0)
        self._proxima_sequencia[chave] = proxima + 1
        return proxima

    @staticmethod
    def _predecessor(
        record: HistoricalEventRecord,
        por_chave: dict[str, PredecessorRef],
        match_id: MatchId,
    ) -> PredecessorRef | None:
        """O evento que esta linha revisa, quando ele está neste conjunto.

        ELE É PROCURADO NO LOTE, e não no banco: uma fonte que emite o evento
        e a correção no mesmo arquivo é o caso comum, e ir ao banco por linha
        seria o N+1 que o §68 proíbe. Um predecessor de OUTRA execução vira
        `DANGLING_REVISION` — honesto: este lote não sabe o que houve antes.
        """
        if not record.revision.references_predecessor:
            return None
        chave = record.supersedes_key
        if chave is None:
            return None
        do_lote = por_chave.get(chave)
        if do_lote is not None:
            return do_lote
        # Ainda pode estar no registro: o id é DERIVADO, então dá para
        # calculá-lo sem consultar. Só a revisão 1 é procurável assim — uma
        # cadeia mais longa exigiria saber a revisão atual, e isso é banco.
        _ = canonical_event_id(source_key=chave, revision=1, match_id=match_id)
        return None

    def _procedencia(
        self, record: HistoricalEventRecord, license_class: LicenseClass
    ) -> DataProvenance:
        return DataProvenance(
            source_type=SourceType.OPEN_DATA,
            provider_id=record.provider_id,
            source_record_id=str(record.record_ref),
            times=ObservationTimes.at_once(self.ingested_at),
            license_class=license_class,
        )

    def _linha(
        self,
        record: HistoricalEventRecord,
        source_key: str,
        references: EventReferences,
        status: EventBuildRecordStatus,
        *,
        event_id: uuid.UUID | None = None,
        reason: EventExclusionReason | None = None,
        detail: str | None = None,
    ) -> EventBuildRecord:
        """A linha de linhagem. Ela existe MESMO para o que não entrou (§48).

        `match_id` USA UM PLACEHOLDER quando a partida não resolveu, e a
        alternativa seria não gravar a linha — que é justamente o caso em que
        «por que este evento sumiu» mais precisa de resposta.
        """
        partida = references.match_for(record) or _PARTIDA_DESCONHECIDA
        return EventBuildRecord(
            id=str(uuid.uuid4()),
            build_run_id=self.build_run_id,
            match_id=partida,
            source_key=source_key,
            record_ref=str(record.record_ref),
            status=status,
            event_id=event_id,
            reason=reason,
            raw_type=record.raw_type,
            detail=detail,
        )


#: O `MatchId` das linhas cuja partida não resolveu. Ele é derivado e fixo, e
#: NÃO tem linha em `matches` — por isso a tabela de linhagem não tem chave
#: estrangeira para lá: registrar a recusa é mais importante que a integridade
#: referencial de uma linha que existe justamente para dizer que não há partida.
_PARTIDA_DESCONHECIDA: MatchId = MatchId.derive("pr0441", "partida-nao-resolvida")
