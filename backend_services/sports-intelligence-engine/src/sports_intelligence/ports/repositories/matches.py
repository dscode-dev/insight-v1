"""O que o domínio precisa saber sobre partidas para funcionar.

INTERFACE PEQUENA, DE PROPÓSITO. A tentação é oferecer `find_by(**kwargs)` e
resolver tudo; o custo é que o port deixa de dizer o que o domínio realmente
usa, e qualquer adapter passa a precisar suportar qualquer consulta.

`historical_candidates` É O MÉTODO QUE CARREGA O INVARIANTE. Ele existe
separado de uma busca genérica justamente para que o filtro de
`HISTORICAL_ACTIVE` (ADR-0007) esteja embutido no contrato, e não dependa de
cada chamador lembrar de aplicá-lo.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from sports_intelligence.domain.matches.lifecycle import MatchLifecycle
from sports_intelligence.domain.shared.identity import CompetitionId, MatchId
from sports_intelligence.domain.shared.temporal import Instant


@runtime_checkable
class MatchRepositoryPort(Protocol):
    async def get_lifecycle(self, match_id: MatchId) -> MatchLifecycle | None:
        """O estado atual, ou None se a partida não existe."""
        ...

    async def record_transition(
        self,
        match_id: MatchId,
        *,
        from_state: MatchLifecycle,
        to_state: MatchLifecycle,
        at: Instant,
        reason: str,
    ) -> None:
        """Grava a transição E o novo estado, na mesma operação.

        Separá-los abriria a janela em que o estado mudou sem registro do
        porquê — que é exatamente o que se procura durante um incidente.
        """
        ...

    async def historical_candidates(
        self,
        *,
        competition_id: CompetitionId,
        before: Instant,
        limit: int,
    ) -> Sequence[MatchId]:
        """Partidas que PODEM alimentar retrieval histórico.

        DUAS TRAVAS NO CONTRATO, e as duas são obrigatórias na implementação:

        1. só `HISTORICAL_ACTIVE` (ADR-0007);
        2. só anteriores a `before` — o corte é o instante da consulta, e
           incluir o futuro é vazamento temporal, o mesmo defeito por outra
           porta.
        """
        ...
