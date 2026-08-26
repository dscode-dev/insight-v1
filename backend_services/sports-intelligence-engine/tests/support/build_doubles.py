"""Os duplos em memória do PR-04.2 — com as MESMAS restrições dos reais.

A ARMADILHA QUE ELES EVITAM é a mesma que `registry_fakes` documenta: um duplo
mais permissivo que o real deixa passar exatamente a classe de erro que o real
bloquearia em produção. Então aqui:

    `finish`                     é condicional ao estado anterior, como o
                                 `UPDATE ... WHERE status = 'RUNNING'`
    `append_many`                é idempotente por chave, como o `ON CONFLICT`
    `upsert_equivalent_matches`  compara equivalência e RECUSA o conflito, em
                                 vez de sobrescrever (§62)
    `persist_odds`               deduplica pela identidade da V1 (§43, §96)

São duplos, não mocks: têm comportamento e são verificados pelo estado final.
Um teste que afirma «chamou `persist_odds` uma vez» continua passando quando
`persist_odds` para de funcionar.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final, final

from sports_intelligence.domain.build.decisions import BuildDecision, FamilyDecision
from sports_intelligence.domain.build.facts import MatchIdentityFacts
from sports_intelligence.domain.build.policy import CanonicalBuildPolicy
from sports_intelligence.domain.build.runs import (
    CanonicalBuildRecord,
    CanonicalBuildRun,
    MatchWriteOutcome,
)
from sports_intelligence.domain.fusion.models import FusionGroup
from sports_intelligence.domain.fusion.runs import FusedMatchCandidate, FusionRun
from sports_intelligence.domain.matches.lineup import Lineup
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.matches.result import MatchResult
from sports_intelligence.domain.odds.models import CanonicalOddsObservation
from sports_intelligence.domain.quality.assessment import BuildEligibility
from sports_intelligence.domain.quality.policy import HistoricalQualityPolicy
from sports_intelligence.domain.quality.runs import MatchQualityRecord, QualityRun
from sports_intelligence.domain.shared.audit import AuditEntry
from sports_intelligence.domain.shared.identity import DatasetId, MatchId, TeamId


@final
class FakeFusionRunRepository:
    """A execução de fusão, em memória. Implementa o port INTEIRO.

    OS MÉTODOS QUE A AVALIAÇÃO NÃO USA TAMBÉM EXISTEM, e têm comportamento:
    um duplo que só implementa o que o teste de hoje chama deixa de satisfazer
    o protocolo — e o checador de tipos passa a aceitar qualquer coisa no
    lugar dele.
    """

    def __init__(self, *runs: FusionRun) -> None:
        self.runs: dict[str, FusionRun] = {r.id: r for r in runs}
        self.groups: dict[str, list[FusionGroup]] = {}
        self.candidates: dict[str, list[FusedMatchCandidate]] = {}

    async def create(self, run: FusionRun) -> FusionRun:
        self.runs[run.id] = run
        return run

    async def finish(self, run: FusionRun) -> bool:
        atual = self.runs.get(run.id)
        if atual is None or atual.status.is_terminal:
            return False
        self.runs[run.id] = run
        return True

    async def by_id(self, run_id: str) -> FusionRun | None:
        return self.runs.get(run_id)

    async def recent(self, *, limit: int = 20) -> Sequence[FusionRun]:
        return sorted(self.runs.values(), key=lambda r: r.started_at, reverse=True)[:limit]

    async def save_groups(self, run_id: str, groups: Sequence[FusionGroup]) -> int:
        self.groups.setdefault(run_id, []).extend(groups)
        return len(groups)

    async def save_candidates(self, run_id: str, candidates: Sequence[FusedMatchCandidate]) -> int:
        self.candidates.setdefault(run_id, []).extend(candidates)
        return len(candidates)

    async def candidates_of(
        self, run_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[Sequence[dict[str, object]], int]:
        todos = self.candidates.get(run_id, [])
        return [c.as_canonical() for c in todos[offset : offset + limit]], len(todos)

    async def group_ids_of(self, run_id: str) -> dict[str, str]:
        return {str(g.canonical_match_id): g.id for g in self.groups.get(run_id, [])}

    async def conflicts_of(
        self, run_id: str, *, limit: int = 100
    ) -> Sequence[tuple[str, str, str]]:
        return [
            (str(c.canonical_match_id), campo.field_name.value, "")
            for c in self.candidates.get(run_id, [])
            for campo in c.unresolved_conflicts
        ][:limit]


@final
class FakeQualityRunRepository:
    def __init__(self) -> None:
        self.runs: dict[str, QualityRun] = {}
        self.snapshots: dict[str, HistoricalQualityPolicy] = {}

    async def create(self, run: QualityRun) -> QualityRun:
        self.runs[run.id] = run
        return run

    async def save_policy_snapshot(self, run_id: str, policy: HistoricalQualityPolicy) -> None:
        self.snapshots[run_id] = policy

    async def finish(self, run: QualityRun) -> bool:
        """CONDICIONAL AO ESTADO ANTERIOR, como o `UPDATE ... WHERE status =
        'RUNNING'` do real. Um duplo que aceitasse fechar duas vezes deixaria
        passar a corrida que o real bloqueia."""
        atual = self.runs.get(run.id)
        if atual is None or atual.status.is_terminal:
            return False
        self.runs[run.id] = run
        return True

    async def by_id(self, run_id: str) -> QualityRun | None:
        return self.runs.get(run_id)

    async def recent(self, *, limit: int = 20) -> Sequence[QualityRun]:
        return sorted(self.runs.values(), key=lambda r: r.started_at, reverse=True)[:limit]


@final
class FakeQualityAssessmentRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], MatchQualityRecord] = {}
        self.severities: dict[str, str] = {}

    async def append_many(
        self,
        records: Sequence[MatchQualityRecord],
        *,
        policy: HistoricalQualityPolicy,
    ) -> int:
        gravados = 0
        for registro in records:
            chave = (registro.quality_run_id, str(registro.match_id))
            # IDEMPOTENTE POR (execução, partida), como o UNIQUE do real.
            if chave in self.records:
                continue
            self.records[chave] = registro
            for problema in registro.assessment.issues:
                self.severities[f"{registro.id}:{problema.code.value}"] = policy.severity_of(
                    problema.code
                ).name
            gravados += 1
        return gravados

    def _do_run(self, run_id: str) -> list[MatchQualityRecord]:
        return sorted(
            (r for (rid, _), r in self.records.items() if rid == run_id),
            key=lambda r: str(r.match_id),
        )

    async def by_run(
        self,
        run_id: str,
        *,
        eligibility: BuildEligibility | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[Sequence[MatchQualityRecord], int]:
        todos = [
            r for r in self._do_run(run_id) if eligibility is None or r.eligibility is eligibility
        ]
        return todos[offset : offset + limit], len(todos)

    async def page_after(
        self, run_id: str, *, limit: int = 500, after_match_id: str | None = None
    ) -> Sequence[MatchQualityRecord]:
        todos = self._do_run(run_id)
        if after_match_id is not None:
            todos = [r for r in todos if str(r.match_id) > after_match_id]
        return todos[:limit]

    async def by_matches(
        self, run_id: str, match_ids: Sequence[MatchId]
    ) -> Sequence[MatchQualityRecord]:
        alvo = {str(m) for m in match_ids}
        return [r for r in self._do_run(run_id) if str(r.match_id) in alvo]


@final
class FakeCanonicalIdentityReader:
    """As identidades que EXISTEM. As ausentes não voltam — como o real."""

    def __init__(self, *facts: MatchIdentityFacts) -> None:
        self.facts: dict[MatchId, MatchIdentityFacts] = {f.match_id: f for f in facts}

    async def identity_facts(
        self, match_ids: Sequence[MatchId]
    ) -> Mapping[MatchId, MatchIdentityFacts]:
        return {m: self.facts[m] for m in match_ids if m in self.facts}


@final
class FakeCanonicalRegistryWriter:
    """A escrita canônica com a MESMA regra de equivalência do real.

    ELE RECUSA O CONFLITO em vez de sobrescrever (§62). Um duplo que aceitasse
    `last write wins` deixaria passar exatamente o defeito que o real impede —
    e o teste de rejeição de fato conflitante passaria sem provar nada.
    """

    def __init__(self) -> None:
        self.matches: dict[MatchId, Match] = {}
        self.results: dict[MatchId, MatchResult] = {}
        self.lineups: dict[tuple[MatchId, TeamId], Lineup] = {}
        self.odds: dict[tuple[str, ...], CanonicalOddsObservation] = {}

    async def upsert_equivalent_matches(
        self, matches: Sequence[Match]
    ) -> Mapping[MatchId, MatchWriteOutcome]:
        saida: dict[MatchId, MatchWriteOutcome] = {}
        for partida in matches:
            existente = self.matches.get(partida.id)
            if existente is None:
                self.matches[partida.id] = partida
                saida[partida.id] = MatchWriteOutcome.INSERTED
            elif _estrutural(existente) == _estrutural(partida):
                saida[partida.id] = MatchWriteOutcome.REUSED_EQUIVALENT
            else:
                saida[partida.id] = MatchWriteOutcome.CONFLICT
        return saida

    async def persist_results(
        self, results: Sequence[tuple[MatchId, MatchResult]]
    ) -> Mapping[MatchId, MatchWriteOutcome]:
        saida: dict[MatchId, MatchWriteOutcome] = {}
        for identificador, resultado in results:
            existente = self.results.get(identificador)
            if existente is None:
                self.results[identificador] = resultado
                saida[identificador] = MatchWriteOutcome.INSERTED
            elif existente == resultado:
                saida[identificador] = MatchWriteOutcome.REUSED_EQUIVALENT
            else:
                saida[identificador] = MatchWriteOutcome.CONFLICT
        return saida

    async def persist_lineups(
        self, lineups: Sequence[Lineup]
    ) -> Mapping[MatchId, MatchWriteOutcome]:
        saida: dict[MatchId, MatchWriteOutcome] = {}
        for escalacao in lineups:
            chave = (escalacao.match_id, escalacao.team_id)
            desfecho = (
                MatchWriteOutcome.REUSED_EQUIVALENT
                if chave in self.lineups
                else MatchWriteOutcome.INSERTED
            )
            self.lineups.setdefault(chave, escalacao)
            saida[escalacao.match_id] = desfecho
        return saida

    async def persist_odds(
        self, observations: Sequence[CanonicalOddsObservation]
    ) -> Mapping[MatchId, MatchWriteOutcome]:
        saida: dict[MatchId, MatchWriteOutcome] = {}
        for observacao in observations:
            chave = tuple(str(p) for p in observacao.identity)
            existente = self.odds.get(chave)
            if existente is None:
                self.odds[chave] = observacao
                atual = MatchWriteOutcome.INSERTED
            elif existente.decimal_odds == observacao.decimal_odds:
                atual = MatchWriteOutcome.REUSED_EQUIVALENT
            else:
                atual = MatchWriteOutcome.CONFLICT
            anterior = saida.get(observacao.match_id)
            saida[observacao.match_id] = (
                atual if anterior is None else min(atual, anterior, key=_gravidade)
            )
        return saida


@final
class FakeCanonicalBuildRunRepository:
    def __init__(self) -> None:
        self.runs: dict[str, CanonicalBuildRun] = {}
        self.snapshots: dict[str, CanonicalBuildPolicy] = {}

    async def create(self, run: CanonicalBuildRun) -> CanonicalBuildRun:
        self.runs[run.id] = run
        return run

    async def save_policy_snapshot(self, run_id: str, policy: CanonicalBuildPolicy) -> None:
        self.snapshots[run_id] = policy

    async def finish(self, run: CanonicalBuildRun) -> bool:
        atual = self.runs.get(run.id)
        if atual is None or atual.status.is_terminal:
            return False
        self.runs[run.id] = run
        return True

    async def by_id(self, run_id: str) -> CanonicalBuildRun | None:
        return self.runs.get(run_id)

    async def for_quality_run(
        self, quality_run_id: str, *, limit: int = 20
    ) -> Sequence[CanonicalBuildRun]:
        return [r for r in self.runs.values() if r.quality_run_id == quality_run_id][:limit]


@final
class FakeCanonicalBuildRecordRepository:
    def __init__(self) -> None:
        self.records: list[CanonicalBuildRecord] = []
        self.families: dict[tuple[str, str], list[FamilyDecision]] = {}

    async def append_many(self, records: Sequence[CanonicalBuildRecord]) -> int:
        vistos = {(r.build_run_id, str(r.match_id), r.fact_type) for r in self.records}
        novos = [r for r in records if (r.build_run_id, str(r.match_id), r.fact_type) not in vistos]
        self.records.extend(novos)
        return len(novos)

    async def by_run(
        self, run_id: str, *, limit: int = 200, offset: int = 0
    ) -> tuple[Sequence[CanonicalBuildRecord], int]:
        todos = [r for r in self.records if r.build_run_id == run_id]
        return todos[offset : offset + limit], len(todos)

    async def for_match(self, match_id: MatchId) -> Sequence[CanonicalBuildRecord]:
        return [r for r in self.records if r.match_id == match_id]

    async def record_family_decisions(self, run_id: str, decisions: Sequence[BuildDecision]) -> int:
        total = 0
        for decisao in decisions:
            self.families[run_id, str(decisao.match_id)] = list(decisao.families)
            total += len(decisao.families)
        return total

    async def family_decisions_of(self, run_id: str, match_id: MatchId) -> Sequence[FamilyDecision]:
        return self.families.get((run_id, str(match_id)), [])


@final
class FakeAudit:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)

    async def recent_for_dataset(
        self, dataset_id: DatasetId, *, limit: int = 50
    ) -> Sequence[AuditEntry]:
        return [e for e in self.entries if e.dataset_id == dataset_id][:limit]

    def actions(self) -> list[str]:
        return [e.action.value for e in self.entries]


def _estrutural(match: Match) -> tuple[object, ...]:
    return (
        match.competition_id,
        match.season_id,
        match.home_team_id,
        match.away_team_id,
        match.scheduled_kickoff,
        match.stage,
    )


_GRAVIDADE: Final[dict[MatchWriteOutcome, int]] = {
    MatchWriteOutcome.CONFLICT: 0,
    MatchWriteOutcome.REUSED_EQUIVALENT: 1,
    MatchWriteOutcome.INSERTED: 2,
}


def _gravidade(desfecho: MatchWriteOutcome) -> int:
    return _GRAVIDADE[desfecho]
