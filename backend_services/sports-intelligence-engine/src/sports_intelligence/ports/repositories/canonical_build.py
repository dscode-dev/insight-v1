"""Os ports da construção canônica — incluindo o primeiro de ESCRITA.

A DÍVIDA DO PR-03 ENTRA AQUI (§25). `CanonicalRegistryPort` só lia, e era
deliberado: povoar o registro canônico sem passar pela qualidade seria a porta
aberta que este PR existe para fechar. Agora a porta existe, e ela tem
fechadura: `CanonicalRegistryWritePort` recebe agregados de domínio já
construídos a partir de uma `BuildDecision` — nunca `dict`, nunca campos
soltos.

`upsert` NÃO É O VERBO, e a escolha da palavra importa (§62, §70). Um `upsert`
responde «gravado» a três situações diferentes, e a terceira — o fato já
existe e DISCORDA — é aquela em que gravar é o erro. Os métodos aqui devolvem
`MatchWriteOutcome` por partida justamente para que `last write wins` não
tenha como acontecer por omissão.

TUDO EM MASSA (§68). Nenhum método recebe um fato: todos recebem a coleção.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from sports_intelligence.domain.build.decisions import BuildDecision, FamilyDecision
from sports_intelligence.domain.build.facts import MatchIdentityFacts
from sports_intelligence.domain.build.runs import (
    CanonicalBuildRecord,
    CanonicalBuildRun,
    MatchWriteOutcome,
)
from sports_intelligence.domain.matches.lineup import Lineup
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.matches.result import MatchResult
from sports_intelligence.domain.odds.models import CanonicalOddsObservation
from sports_intelligence.domain.shared.identity import MatchId


@runtime_checkable
class CanonicalIdentityReaderPort(Protocol):
    """A identidade canônica já resolvida das partidas de um lote.

    ELE EXISTE PARA QUE O BUILD NÃO INVENTE IDENTIDADE (§27). O construtor de
    partida exige `MatchIdentityFacts`, e a única forma de obtê-los é
    perguntando ao registro o que já foi resolvido. Uma partida que não volta
    daqui não tem identidade — e o build a recusa em vez de criá-la.
    """

    async def identity_facts(
        self, match_ids: Sequence[MatchId]
    ) -> Mapping[MatchId, MatchIdentityFacts]:
        """Os fatos de identidade de um lote, numa consulta.

        AS AUSENTES SIMPLESMENTE NÃO VOLTAM. Devolver um objeto vazio para
        elas obrigaria todo chamador a distinguir «vazio» de «ausente», e
        alguém erraria — o mapa incompleto é o tipo dizendo a verdade.
        """
        ...


@runtime_checkable
class CanonicalRegistryWritePort(Protocol):
    """A escrita real no registro canônico. Equivalência antes de reuso.

    CADA MÉTODO DEVOLVE O DESFECHO POR PARTIDA, e é o que torna o §62
    verificável: quem chamou sabe se inseriu, reaproveitou ou bateu num
    conflito, e o registro de linhagem grava qual dos três.
    """

    async def upsert_equivalent_matches(
        self, matches: Sequence[Match]
    ) -> Mapping[MatchId, MatchWriteOutcome]:
        """Insere as que faltam, reaproveita as equivalentes, recusa as demais.

        TRÊS DESFECHOS E NENHUM `UPDATE` (§61, §62, §63):

            ausente                  INSERTED
            presente e idêntica      REUSED_EQUIVALENT — nova linhagem, mesmo fato
            presente e diferente     CONFLICT — nada escrito, alguém decide

        A EQUIVALÊNCIA É ESTRUTURAL: competição, temporada, times, horário
        marcado e fase. `lifecycle` e `venue` mudam legitimamente entre
        execuções e não entram na comparação — exigi-los faria toda reingestão
        virar conflito.
        """
        ...

    async def persist_results(
        self, results: Sequence[tuple[MatchId, MatchResult]]
    ) -> Mapping[MatchId, MatchWriteOutcome]:
        """Grava resultados. Mesma regra de equivalência das partidas.

        SEPARADO DE `Match` PORQUE O FATO É OUTRO (§26, §33). Uma partida pode
        existir sem resultado; um resultado nunca existe sem partida. Juntá-los
        num método faria o segundo caso ser possível de expressar.
        """
        ...

    async def persist_lineups(
        self, lineups: Sequence[Lineup]
    ) -> Mapping[MatchId, MatchWriteOutcome]:
        """Grava escalações iniciais. Uma por time e por partida."""
        ...

    async def persist_odds(
        self, observations: Sequence[CanonicalOddsObservation]
    ) -> Mapping[MatchId, MatchWriteOutcome]:
        """Grava o CONJUNTO de observações. Nunca uma cotação consolidada.

        A IDENTIDADE É (partida, casa, mercado, seleção, linha) — a do
        PR-03.2, preservada (§43). Duas casas cotando o mesmo jogo produzem
        duas linhas, e é exatamente isso que precisa sobreviver ao banco.
        """
        ...


@runtime_checkable
class CanonicalBuildRunRepositoryPort(Protocol):
    """Execuções de construção. Uma concluída é imutável (ADR-0024)."""

    async def create(self, run: CanonicalBuildRun) -> CanonicalBuildRun: ...

    async def finish(self, run: CanonicalBuildRun) -> bool:
        """Fecha SE ainda estiver em curso. `False` se não."""
        ...

    async def by_id(self, run_id: str) -> CanonicalBuildRun | None: ...

    async def for_quality_run(
        self, quality_run_id: str, *, limit: int = 20
    ) -> Sequence[CanonicalBuildRun]:
        """As construções de uma avaliação, da mais nova para a mais velha.

        PLURAL É O PONTO (§52). A mesma avaliação alimenta um build de
        pesquisa e um comercial, e os dois coexistem com resultados diferentes
        e igualmente corretos.
        """
        ...


@runtime_checkable
class CanonicalBuildRecordRepositoryPort(Protocol):
    """A linhagem por fato. APPEND-ONLY."""

    async def append_many(self, records: Sequence[CanonicalBuildRecord]) -> int: ...

    async def by_run(
        self, run_id: str, *, limit: int = 200, offset: int = 0
    ) -> tuple[Sequence[CanonicalBuildRecord], int]: ...

    async def for_match(self, match_id: MatchId) -> Sequence[CanonicalBuildRecord]:
        """TODA a linhagem de uma partida, de todas as execuções.

        É A CONSULTA DO §50 E DO §97: «por que este Match está no corpus» e
        «quantos builds o produziram». Filtrar por execução aqui esconderia
        justamente a coexistência que o PR precisa provar.
        """
        ...

    async def record_family_decisions(self, run_id: str, decisions: Sequence[BuildDecision]) -> int:
        """Grava a decisão POR FAMÍLIA de cada partida (§20).

        SEPARADA DO REGISTRO DE FATO porque a granularidade é outra: um fato é
        por tipo, uma decisão de família é por partida. Repetir as decisões em
        cada linha de fato duplicaria o motivo e faria as cópias divergirem.
        """
        ...

    async def family_decisions_of(self, run_id: str, match_id: MatchId) -> Sequence[FamilyDecision]:
        """As decisões por família de uma partida — a resposta do §20.

        «As odds desta partida sumiram?» só tem resposta honesta com estas
        linhas: elas dizem `EXCLUDED`, `LICENSE_POLICY` e `RESEARCH_ONLY`, que
        juntos explicam o que aconteceu sem ninguém precisar reexecutar nada.
        """
        ...
