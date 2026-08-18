"""A montagem de UMA partida — o plano, e os registros de linhagem que sobram.

DUAS ETAPAS, E A SEPARAÇÃO É O QUE TORNA O §65 POSSÍVEL:

    planejar    decidir e CONSTRUIR os objetos de domínio, sem tocar o banco
    registrar   depois de a escrita voltar, dizer o que de fato aconteceu

Se o registro de linhagem fosse produzido junto do plano, ele afirmaria
`BUILT` antes de a escrita acontecer — e uma falha no meio deixaria um
`BuildRecord=BUILT` sem os fatos que ele diz ter construído, que é exatamente
a mentira que o §65 proíbe.

O PLANO NÃO É UM `dict[str, Any]` (§29). Ele é um agregado tipado com um campo
por família, e a família ausente é `None` ou tupla vazia — nunca uma chave que
alguém esqueceu de conferir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import final

from sports_intelligence.domain.build.decisions import (
    BuildDecision,
    BuildOutcome,
    CanonicalFactType,
)
from sports_intelligence.domain.build.facts import LineupDraft, MatchIdentityFacts
from sports_intelligence.domain.build.policy import CanonicalBuildPolicy
from sports_intelligence.domain.build.runs import (
    BuildRecordStatus,
    CanonicalBuildRecord,
    MatchWriteOutcome,
    outcome_to_record_status,
)
from sports_intelligence.domain.fusion.runs import FusedMatchCandidate
from sports_intelligence.domain.matches.lineup import Lineup
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.matches.result import MatchResult
from sports_intelligence.domain.odds.models import CanonicalOddsObservation
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.quality.runs import MatchQualityRecord
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.historical.build.builders import (
    CanonicalLineupBuilder,
    CanonicalMatchBuilder,
    CanonicalOddsBuilder,
    CanonicalResultBuilder,
)
from sports_intelligence.historical.build.translation import (
    odds_observations_of,
    read_score_facts,
)

#: A tradução entre um desfecho de escrita e o estado do registro. UMA tabela,
#: porque a mesma tradução escrita em dois pontos divergiria — e a divergência
#: apareceria como uma partida contada como construída num lugar e reusada
#: noutro.
_ESTADO_DA_ESCRITA: dict[MatchWriteOutcome, BuildRecordStatus] = {
    MatchWriteOutcome.INSERTED: BuildRecordStatus.BUILT,
    MatchWriteOutcome.REUSED_EQUIVALENT: BuildRecordStatus.REUSED,
    MatchWriteOutcome.CONFLICT: BuildRecordStatus.FAILED,
}


@final
@dataclass(frozen=True, slots=True)
class MatchBuildInputs:
    """Tudo que a montagem de UMA partida precisa, já carregado em lote."""

    record: MatchQualityRecord
    candidate: FusedMatchCandidate
    #: `None` quando a identidade canônica não existe. O build NÃO a inventa
    #: (§27): identidade é resolução, com evidência e possibilidade de falhar.
    identity: MatchIdentityFacts | None = None
    lineup_drafts: tuple[LineupDraft, ...] = ()

    def __post_init__(self) -> None:
        if self.record.match_id != self.candidate.canonical_match_id:
            raise ValidationError(
                f"avaliação de {self.record.match_id} com candidato de "
                f"{self.candidate.canonical_match_id} — seriam duas partidas "
                "viradas uma"
            )


@final
@dataclass(frozen=True, slots=True)
class MatchBuildPlan:
    """O que ESTA partida vai gravar. Objetos de domínio, nada de banco."""

    decision: BuildDecision
    quality_assessment_id: str
    fusion_group_id: str
    match: Match | None = None
    result: MatchResult | None = None
    lineups: tuple[Lineup, ...] = ()
    odds: tuple[CanonicalOddsObservation, ...] = ()
    #: Por que um fato AUTORIZADO não foi produzido. O caso comum é placar
    #: ausente numa política que o permite: a família entrou, o fato não
    #: existe, e a diferença precisa ficar escrita (§44).
    notes: dict[CanonicalFactType, str] = field(default_factory=dict)

    @property
    def builds_anything(self) -> bool:
        return self.match is not None or bool(self.lineups) or bool(self.odds)


@final
@dataclass(frozen=True, slots=True)
class CanonicalAssembler:
    """Aplica a política e chama os construtores tipados. Não toca no banco.

    NÃO É UM `build_everything` (§29). Ele é um roteador de dez linhas por
    família: pergunta à decisão se a família entra, chama o construtor DELA, e
    guarda o que voltou. Toda a lógica de cada família mora no construtor
    correspondente, e nenhuma delas conhece as outras.
    """

    policy: CanonicalBuildPolicy
    #: `default_factory` E NÃO UMA INSTÂNCIA NO DEFAULT: um objeto criado na
    #: definição da classe é COMPARTILHADO por todas as montagens. Estes
    #: construtores são imutáveis e sem estado, então hoje não haveria dano —
    #: e é justamente por isso que o dia em que um deles ganhar estado seria
    #: silencioso.
    matches: CanonicalMatchBuilder = field(default_factory=CanonicalMatchBuilder)
    results: CanonicalResultBuilder = field(default_factory=CanonicalResultBuilder)
    lineups: CanonicalLineupBuilder = field(default_factory=CanonicalLineupBuilder)
    odds: CanonicalOddsBuilder = field(default_factory=CanonicalOddsBuilder)

    def plan(self, inputs: MatchBuildInputs, *, ingested_at: Instant) -> MatchBuildPlan:
        decisao = self.policy.decide(inputs.record)

        if not decisao.outcome.materializes:
            return MatchBuildPlan(
                decision=decisao,
                quality_assessment_id=inputs.record.id,
                fusion_group_id=inputs.record.fusion_group_id,
            )

        if inputs.identity is None:
            # A IDENTIDADE NÃO EXISTE E O BUILD NÃO A INVENTA (§27). A decisão
            # vira recusa AQUI e não na política, porque a política decide
            # sobre a AVALIAÇÃO — e a ausência do registro canônico é um fato
            # da infraestrutura de leitura, não do veredito de qualidade.
            return MatchBuildPlan(
                decision=_recusar_por_identidade(decisao),
                quality_assessment_id=inputs.record.id,
                fusion_group_id=inputs.record.fusion_group_id,
            )

        anotacoes: dict[CanonicalFactType, str] = {}
        partida = self.matches.build(decision=decisao, identity=inputs.identity)
        resultado = self.results.build(
            decision=decisao, scores=read_score_facts(inputs.candidate)
        )
        if resultado is None:
            anotacoes[CanonicalFactType.MATCH_RESULT] = (
                "placar ausente ou em conflito não resolvido — a partida entra sem "
                "resultado, e a ausência NÃO vira 0-0 (§44)"
            )

        escalacoes = self._escalacoes(decisao, inputs)
        cotacoes = self._cotacoes(decisao, inputs, ingested_at=ingested_at)
        if decisao.includes(CoverageFamily.ODDS) and not cotacoes:
            anotacoes[CanonicalFactType.ODDS_OBSERVATION] = (
                "conjunto de odds sem observação legível"
            )

        return MatchBuildPlan(
            decision=decisao,
            quality_assessment_id=inputs.record.id,
            fusion_group_id=inputs.record.fusion_group_id,
            match=partida,
            result=resultado,
            lineups=escalacoes,
            odds=cotacoes,
            notes=anotacoes,
        )

    def _escalacoes(
        self, decision: BuildDecision, inputs: MatchBuildInputs
    ) -> tuple[Lineup, ...]:
        if not decision.includes(CoverageFamily.LINEUP):
            return ()
        return tuple(
            self.lineups.build(decision=decision, draft=rascunho)
            for rascunho in inputs.lineup_drafts
            # A GUARDA É REDUNDANTE COM A POLÍTICA E FICA (§36). Se um
            # rascunho não resolvido chegasse aqui, o construtor explodiria —
            # e explodir é melhor que inventar, mas pular é melhor que os
            # dois quando a política já disse que a família entra.
            if rascunho.is_fully_resolved
        )

    def _cotacoes(
        self,
        decision: BuildDecision,
        inputs: MatchBuildInputs,
        *,
        ingested_at: Instant,
    ) -> tuple[CanonicalOddsObservation, ...]:
        if not decision.includes(CoverageFamily.ODDS):
            return ()
        conjunto = odds_observations_of(inputs.candidate)
        if conjunto is None:
            return ()
        return self.odds.build(
            decision=decision,
            observations=conjunto,
            match_id=inputs.record.match_id,
            ingested_at=ingested_at,
        )


def _recusar_por_identidade(decision: BuildDecision) -> BuildDecision:
    """Converte uma decisão de construir numa recusa por identidade ausente."""
    from sports_intelligence.domain.build.decisions import (
        FamilyDecision,
        FamilyExclusionReason,
    )

    return BuildDecision.of(
        match_id=decision.match_id,
        outcome=BuildOutcome.SKIP,
        scope=decision.scope,
        build_policy_version=decision.build_policy_version,
        families=tuple(
            FamilyDecision.excluded(d.family, FamilyExclusionReason.UNRESOLVED_IDENTITY)
            if d.outcome.materializes
            else d
            for d in decision.families
        ),
        reason=(
            f"a partida {decision.match_id} não tem identidade canônica resolvida — "
            "o build não a inventa, e criar um `MatchId` aqui produziria uma partida "
            "que nenhuma resolução provou existir (§27)"
        ),
    )


def records_of(
    plan: MatchBuildPlan,
    *,
    build_run_id: str,
    match_outcome: MatchWriteOutcome | None = None,
    result_outcome: MatchWriteOutcome | None = None,
    lineup_outcome: MatchWriteOutcome | None = None,
    odds_outcome: MatchWriteOutcome | None = None,
) -> tuple[CanonicalBuildRecord, ...]:
    """Os registros de linhagem desta partida, DEPOIS de a escrita voltar.

    UM POR FATO, E UM QUANDO NÃO HOUVE FATO. A partida recusada também produz
    registro: sem ele, «o que aconteceu com esta partida» não teria resposta —
    e a ausência de linha é indistinguível de a partida nunca ter sido vista.

    OS DESFECHOS VÊM DE FORA porque quem sabe se o fato foi inserido, reusado
    ou entrou em conflito é o registro canônico — e este módulo afirmar `BUILT`
    sem essa resposta seria a declaração falsa do §66.
    """
    if not plan.decision.outcome.materializes:
        return (
            CanonicalBuildRecord.of(
                build_run_id=build_run_id,
                decision=plan.decision,
                fact_type=CanonicalFactType.MATCH,
                source_fusion_group_id=plan.fusion_group_id,
                quality_assessment_id=plan.quality_assessment_id,
                status=outcome_to_record_status(plan.decision.outcome),
            ),
        )

    registros: list[CanonicalBuildRecord] = []
    if plan.match is not None and match_outcome is not None:
        registros.append(
            _registro(
                plan,
                build_run_id=build_run_id,
                fact_type=CanonicalFactType.MATCH,
                fact_id=str(plan.match.id),
                outcome=match_outcome,
            )
        )
    if plan.result is not None and result_outcome is not None:
        registros.append(
            _registro(
                plan,
                build_run_id=build_run_id,
                fact_type=CanonicalFactType.MATCH_RESULT,
                fact_id=str(plan.decision.match_id),
                outcome=result_outcome,
            )
        )
    elif CanonicalFactType.MATCH_RESULT in plan.notes:
        registros.append(
            CanonicalBuildRecord.of(
                build_run_id=build_run_id,
                decision=plan.decision,
                fact_type=CanonicalFactType.MATCH_RESULT,
                source_fusion_group_id=plan.fusion_group_id,
                quality_assessment_id=plan.quality_assessment_id,
                status=BuildRecordStatus.SKIPPED,
                reason=plan.notes[CanonicalFactType.MATCH_RESULT],
            )
        )
    if plan.lineups and lineup_outcome is not None:
        registros.append(
            _registro(
                plan,
                build_run_id=build_run_id,
                fact_type=CanonicalFactType.LINEUP,
                fact_id=str(plan.decision.match_id),
                outcome=lineup_outcome,
            )
        )
    if plan.odds and odds_outcome is not None:
        registros.append(
            _registro(
                plan,
                build_run_id=build_run_id,
                fact_type=CanonicalFactType.ODDS_OBSERVATION,
                fact_id=str(plan.decision.match_id),
                outcome=odds_outcome,
            )
        )
    return tuple(registros)


def _registro(
    plan: MatchBuildPlan,
    *,
    build_run_id: str,
    fact_type: CanonicalFactType,
    fact_id: str,
    outcome: MatchWriteOutcome,
) -> CanonicalBuildRecord:
    estado = _ESTADO_DA_ESCRITA[outcome]
    return CanonicalBuildRecord.of(
        build_run_id=build_run_id,
        decision=plan.decision,
        fact_type=fact_type,
        source_fusion_group_id=plan.fusion_group_id,
        quality_assessment_id=plan.quality_assessment_id,
        status=estado,
        fact_id=fact_id if estado.persisted_a_fact else None,
        reason=(
            "o fato canônico já existe e DISCORDA do que este build produziu — "
            "nada foi sobrescrito (§62)"
            if outcome.is_conflict
            else None
        ),
    )
