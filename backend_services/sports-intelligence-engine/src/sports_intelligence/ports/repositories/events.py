"""Os ports da canonicalização de eventos — escrita e linhagem.

POR QUE UM PORT NOVO E NÃO O `CanonicalEventRepositoryPort` DO PR-01. Aquele
existe em `repositories/football.py` desde o PR-01 e nunca teve implementação:
ele declara `append` e `for_match` para um caminho AO VIVO que ainda não
existe. Este descreve a escrita HISTÓRICA em lote, com desfecho por evento e
ordem determinística de leitura — coisas que o outro não pede.

Os dois vão coexistir e não conflitam: um descreve «grave este evento que
acabou de acontecer», o outro «grave estes cinco mil que acabaram de ser
canonicalizados, e me diga o que aconteceu com cada um».

TUDO EM MASSA (§67, §68). Nenhum método recebe um evento: um arquivo de
temporada tem centenas de milhares de linhas, e uma escrita por linha faria a
canonicalização durar horas por um motivo que não é o dado.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from sports_intelligence.domain.events.build import (
    EventBuildRecord,
    EventBuildRecordStatus,
)
from sports_intelligence.domain.events.canonical import CanonicalMatchEvent
from sports_intelligence.domain.events.runs import CanonicalEventBuildRun
from sports_intelligence.domain.shared.identity import DatasetId, MatchId


@runtime_checkable
class CanonicalEventWritePort(Protocol):
    """A escrita real de eventos canônicos no registro."""

    async def persist_events(
        self,
        events: Sequence[CanonicalMatchEvent],
        *,
        build_run_id: str,
        source_keys: Mapping[uuid.UUID, str],
    ) -> Mapping[uuid.UUID, EventBuildRecordStatus]:
        """Grava o lote. Devolve o desfecho POR EVENTO.

        `source_keys` VIAJA SEPARADO DA PROCEDÊNCIA, e a separação é
        deliberada: `DataProvenance.source_record_id` responde «de qual LINHA
        de qual arquivo este fato veio» — é o elo para o byte bruto, e todo
        fato canônico do motor o tem. A chave de origem responde outra coisa:
        «como o PROVEDOR identifica este evento», que é o que torna o
        reprocessamento idempotente (§19).
        As duas coincidem quando a fonte não dá id de evento, e são diferentes
        sempre que ela dá — escrever uma no lugar da outra faz a coluna que
        deveria identificar o evento no vocabulário do provedor guardar um
        número de linha.

        TRÊS DESFECHOS E NENHUM `UPDATE` DESTRUTIVO (§22, §100):

            ausente                  BUILT
            presente e idêntico      REUSED — reprocessamento, mesmo fato
            presente e diferente     FAILED — nada escrito, alguém decide

        O TERCEIRO É O QUE IMPORTA. Um `upsert` responderia «gravado» aos
        três, e o terceiro caso — mesma identidade de provedor, conteúdo
        incompatível, sem semântica de revisão que explique — é exatamente
        aquele em que gravar é o erro (§29).

        A IDENTIDADE É O `id` DERIVADO, e não uma chave de banco: ele é
        `uuid5` sobre `(partida, chave da fonte, revisão)`, então reprocessar
        a mesma fonte reencontra o mesmo evento em vez de criar outro.
        """
        ...

    async def mark_superseded(self, transitions: Sequence[tuple[uuid.UUID, uuid.UUID]]) -> int:
        """Marca predecessores como corrigidos: `(anterior, sucessor)`.

        É A ÚNICA ESCRITA QUE TOCA UM EVENTO JÁ GRAVADO, e ela muda só o
        ESTADO — nunca o fato. `CORRECTED` diz «existe uma versão melhor
        deste»; o conteúdo do anterior permanece exatamente como estava, e é
        isso que faz «o que sabíamos antes» continuar tendo resposta (§22).
        """
        ...

    async def mark_cancelled(self, event_ids: Sequence[uuid.UUID]) -> int:
        """Anula eventos. `CANCELLED` ≠ `CORRECTED` (§23).

        Um gol anulado pelo VAR não é um gol corrigido: o primeiro não
        aconteceu, o segundo aconteceu diferente. Apagar a linha faria «não
        aconteceu» e «nunca foi registrado» virarem a mesma coisa.
        """
        ...

    async def events_of_match(
        self, match_id: MatchId, *, include_superseded: bool = False
    ) -> Sequence[CanonicalMatchEvent]:
        """Os eventos de uma partida, em ordem DETERMINÍSTICA (§65, §66).

        A ORDEM É `(período, minuto, acréscimo, sequência, id)` — imposta por
        `ORDER BY`, nunca herdada da ordem natural do PostgreSQL. Ela será
        essencial ao PR-05: uma janela móvel sobre eventos em ordem instável
        produz números diferentes a cada leitura dos mesmos fatos.

        `include_superseded` DEFAULT `False`: a leitura normal quer a verdade
        reconciliada. As revisões antigas continuam lá e são alcançáveis —
        elas não somem, apenas não aparecem por omissão.
        """
        ...

    async def existing_ids(self, event_ids: Sequence[uuid.UUID]) -> frozenset[uuid.UUID]:
        """Quais destes já estão gravados. UMA consulta para o lote.

        É O QUE DISTINGUE `BUILT` DE `REUSED` sem depender de heurística: o
        `ON CONFLICT` não diz qual linha era nova, e adivinhar pelo estado
        final erraria justamente quando o evento pré-existente fosse idêntico.
        """
        ...


@runtime_checkable
class CanonicalEventBuildRunRepositoryPort(Protocol):
    """Execuções de canonicalização. Uma concluída é imutável (ADR-0024)."""

    async def create(self, run: CanonicalEventBuildRun) -> CanonicalEventBuildRun:
        """Abre a execução ANTES de qualquer evento ser gravado.

        A ORDEM É EXIGIDA PELO BANCO e é a certa por outra razão também:
        `canonical_match_events.created_by_build_run` aponta para cá, então um
        evento gravado antes da execução seria um fato sem quem o produziu.
        """
        ...

    async def finish(self, run: CanonicalEventBuildRun) -> bool:
        """Fecha SE ainda estiver em curso. `False` se não.

        `UPDATE ... WHERE status = 'RUNNING'` — a mesma serialização de toda
        transição desta base desde o PR-02: dois workers fechando a mesma
        execução produziriam duas contagens, e a segunda sobrescreveria a
        primeira em silêncio.
        """
        ...

    async def by_id(self, run_id: str) -> CanonicalEventBuildRun | None: ...

    async def for_dataset(
        self, dataset_id: DatasetId, *, limit: int = 20
    ) -> Sequence[CanonicalEventBuildRun]:
        """As canonicalizações de um dataset, da mais nova para a mais velha."""
        ...


@runtime_checkable
class EventBuildRecordRepositoryPort(Protocol):
    """A linhagem por evento. APPEND-ONLY."""

    async def append_many(self, records: Sequence[EventBuildRecord]) -> int:
        """Grava a linhagem de um lote. Devolve quantos entraram."""
        ...

    async def for_match(self, match_id: MatchId) -> Sequence[EventBuildRecord]:
        """Toda a linhagem de eventos de uma partida, de todas as execuções.

        É A CONSULTA DO §48: «por que este evento entrou» e «por que aquele
        não entrou» têm a mesma resposta aqui — a linha de quem foi excluído
        existe, com motivo, e é o que distingue «não entrou» de «nunca veio».
        """
        ...

    async def by_source_keys(
        self, build_run_id: str, source_keys: Sequence[str]
    ) -> Sequence[EventBuildRecord]:
        """A linhagem de um lote de chaves de origem, numa consulta."""
        ...
