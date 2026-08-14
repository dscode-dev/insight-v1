"""Os ports da avaliação de qualidade. Em MASSA, e append-only.

A MESMA DISCIPLINA DO PR-03 (§68, §69). Nenhum método recebe uma partida e
devolve um veredito: todos recebem coleção e devolvem coleção. Um port com
`assessment_for(match_id)` convidaria ao laço por partida, e o laço por
partida é a diferença entre seis consultas por lote e uma por registro.

NADA AQUI TEM `update`. Uma execução concluída e um veredito são imutáveis
(§51): reavaliar sob política nova emite uma execução NOVA, e a anterior fica
exatamente como estava. A única exceção é fechar uma execução em curso, e ela
é condicional ao estado anterior — como toda transição desta base.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from sports_intelligence.domain.quality.assessment import BuildEligibility
from sports_intelligence.domain.quality.policy import HistoricalQualityPolicy
from sports_intelligence.domain.quality.runs import MatchQualityRecord, QualityRun
from sports_intelligence.domain.shared.identity import MatchId


@runtime_checkable
class QualityRunRepositoryPort(Protocol):
    """Execuções de avaliação. Uma concluída é imutável (ADR-0023)."""

    async def create(self, run: QualityRun) -> QualityRun: ...

    async def finish(self, run: QualityRun) -> bool:
        """Fecha a execução SE ela ainda estiver em curso. `False` se não.

        Condicional ao estado anterior: dois workers fechando a mesma execução
        produziriam duas contagens, e a segunda sobrescreveria a primeira.
        """
        ...

    async def by_id(self, run_id: str) -> QualityRun | None: ...

    async def recent(self, *, limit: int = 20) -> Sequence[QualityRun]:
        """As execuções mais recentes. PLURAL é o ponto: a mesma fusão passa
        por várias avaliações com políticas diferentes, e todas coexistem."""
        ...


@runtime_checkable
class QualityAssessmentRepositoryPort(Protocol):
    """Vereditos por partida. APPEND-ONLY — não há `update` neste protocolo."""

    async def append_many(
        self,
        records: Sequence[MatchQualityRecord],
        *,
        policy: HistoricalQualityPolicy,
    ) -> int:
        """Grava um lote. Devolve quantos entraram.

        O NÚMERO IMPORTA: «gravado com sucesso» sem contagem é uma afirmação
        sem medida, e é assim que um lote que entrou pela metade passa por
        completo.

        A POLÍTICA ESTÁ NA ASSINATURA porque a severidade de cada problema é
        DELA e o `QualityIssue` não a carrega (§12). Deixar o adapter escolher
        uma política para carimbar a severidade seria deixá-lo discordar da
        que de fato decidiu o veredito.
        """
        ...

    async def by_run(
        self,
        run_id: str,
        *,
        eligibility: BuildEligibility | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[Sequence[MatchQualityRecord], int]:
        """Uma página de vereditos, e o total. Filtro no BANCO e não em
        Python: carregar dez mil vereditos para mostrar cinquenta traria
        megabytes para uma tela."""
        ...

    async def page_after(
        self, run_id: str, *, limit: int = 500, after_match_id: str | None = None
    ) -> Sequence[MatchQualityRecord]:
        """O próximo lote de vereditos, em ordem de `match_id`.

        PAGINAÇÃO POR CHAVE E NÃO POR `OFFSET`. `OFFSET 9500` faz o banco
        percorrer 9.500 linhas para descartá-las, e o custo cresce com a
        página — que é como uma varredura em lotes vira quadrática sem que
        ninguém perceba.

        É COMO A CONSTRUÇÃO CONSOME A AVALIAÇÃO (§67, §79). Um
        `list(assessments)` de dez mil partidas com vetor, cobertura, licenças
        e problemas é o pico de memória que o PR-03.2 mediu e corrigiu — e ele
        voltaria aqui pela mesma porta.
        """
        ...

    async def by_matches(
        self, run_id: str, match_ids: Sequence[MatchId]
    ) -> Sequence[MatchQualityRecord]:
        """Os vereditos de um lote de partidas, numa consulta."""
        ...
