"""Os casos de uso da construção canônica histórica.

A CADEIA COMPLETA, e o lugar de cada peça:

    avaliação persistida   lida do banco, NUNCA recalculada aqui (§5)
    política de build      decide, e é a única que decide
    construtores tipados   materializam, e recusam sem decisão
    registro canônico      escreve, com equivalência antes de reuso
    linhagem               grava o que de fato aconteceu (§65, §66)

O CASO DE USO É PURO SOBRE LOTES, como o de fusão e o de qualidade. Ele recebe
os candidatos fundidos de quem os leu, busca no banco a avaliação e a
identidade daquele lote — duas consultas, não duas por partida — e monta.

A UNIDADE TRANSACIONAL É O LOTE, não a execução (§64). Uma transação global
sobre dez mil partidas seguraria locks por minutos e refaria tudo por causa de
uma; uma por partida pagaria o custo de transação dez mil vezes. O lote é o
meio-termo, e o §65 continua valendo dentro dele: se a escrita falha, nenhum
`BuildRecord=BUILT` é gravado para os fatos daquele lote.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, final

from sports_intelligence.domain.build.decisions import BuildDecision
from sports_intelligence.domain.build.facts import LineupDraft
from sports_intelligence.domain.build.policy import (
    DEFAULT_RESEARCH_BUILD_POLICY,
    CanonicalBuildPolicy,
)
from sports_intelligence.domain.build.runs import (
    BuildCounts,
    CanonicalBuildRecord,
    CanonicalBuildRun,
    counts_of,
)
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.fusion.runs import FusedMatchCandidate
from sports_intelligence.domain.quality.runs import (
    QualityRun,
    assert_run_is_consumable,
)
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.audit import AuditAction, AuditEntry
from sports_intelligence.domain.shared.errors import NotFoundError
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.historical.build.assembly import (
    CanonicalAssembler,
    MatchBuildInputs,
    MatchBuildPlan,
    records_of,
)
from sports_intelligence.ports.audit import AuditPort
from sports_intelligence.ports.clock import ClockPort
from sports_intelligence.ports.repositories.canonical_build import (
    CanonicalBuildRecordRepositoryPort,
    CanonicalBuildRunRepositoryPort,
    CanonicalIdentityReaderPort,
    CanonicalRegistryWritePort,
)
from sports_intelligence.ports.repositories.quality import (
    QualityAssessmentRepositoryPort,
    QualityRunRepositoryPort,
)
from sports_intelligence.ports.unit_of_work import UnitOfWorkPort


@final
@dataclass(frozen=True, slots=True)
class BuildCandidateBatch:
    """Um lote de candidatos fundidos prontos para construir.

    A ESCALAÇÃO VEM JUNTO E HOJE VEM VAZIA. O contrato fundido da V1 não
    carrega lista de jogadores — nenhum papel semântico a descreve —, e o
    campo existe para que o dia em que ela existir seja uma mudança na BORDA e
    não no caso de uso (§28, §35).
    """

    candidates: tuple[FusedMatchCandidate, ...]
    lineup_drafts: Mapping[MatchId, tuple[LineupDraft, ...]] = field(
        default_factory=dict
    )


@final
@dataclass(frozen=True, slots=True)
class BuildOutput:
    run: CanonicalBuildRun
    #: As decisões de cada partida, para que o chamador possa afirmar coisas
    #: sobre elas sem reler o banco. Elas NÃO são o corpus (§111).
    decisions: tuple[BuildDecision, ...]


@final
@dataclass(frozen=True, slots=True)
class RunCanonicalBuild:
    """Constrói fatos canônicos a partir de uma avaliação já persistida."""

    quality_runs: QualityRunRepositoryPort
    assessments: QualityAssessmentRepositoryPort
    identities: CanonicalIdentityReaderPort
    registry: CanonicalRegistryWritePort
    build_runs: CanonicalBuildRunRepositoryPort
    records: CanonicalBuildRecordRepositoryPort
    clock: ClockPort
    audit: AuditPort
    uow: UnitOfWorkPort | None = None
    policy: CanonicalBuildPolicy = DEFAULT_RESEARCH_BUILD_POLICY

    async def execute(
        self,
        *,
        actor: Actor,
        quality_run_id: str,
        batches: AsyncIterator[BuildCandidateBatch],
        correlation_id: str | None = None,
    ) -> BuildOutput:
        avaliacao = await self._validar_avaliacao(quality_run_id)

        execucao = await self.build_runs.create(
            CanonicalBuildRun.start(
                quality_run_id=avaliacao.id,
                input_fusion_run_ids=avaliacao.fusion_run_ids,
                build_policy_version=self.policy.version,
                scope=self.policy.scope,
                quality_policy_version=avaliacao.policy_version,
                at=self.clock.now(),
                triggered_by=actor,
            )
        )
        await self._snapshot(execucao)
        await self._auditar(
            AuditAction.CANONICAL_BUILD_STARTED,
            actor=actor,
            correlation_id=correlation_id,
            build_run=execucao.id,
            quality_run=avaliacao.id,
            scope=self.policy.scope.value,
            build_policy_version=str(self.policy.version),
        )

        montador = CanonicalAssembler(policy=self.policy)
        decisoes: list[BuildDecision] = []
        contagens = BuildCounts()
        impressao = hashlib.sha256()
        try:
            async for lote in batches:
                planos, registros = await self._construir_lote(
                    montador, execucao.id, quality_run_id=avaliacao.id, batch=lote
                )
                do_lote = tuple(p.decision for p in planos)
                decisoes.extend(do_lote)
                contagens = contagens.merged_with(counts_of(do_lote, registros))
                _acumular(impressao, registros)
        except Exception as erro:
            falha = execucao.fail(reason=type(erro).__name__, at=self.clock.now())
            await self.build_runs.finish(falha)
            raise

        concluida = execucao.complete(
            counts=contagens,
            at=self.clock.now(),
            output_fingerprint=ContentHash(impressao.hexdigest()),
        )
        await self.build_runs.finish(concluida)
        await self._auditar_conclusao(
            concluida, actor=actor, correlation_id=correlation_id, decisions=decisoes
        )
        return BuildOutput(run=concluida, decisions=tuple(decisoes))

    # ------------------------------------------------------------- o lote --

    async def _construir_lote(
        self,
        assembler: CanonicalAssembler,
        build_run_id: str,
        *,
        quality_run_id: str,
        batch: BuildCandidateBatch,
    ) -> tuple[tuple[MatchBuildPlan, ...], tuple[CanonicalBuildRecord, ...]]:
        """Um lote inteiro em poucas consultas — nunca em algumas por partida.

        DUAS LEITURAS PARA N PARTIDAS: os vereditos daquele lote e a identidade
        canônica deles. Depois, uma escrita por FAMÍLIA — não por partida. É a
        disciplina do §68 aplicada ao caminho de escrita, que é justamente onde
        o benchmark do PR-03.1 encontrou o N+1 que a assinatura em massa dos
        ports não tinha protegido.
        """
        if not batch.candidates:
            return (), ()

        ids = [c.canonical_match_id for c in batch.candidates]
        vereditos = {
            r.match_id: r
            for r in await self.assessments.by_matches(quality_run_id, ids)
        }
        identidades = await self.identities.identity_facts(ids)
        rascunhos = dict(batch.lineup_drafts)

        planos = tuple(
            assembler.plan(
                MatchBuildInputs(
                    record=veredito,
                    candidate=candidato,
                    identity=identidades.get(candidato.canonical_match_id),
                    lineup_drafts=rascunhos.get(candidato.canonical_match_id, ()),
                ),
                ingested_at=self.clock.now(),
            )
            for candidato in batch.candidates
            if (veredito := vereditos.get(candidato.canonical_match_id)) is not None
        )
        if not planos:
            return (), ()

        registros = await self._persistir(planos, build_run_id=build_run_id)
        return planos, registros

    async def _persistir(
        self, plans: Sequence[MatchBuildPlan], *, build_run_id: str
    ) -> tuple[CanonicalBuildRecord, ...]:
        """Escreve os fatos e grava a linhagem — nessa ordem, e numa transação.

        A ORDEM É O §65 INTEIRO. A linhagem é escrita DEPOIS de a escrita
        canônica voltar, com o desfecho que ela devolveu: um
        `BuildRecord=BUILT` gravado antes afirmaria ter construído um fato que
        a transação seguinte poderia não conseguir gravar.
        """
        partidas = [p.match for p in plans if p.match is not None]
        resultados = [
            (p.decision.match_id, p.result) for p in plans if p.result is not None
        ]
        escalacoes = [line for p in plans for line in p.lineups]
        cotacoes = [odd for p in plans for odd in p.odds]

        async with _escopo(self.uow):
            desfechos_de_partida = await self.registry.upsert_equivalent_matches(partidas)
            # O RESULTADO SÓ ENTRA PARA AS PARTIDAS QUE ENTRARAM. Gravar um
            # placar cuja partida entrou em conflito produziria um resultado
            # órfão — e a chave estrangeira o recusaria de qualquer forma, com
            # uma mensagem muito pior de investigar.
            gravaveis = {
                m
                for m, desfecho in desfechos_de_partida.items()
                if not desfecho.is_conflict
            }
            desfechos_de_resultado = await self.registry.persist_results(
                [(m, r) for m, r in resultados if m in gravaveis]
            )
            desfechos_de_escalacao = await self.registry.persist_lineups(
                [line for line in escalacoes if line.match_id in gravaveis]
            )
            desfechos_de_odds = await self.registry.persist_odds(
                [odd for odd in cotacoes if odd.match_id in gravaveis]
            )

            registros = tuple(
                registro
                for plano in plans
                for registro in records_of(
                    plano,
                    build_run_id=build_run_id,
                    match_outcome=desfechos_de_partida.get(plano.decision.match_id),
                    result_outcome=desfechos_de_resultado.get(plano.decision.match_id),
                    lineup_outcome=desfechos_de_escalacao.get(plano.decision.match_id),
                    odds_outcome=desfechos_de_odds.get(plano.decision.match_id),
                )
            )
            await self.records.append_many(registros)
            await self.records.record_family_decisions(
                build_run_id, [p.decision for p in plans]
            )
        return registros

    # ----------------------------------------------------------- apoio ----

    async def _validar_avaliacao(self, quality_run_id: str) -> QualityRun:
        execucao = await self.quality_runs.by_id(quality_run_id)
        if execucao is None:
            raise NotFoundError(
                f"execução de qualidade {quality_run_id} não encontrada"
            )
        assert_run_is_consumable(execucao)
        return execucao

    async def _snapshot(self, run: CanonicalBuildRun) -> None:
        gravar = getattr(self.build_runs, "save_policy_snapshot", None)
        if gravar is not None:
            await gravar(run.id, self.policy)

    async def _auditar(
        self,
        action: AuditAction,
        *,
        actor: Actor,
        correlation_id: str | None,
        **detalhe: Any,
    ) -> None:
        await self.audit.record(
            AuditEntry.of(
                action,
                actor=actor,
                at=self.clock.now(),
                correlation_id=correlation_id,
                **detalhe,
            )
        )

    async def _auditar_conclusao(
        self,
        run: CanonicalBuildRun,
        *,
        actor: Actor,
        correlation_id: str | None,
        decisions: Sequence[BuildDecision],
    ) -> None:
        """Uma linha de conclusão, e UMA de exclusão por licença (§76).

        NÃO UMA POR PARTIDA. `canonical_build_family_decisions` já é a linhagem
        por partida; repeti-la na trilha faria o volume dela ser governado pelo
        tamanho do corpus até ninguém achar as decisões no meio. O que a trilha
        precisa responder é «este build comercial descartou o quê, e sob qual
        licença» — e isso cabe numa linha.
        """
        await self._auditar(
            AuditAction.CANONICAL_BUILD_COMPLETED,
            actor=actor,
            correlation_id=correlation_id,
            build_run=run.id,
            status=run.status.value,
            attempted=run.counts.records_attempted,
            built=run.counts.records_built,
            reused=run.counts.records_reused,
            skipped=run.counts.records_skipped,
            review_required=run.counts.records_review_required,
            failed=run.counts.records_failed,
        )
        por_licenca: dict[str, int] = {}
        for decisao in decisions:
            for familia in decisao.excluded_by_license:
                por_licenca[familia.value] = por_licenca.get(familia.value, 0) + 1
        if por_licenca:
            await self._auditar(
                AuditAction.CANONICAL_BUILD_FAMILY_EXCLUDED,
                actor=actor,
                correlation_id=correlation_id,
                build_run=run.id,
                scope=run.scope.value,
                **{f"family_{nome}": str(quantas) for nome, quantas in por_licenca.items()},
            )


@final
@dataclass(frozen=True, slots=True)
class GetCanonicalBuildRun:
    build_runs: CanonicalBuildRunRepositoryPort

    async def execute(self, run_id: str) -> CanonicalBuildRun:
        execucao = await self.build_runs.by_id(run_id)
        if execucao is None:
            raise NotFoundError(f"execução de build {run_id} não encontrada")
        return execucao


@final
@dataclass(frozen=True, slots=True)
class GetMatchLineage:
    """A linhagem de UMA partida — a resposta do §50 e do §97.

    «Por que este Match entrou no corpus?» e «quantos builds o produziram?»
    saem da mesma lista: um registro por fato e por execução, cada um com a
    avaliação que o autorizou e o grupo de fusão de onde ele veio.
    """

    records: CanonicalBuildRecordRepositoryPort

    async def execute(self, match_id: MatchId) -> Sequence[CanonicalBuildRecord]:
        return await self.records.for_match(match_id)


def _escopo(uow: UnitOfWorkPort | None) -> Any:
    """A transação do lote, ou um bloco que não faz nada.

    `None` É LEGÍTIMO E NÃO É PREGUIÇA: um teste com repositórios em memória
    não tem transação para abrir, e exigir uma o obrigaria a inventar um duplo
    de `UnitOfWork` cujo único comportamento seria não fazer nada.
    """
    if uow is not None:
        return uow
    return _SemTransacao()


@final
class _SemTransacao:
    """O escopo que não abre transação nenhuma. Explícito, e não um `nullcontext`
    genérico: o nome diz, na leitura do rastro, que ali NÃO havia atomicidade."""

    async def __aenter__(self) -> _SemTransacao:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


def _acumular(digest: Any, records: Sequence[CanonicalBuildRecord]) -> None:
    """A impressão determinística do conjunto de registros (§54).

    ORDENADA POR (partida, tipo de fato) e SEM os identificadores de execução:
    `id` e `build_run_id` são UUID sorteados e mudam a cada execução, e
    incluí-los faria a impressão dizer «são diferentes» sobre dois builds que
    produziram exatamente a mesma coisa — que é o oposto do que ela existe para
    responder.
    """
    for registro in sorted(
        records, key=lambda r: (str(r.match_id), r.fact_type.value)
    ):
        digest.update(
            json.dumps(
                registro.as_canonical(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        )
