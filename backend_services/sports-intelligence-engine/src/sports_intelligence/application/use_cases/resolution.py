"""Os casos de uso de resolução — em lote, e na ordem obrigatória.

A ORDEM É O ASSUNTO DESTE MÓDULO (ADR-0022):

    competição → temporada → time → partida

Cada etapa consome o que a anterior resolveu. Resolver partida antes de time
significaria resolver time por dentro, sem evidência nem decisão registrada —
e é exatamente assim que uma resolução silenciosa entra no sistema.

O LOTE É A UNIDADE, e é o que mata o N+1 (§42, §74):

    ler lote → valores distintos → carregar candidatos → resolver → persistir
      1 I/O        0 I/O            ~6 consultas         0 I/O      1 I/O

Um lote de mil linhas de Premier League tem vinte nomes de clube. Consultar
mil vezes o que são vinte buscas é a diferença entre dois minutos e três
horas — e o sintoma não é erro, é «a resolução está lenta».

REPROCESSAR NÃO REESCREVE NADA (ADR-0019). Uma execução nova com resolver ou
política novos produz decisões novas, numa execução nova. A anterior fica
exatamente como estava, e a diferença entre as duas é o que mostra o que o
resolver novo passou a enxergar.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Final, final

from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.datasets.lifecycle import DatasetLifecycle
from sports_intelligence.domain.events.envelope import EventEnvelope
from sports_intelligence.domain.events.envelope_types import (
    DOMAIN_SCHEMA,
    RESOLUTION_REVIEW_REQUIRED,
    RESOLUTION_RUN_COMPLETED,
)
from sports_intelligence.domain.resolution.decisions import (
    DecisionCounts,
    DecisionVersions,
    ResolutionConfidence,
    ResolutionDecision,
    ResolutionInput,
    ResolutionMethod,
    ResolutionStatus,
    SourceValue,
    SubjectType,
)
from sports_intelligence.domain.resolution.evidence import (
    EvidenceKind,
    ExplanationCode,
    ResolutionEvidence,
)
from sports_intelligence.domain.resolution.mappings import (
    EntityAlias,
    ProviderEntityMapping,
    assert_mapping_is_consistent,
)
from sports_intelligence.domain.resolution.policy import (
    DEFAULT_MATCH_POLICY,
    DEFAULT_RESOLUTION_POLICY,
    MatchResolutionPolicy,
    ResolutionPolicy,
)
from sports_intelligence.domain.resolution.review import (
    ResolutionReviewItem,
    ReviewFilter,
    ReviewSubject,
)
from sports_intelligence.domain.resolution.runs import ResolutionRun
from sports_intelligence.domain.resolution.versions import (
    CURRENT_RESOLUTION_POLICY_VERSION,
    CURRENT_RESOLVER_VERSION,
)
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.audit import AuditAction, AuditEntry
from sports_intelligence.domain.shared.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from sports_intelligence.domain.shared.identity import (
    CompetitionId,
    DatasetId,
    EntityId,
    ProviderId,
    SeasonId,
    TeamId,
)
from sports_intelligence.domain.shared.temporal import Instant, instant
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.domain.sources.mapping import (
    SeasonConvention,
    SourceMappingDefinition,
)
from sports_intelligence.domain.sources.records import SourceBatch, SourceRecord
from sports_intelligence.domain.sources.semantics import MATCH_REQUIRED_ROLES, SemanticRole
from sports_intelligence.ingestion.resolution.context import (
    ContextBuilder,
    NormalizedName,
    ResolutionContext,
)
from sports_intelligence.ingestion.resolution.resolvers import (
    MatchCandidateInput,
    Outcome,
    ResolverBundle,
)
from sports_intelligence.ports.audit import AuditPort
from sports_intelligence.ports.clock import ClockPort
from sports_intelligence.ports.event_bus import EventPublisherPort
from sports_intelligence.ports.repositories.dataset_registry import DatasetRepositoryPort
from sports_intelligence.ports.repositories.resolution import (
    CanonicalRegistryPort,
    EntityAliasRepositoryPort,
    ProviderMappingRepositoryPort,
    ResolutionDecisionRepositoryPort,
    ResolutionRunRepositoryPort,
    ReviewQueueRepositoryPort,
    SourceMappingRepositoryPort,
)

#: O ator de serviço que executa a resolução automática. Identificado pelo
#: que ele É — nunca «system» (§11).
RESOLUTION_WORKER: Final[str] = "historical-resolution-worker"

#: Os papéis que carregam nome de clube. `TEAM_NAME` entra porque um dataset
#: de JOGADORES declara o clube por ele — e é esse clube que ativa a evidência
#: temporal do vínculo, que é o que separa dois homônimos (§19).
_PAPEIS_DE_TIME: Final[tuple[SemanticRole, ...]] = (
    SemanticRole.HOME_TEAM_NAME,
    SemanticRole.AWAY_TEAM_NAME,
    SemanticRole.TEAM_NAME,
)


async def _um_a_um(
    batches: Iterable[SourceBatch] | AsyncIterable[SourceBatch],
) -> AsyncIterable[SourceBatch]:
    """Percorre os lotes sem materializar a coleção — síncrona ou assíncrona.

    ACEITA AS DUAS FORMAS porque as duas existem no caminho real: o leitor de
    arquivo é um gerador síncrono, e a leitura a partir do object store é
    assíncrona. Exigir uma só obrigaria o outro lado a materializar para
    converter — que é exatamente o que este PR removeu.
    """
    if isinstance(batches, AsyncIterable):
        async for lote in batches:
            yield lote
        return
    for lote in batches:
        yield lote


@final
@dataclass(frozen=True, slots=True)
class RegisterSourceMapping:
    """Registra como ler um dataset STAGED.

    O DATASET PRECISA ESTAR `STAGED`. Antes disso os bytes não foram
    validados, e mapear um arquivo que pode nem ser CSV é declarar
    interpretação sobre algo que ninguém leu.
    """

    datasets: DatasetRepositoryPort
    mappings: SourceMappingRepositoryPort
    clock: ClockPort
    audit: AuditPort

    async def execute(
        self,
        *,
        actor: Actor,
        dataset_id: DatasetId,
        definition: SourceMappingDefinition,
        correlation_id: str | None = None,
    ) -> SourceMappingDefinition:
        dataset = await self.datasets.by_id(dataset_id, with_files=False)
        if dataset is None:
            raise NotFoundError(f"dataset {dataset_id} não registrado")
        if dataset.lifecycle is not DatasetLifecycle.STAGED:
            raise ConflictError(
                f"o dataset está em {dataset.lifecycle}; mapeamento de fonte só faz "
                "sentido sobre um dataset STAGED, cujos bytes já foram validados",
                context={"state": dataset.lifecycle.value},
            )
        # FALHA NO REGISTRO, E NÃO NA EXECUÇÃO. Descobrir que falta o nome do
        # visitante depois de processar cem mil linhas custa a execução
        # inteira; descobrir aqui custa uma mensagem.
        definition.assert_resolvable_as_matches()

        gravado = await self.mappings.save(definition)
        await self.audit.record(
            AuditEntry.of(
                AuditAction.DATASET_FILE_ATTACHED,
                actor=actor,
                at=self.clock.now(),
                dataset_id=dataset_id,
                correlation_id=correlation_id,
                mapping_id=gravado.id,
                mapping_version=gravado.version,
                roles=len(gravado.fields),
            )
        )
        return gravado


@final
@dataclass(frozen=True, slots=True)
class ResolutionOutput:
    """O que uma execução produziu, para o chamador reportar."""

    run: ResolutionRun
    decisions: int
    review_items: int


@final
@dataclass(frozen=True, slots=True)
class RunIdentityResolution:
    """A execução de resolução, lote a lote, na ordem obrigatória.

    A EXECUÇÃO É IDEMPOTENTE NO SENTIDO QUE IMPORTA (§68): rodá-la duas vezes
    produz DUAS execuções, e é o comportamento certo — cada uma com suas
    decisões, ambas explicáveis. O que ela não faz é reescrever a anterior.
    """

    datasets: DatasetRepositoryPort
    source_mappings: SourceMappingRepositoryPort
    registry: CanonicalRegistryPort
    provider_mappings: ProviderMappingRepositoryPort
    aliases: EntityAliasRepositoryPort
    runs: ResolutionRunRepositoryPort
    decisions: ResolutionDecisionRepositoryPort
    review: ReviewQueueRepositoryPort
    resolvers: ResolverBundle
    clock: ClockPort
    audit: AuditPort
    publisher: EventPublisherPort
    policy: ResolutionPolicy = DEFAULT_RESOLUTION_POLICY
    match_policy: MatchResolutionPolicy = DEFAULT_MATCH_POLICY
    batch_size: int = 2_000
    candidate_limit: int = 5_000
    #: Quantos candidatos de similaridade carregar POR NOME consultado.
    #:
    #: POR NOME E NÃO NO TOTAL (§35). Um teto global faria o corte depender de
    #: quantos nomes vieram no lote — trocaria a dependência de lote que este
    #: PR removeu por outra, no mesmo lugar.
    #:
    #: Cinquenta é folgado para o que o resolver usa: o corte de candidato é
    #: 0,55 de similaridade, e um nome raramente tem cinquenta clubes acima
    #: disso. O limite existe para o caso patológico — um token comum como
    #: `fc` casando com metade do registro — e não para o caso normal.
    candidates_per_name: int = 50

    async def execute(
        self,
        *,
        actor: Actor,
        dataset_id: DatasetId,
        batches: Iterable[SourceBatch] | AsyncIterable[SourceBatch],
        correlation_id: str | None = None,
    ) -> ResolutionOutput:
        dataset = await self.datasets.by_id(dataset_id)
        if dataset is None:
            raise NotFoundError(f"dataset {dataset_id} não registrado")
        if dataset.lifecycle is not DatasetLifecycle.STAGED:
            raise ConflictError(
                f"resolução exige dataset STAGED; este está em {dataset.lifecycle}"
            )
        mapeamento = await self.source_mappings.active_for(dataset_id)
        if mapeamento is None:
            raise ConflictError(
                "o dataset não tem mapeamento de fonte ativo — sem ele não há como "
                "saber qual coluna carrega o quê"
            )
        manifesto = await self._impressao(dataset_id)

        versoes = DecisionVersions(
            resolver=CURRENT_RESOLVER_VERSION,
            normalizer=self.resolvers.normalizer.version,
            policy=self.policy.version,
        )
        execucao = await self.runs.create(
            ResolutionRun.start(
                dataset_id=dataset_id,
                dataset_version=dataset.version,
                manifest_fingerprint=manifesto,
                versions=versoes,
                at=self.clock.now(),
                triggered_by=actor,
            )
        )
        entrada = ResolutionInput(
            dataset_id=dataset_id,
            dataset_version=dataset.version,
            manifest_fingerprint=manifesto,
        )
        servico = Actor.service(RESOLUTION_WORKER)

        contagens = DecisionCounts()
        total_decisoes = 0
        total_revisao = 0
        try:
            # OS LOTES CHEGAM COMO ITERÁVEL E SÃO CONSUMIDOS UM A UM (§41 a §43).
            # Uma `Sequence` obrigava o chamador a materializar a lista inteira
            # antes de a resolução começar, e era o que fazia o pico de memória
            # de cem mil registros ser 224 MB em vez do tamanho de um lote.
            async for lote in _um_a_um(batches):
                decisoes, itens = await self._processar_lote(
                    lote,
                    mapping=mapeamento,
                    run_id=execucao.id,
                    versions=versoes,
                    input_ref=entrada,
                    service=servico,
                )
                for decisao in decisoes:
                    contagens = contagens.with_status(decisao.status)
                total_decisoes += await self.decisions.append_many(
                    decisoes, run_id=execucao.id
                )
                total_revisao += await self.review.create_many(itens)
        except Exception as erro:
            falha = execucao.fail(
                reason=f"{type(erro).__name__}", at=self.clock.now()
            )
            await self.runs.finish(falha)
            raise

        concluida = execucao.complete(counts=contagens, at=self.clock.now())
        await self.runs.finish(concluida)
        await self._publicar(concluida, correlation_id)
        return ResolutionOutput(
            run=concluida, decisions=total_decisoes, review_items=total_revisao
        )

    # ------------------------------------------------------------- lote --

    async def _processar_lote(
        self,
        lote: SourceBatch,
        *,
        mapping: SourceMappingDefinition,
        run_id: str,
        versions: DecisionVersions,
        input_ref: ResolutionInput,
        service: Actor,
    ) -> tuple[list[ResolutionDecision], list[ResolutionReviewItem]]:
        contexto = await self._carregar_contexto(lote, mapping)
        decisoes: list[ResolutionDecision] = []
        itens: list[ResolutionReviewItem] = []
        agora = self.clock.now()

        # PRIMEIRA PASSAGEM: competição, temporada e times, sobre os valores
        # DISTINTOS do lote. Vinte nomes de clube em mil linhas viram vinte
        # resoluções, não mil.
        por_competicao = self._resolver_distintos(
            lote, SemanticRole.COMPETITION_NAME, SubjectType.COMPETITION, contexto
        )
        por_time = {
            chave: resultado
            for papel in _PAPEIS_DE_TIME
            for chave, resultado in self._resolver_distintos(
                lote, papel, SubjectType.TEAM, contexto
            ).items()
        }
        # O MAPEAMENTO DE PROVEDOR É O CAMINHO PRIORITÁRIO (§22), e ele
        # também é resolvido sobre os valores DISTINTOS: um lote de mil
        # linhas de Premier League tem vinte ids de clube, não mil.
        por_referencia_de_time = self._resolver_por_referencia(
            lote, SubjectType.TEAM, contexto, mapping.provider_id
        )
        por_referencia_de_jogador = self._resolver_por_referencia(
            lote, SubjectType.PLAYER, contexto, mapping.provider_id
        )
        convencao = SeasonConvention(
            mapping.conventions.get("season_convention", SeasonConvention.UNDECLARED.value)
        )

        for registro in lote.records:
            for decisao, item in self._resolver_registro(
                registro,
                contexto=contexto,
                competicoes=por_competicao,
                times=por_time,
                por_referencia_de_time=por_referencia_de_time,
                por_referencia_de_jogador=por_referencia_de_jogador,
                convencao=convencao,
                run_id=run_id,
                versions=versions,
                input_ref=input_ref,
                service=service,
                at=agora,
            ):
                decisoes.append(decisao)
                if item is not None:
                    itens.append(item)

            # A ETAPA DE JOGADOR É INDEPENDENTE DA CADEIA DA PARTIDA, e por
            # isso mora aqui e não dentro dela. Um registro cuja competição
            # não resolveu ainda pode ter identidade de jogador legítima —
            # pendurá-la na cadeia faria a primeira falha apagar a segunda.
            do_jogador = self._resolver_jogador(
                registro,
                contexto=contexto,
                por_referencia=por_referencia_de_jogador,
                times=por_time,
                at=agora,
            )
            if do_jogador is not None:
                decisao, item = self._decidir(
                    do_jogador,
                    SubjectType.PLAYER,
                    registro,
                    registro.text_of(SemanticRole.PLAYER_NAME)
                    or registro.text_of(SemanticRole.PLAYER_PROVIDER_ID)
                    or "",
                    contexto,
                    run_id,
                    versions,
                    input_ref,
                    service,
                    agora,
                )
                decisoes.append(decisao)
                if item is not None:
                    itens.append(item)
        return decisoes, itens

    def _resolver_distintos(
        self,
        lote: SourceBatch,
        papel: SemanticRole,
        sujeito: SubjectType,
        contexto: ResolutionContext,
    ) -> dict[str, Outcome]:
        """Resolve cada valor DISTINTO uma vez, e reusa no lote inteiro."""
        saida: dict[str, Outcome] = {}
        for texto in lote.distinct_texts(papel):
            nome = NormalizedName.of(texto, contexto.normalizer)
            if sujeito is SubjectType.COMPETITION:
                saida[texto] = self.resolvers.competition.resolve(
                    nome, context=contexto, policy=self.policy
                )
            else:
                saida[texto] = self.resolvers.team.resolve(
                    nome, context=contexto, policy=self.policy
                )
        return saida

    def _resolver_por_referencia(
        self,
        lote: SourceBatch,
        sujeito: SubjectType,
        contexto: ResolutionContext,
        provedor: ProviderId,
    ) -> dict[str, Outcome]:
        """Resolve cada REFERÊNCIA DE PROVEDOR distinta do lote, uma vez.

        É O CAMINHO MAIS BARATO E MAIS CONFIÁVEL QUE EXISTE (§23), e até o
        PR-03.1 ele era inalcançável: a execução em lote resolvia por nome
        distinto e nunca passava `provider_ref` ao resolver. Os índices de
        `provider_entity_mappings` terminaram o benchmark com ZERO usos — que
        é como um caminho morto se parece quando ninguém o mede.

        UM ID DE PROVEDOR NÃO PRECISA SER RESOLVIDO DE NOVO. Ele já foi, e a
        decisão ficou registrada; reler `Manchester City` por texto a cada
        execução é refazer trabalho que alguém já conferiu.
        """
        papeis = (
            (
                SemanticRole.HOME_TEAM_PROVIDER_ID,
                SemanticRole.AWAY_TEAM_PROVIDER_ID,
                SemanticRole.TEAM_PROVIDER_ID,
            )
            if sujeito is SubjectType.TEAM
            else (SemanticRole.PLAYER_PROVIDER_ID,)
        )
        resolver = (
            self.resolvers.team if sujeito is SubjectType.TEAM else self.resolvers.player
        )
        saida: dict[str, Outcome] = {}
        for papel in papeis:
            for referencia in lote.distinct_texts(papel):
                if referencia in saida:
                    continue
                resultado = resolver.resolve(
                    NormalizedName.of(referencia, contexto.normalizer),
                    context=contexto,
                    policy=self.policy,
                    provider_ref=referencia,
                    provider_id=provedor,
                )
                # SÓ INTERESSA O QUE O MAPEAMENTO RESOLVEU. Um `UNRESOLVED`
                # aqui significa «não há mapeamento para esta referência», e
                # não «esta entidade não existe» — o nome ainda vai tentar.
                # Guardar o `UNRESOLVED` faria a referência ausente vencer o
                # nome presente.
                if resultado.method is ResolutionMethod.EXACT_PROVIDER_MAPPING:
                    saida[referencia] = resultado
        return saida

    def _resolver_registro(
        self,
        registro: SourceRecord,
        *,
        contexto: ResolutionContext,
        competicoes: dict[str, Outcome],
        times: dict[str, Outcome],
        por_referencia_de_time: dict[str, Outcome],
        por_referencia_de_jogador: dict[str, Outcome],
        convencao: SeasonConvention,
        run_id: str,
        versions: DecisionVersions,
        input_ref: ResolutionInput,
        service: Actor,
        at: Instant,
    ) -> list[tuple[ResolutionDecision, ResolutionReviewItem | None]]:
        """As decisões de UM registro, na ordem obrigatória.

        A CADEIA PARA NA PRIMEIRA QUE NÃO RESOLVE. Sem competição não há
        temporada; sem temporada e sem os dois times não há partida. Seguir
        adiante com uma identidade em aberto seria resolver partida contra um
        contexto que não se sabe qual é.
        """
        saida: list[tuple[ResolutionDecision, ResolutionReviewItem | None]] = []

        texto_competicao = registro.text_of(SemanticRole.COMPETITION_NAME)
        resultado_competicao = competicoes.get(texto_competicao or "")
        if texto_competicao is None or resultado_competicao is None:
            return saida
        saida.append(
            self._decidir(
                resultado_competicao,
                SubjectType.COMPETITION,
                registro,
                texto_competicao,
                contexto,
                run_id,
                versions,
                input_ref,
                service,
                at,
            )
        )
        if not resultado_competicao.status.yields_canonical_reference:
            return saida
        competicao = resultado_competicao.entity_id
        assert isinstance(competicao, CompetitionId)

        texto_temporada = registro.text_of(SemanticRole.SEASON_LABEL)
        if texto_temporada is None:
            return saida
        data = registro.get(SemanticRole.KICKOFF_DATE)
        resultado_temporada = self.resolvers.season.resolve(
            NormalizedName.of(texto_temporada, contexto.normalizer),
            competition=competicao,
            context=contexto,
            policy=self.policy,
            convention=convencao,
            match_date=data.day if data and data.day else None,
        )
        saida.append(
            self._decidir(
                resultado_temporada,
                SubjectType.SEASON,
                registro,
                texto_temporada,
                contexto,
                run_id,
                versions,
                input_ref,
                service,
                at,
            )
        )
        if not resultado_temporada.status.yields_canonical_reference:
            return saida
        temporada = resultado_temporada.entity_id
        assert isinstance(temporada, SeasonId)

        lados: dict[SemanticRole, EntityId | None] = {}
        for papel, papel_de_referencia in (
            (SemanticRole.HOME_TEAM_NAME, SemanticRole.HOME_TEAM_PROVIDER_ID),
            (SemanticRole.AWAY_TEAM_NAME, SemanticRole.AWAY_TEAM_PROVIDER_ID),
        ):
            texto = registro.text_of(papel)
            # O MAPEAMENTO DE PROVEDOR VEM ANTES DO NOME (§22). Quando a fonte
            # traz um id que já foi traduzido, o texto do clube deixa de ser
            # autoridade de identidade e passa a ser procedência (§51).
            referencia = registro.text_of(papel_de_referencia)
            do_provedor = (
                por_referencia_de_time.get(referencia) if referencia else None
            )
            resultado = do_provedor or (times.get(texto or "") if texto else None)
            if resultado is None:
                return saida
            if texto is None:
                texto = referencia or ""
            saida.append(
                self._decidir(
                    resultado,
                    SubjectType.TEAM,
                    registro,
                    texto,
                    contexto,
                    run_id,
                    versions,
                    input_ref,
                    service,
                    at,
                )
            )
            lados[papel] = (
                resultado.entity_id
                if resultado.status.yields_canonical_reference
                else None
            )

        mandante = lados[SemanticRole.HOME_TEAM_NAME]
        visitante = lados[SemanticRole.AWAY_TEAM_NAME]
        if not isinstance(mandante, TeamId) or not isinstance(visitante, TeamId):
            return saida

        kickoff = self._kickoff(registro)
        if kickoff is None:
            return saida
        resultado_partida = self.resolvers.match.resolve(
            MatchCandidateInput(
                competition=competicao,
                season=temporada,
                home=mandante,
                away=visitante,
                kickoff=kickoff,
                kickoff_timezone_undeclared=not registro.has(SemanticRole.KICKOFF),
                round_number=(
                    valor.integer
                    if (valor := registro.get(SemanticRole.ROUND_NUMBER))
                    else None
                ),
            ),
            context=contexto,
            policy=self.policy,
            match_policy=self.match_policy,
        )
        saida.append(
            self._decidir(
                resultado_partida,
                SubjectType.MATCH,
                registro,
                f"{mandante} x {visitante} @ {kickoff.isoformat()}",
                contexto,
                run_id,
                versions,
                input_ref,
                service,
                at,
            )
        )
        return saida

    def _resolver_jogador(
        self,
        registro: SourceRecord,
        *,
        contexto: ResolutionContext,
        por_referencia: dict[str, Outcome],
        times: dict[str, Outcome],
        at: Instant,
    ) -> Outcome | None:
        """A etapa de jogador — que até o PR-03.1 não tinha chamador nenhum.

        `PlayerResolver` existia, tinha teste de unidade e NÃO era alcançável
        pela cadeia operacional: `RunIdentityResolution` ia de competição a
        partida e nunca passava por ele. A evidência foi medida — os dois
        índices de `players` terminaram o benchmark com zero usos.

        A ETAPA É CONDICIONAL AO MAPEAMENTO, e não a um `if` sobre o dataset.
        Se a fonte declara `PLAYER_NAME`, há identidade de jogador para
        resolver; se não declara, não há — e `text_of` devolvendo `None` já
        diz isso, sem precisar de um dispatcher (§15).

        O CLUBE VEM DE `TEAM_NAME`, quando a fonte o declara, e é o que ativa
        a evidência temporal: `team_at` responde pelo vínculo NA DATA, nunca
        pelo clube atual (§19).
        """
        texto = registro.text_of(SemanticRole.PLAYER_NAME)
        referencia = registro.text_of(SemanticRole.PLAYER_PROVIDER_ID)
        do_provedor = por_referencia.get(referencia) if referencia else None
        if do_provedor is not None:
            return do_provedor
        if texto is None:
            return None

        nascimento = registro.get(SemanticRole.PLAYER_DOB)
        clube: TeamId | None = None
        texto_do_clube = registro.text_of(SemanticRole.TEAM_NAME)
        do_clube = times.get(texto_do_clube or "") if texto_do_clube else None
        if do_clube is not None and isinstance(do_clube.entity_id, TeamId):
            clube = do_clube.entity_id

        return self.resolvers.player.resolve(
            NormalizedName.of(texto, contexto.normalizer),
            context=contexto,
            policy=self.policy,
            date_of_birth=nascimento.day if nascimento else None,
            nationality=registro.text_of(SemanticRole.PLAYER_NATIONALITY),
            team=clube,
            at=self._kickoff(registro) or at,
        )

    def _decidir(
        self,
        resultado: Outcome,
        sujeito: SubjectType,
        registro: SourceRecord,
        texto: str,
        contexto: ResolutionContext,
        run_id: str,
        versions: DecisionVersions,
        input_ref: ResolutionInput,
        service: Actor,
        at: Instant,
    ) -> tuple[ResolutionDecision, ResolutionReviewItem | None]:
        """Carimba o raciocínio do resolver como decisão auditável."""
        valor = SourceValue(
            raw=texto,
            normalized=contexto.normalizer.normalize(texto),
            normalizer_version=contexto.normalizer.version,
        )
        comum = {
            "subject_type": sujeito,
            "provider_id": registro.provider_id,
            "source_value": valor,
            "confidence": resultado.confidence,
            "versions": versions,
            "decided_at": at,
            "decided_by": service,
            "input_ref": input_ref,
            # DE QUAL LINHA. É por esta referência que a fusão descobre quais
            # registros têm identidade provada (ADR-0022) e que a procedência
            # de um campo fundido volta ao arquivo bruto. Sem ela, a decisão
            # sabe de quais BYTES veio e não sabe de qual LINHA — e a fusão
            # não teria como ligar uma coisa na outra.
            "record_ref": str(registro.ref),
            "evidence": resultado.evidence,
            "alternatives": resultado.alternatives,
            "reason": resultado.reason,
        }
        if resultado.status.yields_canonical_reference and resultado.entity_id is not None:
            decisao = ResolutionDecision.resolved(
                canonical_entity_id=resultado.entity_id,
                method=resultado.method,
                **comum,  # type: ignore[arg-type]
            )
            return decisao, None

        decisao = ResolutionDecision.undecided(
            status=resultado.status, method=resultado.method, **comum  # type: ignore[arg-type]
        )
        if not resultado.status.needs_human:
            return decisao, None
        return decisao, ResolutionReviewItem.open(
            run_id=run_id,
            subject=ReviewSubject(
                subject_type=sujeito,
                provider_id=registro.provider_id,
                source_value=valor,
                record_ref=str(registro.ref),
                context={"dataset": str(registro.ref.dataset_id)[:8]},
            ),
            reason_status=resultado.status,
            candidates=resultado.alternatives,
            at=at,
        )

    # --------------------------------------------------------- carga --

    async def _carregar_contexto(
        self, lote: SourceBatch, mapping: SourceMappingDefinition
    ) -> ResolutionContext:
        """Seis consultas, uma por tipo. Nunca uma por linha.

        É A FUNÇÃO QUE MATA O N+1. Ela lê os valores DISTINTOS do lote e
        carrega tudo que pode casar com eles de uma vez; os resolvers passam
        a trabalhar sobre dicionários em memória.
        """
        normalizador = self.resolvers.normalizer
        nomes_de_time = {
            normalizador.normalize(t)
            for papel in _PAPEIS_DE_TIME
            for t in lote.distinct_texts(papel)
        }
        nomes_de_jogador = {
            normalizador.normalize(t) for t in lote.distinct_texts(SemanticRole.PLAYER_NAME)
        }
        refs_de_time = [
            r
            for papel in (
                SemanticRole.HOME_TEAM_PROVIDER_ID,
                SemanticRole.AWAY_TEAM_PROVIDER_ID,
                SemanticRole.TEAM_PROVIDER_ID,
            )
            for r in lote.distinct_texts(papel)
        ]
        refs_de_jogador = list(lote.distinct_texts(SemanticRole.PLAYER_PROVIDER_ID))

        competicoes = await self.registry.competitions()
        temporadas = await self.registry.seasons_of([c.id for c in competicoes])
        times = await self.registry.teams_by_normalized_names(sorted(nomes_de_time))
        # OS CANDIDATOS DE SIMILARIDADE SÃO POR NOME (§29 a §33), e é a consulta
        # que torna a decisão independente do lote. `teams_by_normalized_names`
        # continua existindo para o caminho EXATO e para o alcançável por
        # alias; esta traz quem só se parece.
        candidatos_de_time = (
            await self.registry.team_candidates_for_names(
                sorted(nomes_de_time), limit_per_name=self.candidates_per_name
            )
            if nomes_de_time
            else []
        )
        candidatos_de_jogador = (
            await self.registry.player_candidates_for_names(
                sorted(nomes_de_jogador), limit_per_name=self.candidates_per_name
            )
            if nomes_de_jogador
            else []
        )
        jogadores = (
            await self.registry.players_by_normalized_names(sorted(nomes_de_jogador))
            if nomes_de_jogador
            else []
        )
        ids_de_jogador = {
            str(j.id) for j in jogadores
        } | {str(j.id) for _, j in candidatos_de_jogador}
        vinculos = (
            await self.registry.tenures_of(sorted(ids_de_jogador)) if ids_de_jogador else []
        )
        # MAPEAMENTO DE PROVEDOR, DOS DOIS TIPOS. Até o PR-03.1 só as
        # referências de mandante eram carregadas — e nenhuma era CONSULTADA,
        # porque a resolução por nome distinto nunca passava `provider_ref`.
        # Os quatro índices de `provider_entity_mappings` ficaram com zero
        # usos no benchmark, o que é a evidência de um caminho inalcançável.
        mapeamentos = [
            *await self.provider_mappings.by_external_ids(
                mapping.provider_id, SubjectType.TEAM, refs_de_time
            ),
            *await self.provider_mappings.by_external_ids(
                mapping.provider_id, SubjectType.PLAYER, refs_de_jogador
            ),
        ]
        aliases = [
            *await self.aliases.by_normalized(SubjectType.COMPETITION, sorted(
                {normalizador.normalize(t)
                 for t in lote.distinct_texts(SemanticRole.COMPETITION_NAME)}
            )),
            *await self.aliases.by_normalized(SubjectType.TEAM, sorted(nomes_de_time)),
            *await self.aliases.by_normalized(
                SubjectType.PLAYER, sorted(nomes_de_jogador)
            ),
        ]

        construtor = (
            ContextBuilder(normalizador, self.clock.now())
            .with_competitions(tuple(competicoes))
            .with_seasons(tuple(temporadas))
            .with_teams(tuple(times))
            .with_team_candidates(tuple(candidatos_de_time))
            .with_players(tuple(jogadores), tuple(vinculos))
            .with_player_candidates(tuple(candidatos_de_jogador))
            .with_mappings(tuple(mapeamentos))
            .with_aliases(tuple(aliases))
        )
        # As partidas precisam dos confrontos, que só existem depois de os
        # times resolverem. Carregamos todas as da temporada do lote — que é
        # uma consulta, não uma por linha.
        contexto = construtor.build()
        confrontos = self._confrontos(lote, contexto)
        if confrontos:
            partidas = await self.registry.matches_of_fixtures(confrontos)
            construtor.with_matches(tuple(partidas))
        return construtor.build()

    def _confrontos(
        self, lote: SourceBatch, contexto: ResolutionContext
    ) -> list[tuple[SeasonId, TeamId, TeamId]]:
        """Os pares (temporada, mandante, visitante) que o lote pode formar.

        AMBAS AS DIREÇÕES, porque a inversão de mando precisa ser DETECTADA
        para virar candidato com penalidade — e não corrigida em silêncio
        (§24). Sem carregar o confronto invertido, ele simplesmente não
        apareceria.
        """
        pares: set[tuple[SeasonId, TeamId, TeamId]] = set()
        for registro in lote.records:
            casa = registro.text_of(SemanticRole.HOME_TEAM_NAME)
            fora = registro.text_of(SemanticRole.AWAY_TEAM_NAME)
            if not casa or not fora:
                continue
            ids_casa = self._times_possiveis(casa, contexto)
            ids_fora = self._times_possiveis(fora, contexto)
            for temporada in contexto.seasons:
                for a in ids_casa:
                    for b in ids_fora:
                        pares.add((temporada, a, b))
                        pares.add((temporada, b, a))
        return sorted(pares, key=lambda p: (str(p[0]), str(p[1]), str(p[2])))[
            : self.candidate_limit
        ]

    @staticmethod
    def _times_possiveis(texto: str, contexto: ResolutionContext) -> tuple[TeamId, ...]:
        """Os times que aquele texto PODE designar — por nome ou por alias.

        O ALIAS PRECISA CONTAR AQUI, e não contava. Buscar só por nome
        canônico funciona para `Manchester City FC` e falha para `Man City`:
        o time resolvia — o resolver consulta alias antes de nome —, o
        confronto não era carregado, e a PARTIDA ficava `UNRESOLVED`.

        O sintoma era o pior tipo possível: uma fonte que escreve abreviação,
        que é a fonte comum, resolvia todos os times e nenhuma partida. Nada
        falhava; o número de partidas resolvidas simplesmente vinha zero, e a
        explicação — «não havia candidato» — estava correta e escondia a
        causa.

        CARREGAR A MAIS NÃO MUDA DECISÃO. `MatchResolver` consulta os
        confrontos da temporada e dos times JÁ RESOLVIDOS daquele registro;
        um confronto carregado que ninguém consulta é custo, não candidato.
        Por isso ampliar aqui só pode transformar `UNRESOLVED` por ausência em
        decisão de verdade — nunca o contrário.
        """
        normalizado = contexto.normalizer.normalize(texto)
        diretos = contexto.teams_named(normalizado)
        if diretos:
            return diretos
        return tuple(
            alias.entity_id
            for alias in contexto.aliases_for(SubjectType.TEAM, normalizado)
            if isinstance(alias.entity_id, TeamId)
        )

    @staticmethod
    def _kickoff(registro: SourceRecord) -> Instant | None:
        """O horário da partida, do papel que existir.

        SEM FUSO DECLARADO, O INSTANTE É MARCADO e vira evidência FRACA —
        nunca correção silenciosa. Supor UTC aqui moveria a partida para o dia
        errado quando o jogo é à noite (§25, PR-00).
        """
        completo = registro.get(SemanticRole.KICKOFF)
        if completo and completo.moment:
            momento = completo.moment
            return instant(
                momento if momento.tzinfo else momento.replace(tzinfo=UTC)
            )
        apenas_data = registro.get(SemanticRole.KICKOFF_DATE)
        if apenas_data and apenas_data.day:
            return instant(datetime.combine(apenas_data.day, time.min, tzinfo=UTC))
        return None

    async def _impressao(self, dataset_id: DatasetId) -> ContentHash:
        """A impressão da entrada desta execução.

        DERIVADA DE (dataset, versão, validação), e não do manifesto lido do
        banco, porque o repositório de manifesto não é dependência deste caso
        de uso. O que importa é a propriedade: a mesma entrada produz a mesma
        impressão, e uma entrada diferente produz outra — que é o que fecha a
        linhagem (§78).
        """
        dataset = await self.datasets.by_id(dataset_id, with_files=False)
        assert dataset is not None
        # A impressão do manifesto fecha a linhagem. Quando ela não existe —
        # dataset sem manifesto — a execução não pode começar: sem ela, «esta
        # decisão veio do dataset X» seria uma afirmação sobre algo que pode
        # ter mudado.
        if dataset.latest_validation_id is None:
            raise ConflictError(
                "o dataset não tem validação registrada — a linhagem da decisão "
                "ficaria sem a impressão do manifesto (ADR-0019)"
            )
        return ContentHash(
            hashlib.sha256(
                f"{dataset.id}|{dataset.version}|{dataset.latest_validation_id}".encode()
            ).hexdigest()
        )

    async def _publicar(self, run: ResolutionRun, correlation_id: str | None) -> None:
        agora = self.clock.now()
        await self.publisher.publish(
            EventEnvelope.create(
                event_type=RESOLUTION_RUN_COMPLETED,
                schema_version=DOMAIN_SCHEMA,
                occurred_at=run.completed_at or agora,
                produced_at=agora,
                payload={
                    "run_id": run.id,
                    "dataset_id": str(run.dataset_id),
                    "status": run.status.value,
                    "resolver_version": str(run.versions.resolver),
                    "policy_version": str(run.versions.policy),
                    "total": run.counts.total,
                    "resolved": run.counts.resolved,
                    "needs_human": run.counts.needs_human,
                    # DITO EXPLICITAMENTE: nada disto é histórico ativo.
                    "historical_active": False,
                },
            )
        )
        if run.counts.needs_human:
            await self.publisher.publish(
                EventEnvelope.create(
                    event_type=RESOLUTION_REVIEW_REQUIRED,
                    schema_version=DOMAIN_SCHEMA,
                    occurred_at=agora,
                    produced_at=agora,
                    payload={
                        "run_id": run.id,
                        "items": run.counts.needs_human,
                        "ambiguous": run.counts.ambiguous,
                        "review_required": run.counts.review_required,
                        "correlation_id": correlation_id,
                    },
                )
            )


@final
@dataclass(frozen=True, slots=True)
class ResolveReviewItem:
    """A decisão humana — que é evidência, não exceção (§31).

    ELA PRODUZ UMA `ResolutionDecision` COMPLETA, com método `MANUAL_REVIEW`,
    ator humano e motivo obrigatório. Nunca um `UPDATE` silencioso no
    mapeamento: um mapeamento que aparece sem decisão que o explique é
    indistinguível de um mapeamento inventado.

    E O MAPEAMENTO QUE ELA CRIA É O QUE FAZ A PRÓXIMA EXECUÇÃO RESOLVER
    SOZINHA. É o ciclo que a fila de revisão existe para fechar: um humano
    decide uma vez, e o motor lembra.
    """

    review: ReviewQueueRepositoryPort
    decisions: ResolutionDecisionRepositoryPort
    provider_mappings: ProviderMappingRepositoryPort
    aliases: EntityAliasRepositoryPort
    clock: ClockPort
    audit: AuditPort

    async def execute(
        self,
        *,
        actor: Actor,
        item_id: str,
        chosen: EntityId | None,
        reason: str,
        correlation_id: str | None = None,
    ) -> ResolutionDecision:
        item = await self.review.by_id(item_id)
        if item is None:
            raise NotFoundError(f"item de revisão {item_id} não encontrado")
        if not item.status.is_open:
            raise ConflictError(
                f"o item já foi decidido ({item.status}) — decisões de revisão são "
                "imutáveis; abra outro item se a conclusão mudou"
            )
        if actor.is_automated:
            raise ValidationError(
                "a fila de revisão é humana: ela existe porque o automático já falhou"
            )

        agora = self.clock.now()
        decisao = self._decisao(item, chosen, actor, reason, agora)
        await self.decisions.append_many([decisao], run_id=item.run_id)

        fechado = (
            item.resolve_with(
                chosen=chosen, decision_id=decisao.id, actor=actor, reason=reason, at=agora
            )
            if chosen is not None
            and any(c.canonical_entity_id == chosen for c in item.candidates)
            else (
                item.link_to(
                    entity=chosen,
                    decision_id=decisao.id,
                    actor=actor,
                    reason=reason,
                    at=agora,
                )
                if chosen is not None
                else item.reject(
                    decision_id=decisao.id, actor=actor, reason=reason, at=agora
                )
            )
        )
        if not await self.review.update_status(fechado, expected_status=item.status.value):
            raise ConflictError(
                "outro operador decidiu este item primeiro — releia antes de decidir"
            )

        if chosen is not None:
            await self._memorizar(item, chosen, decisao, actor, agora)

        await self.audit.record(
            AuditEntry.of(
                AuditAction.DATASET_STAGED
                if chosen is not None
                else AuditAction.DATASET_REJECTED,
                actor=actor,
                at=agora,
                correlation_id=correlation_id,
                reason=reason,
                review_item=item.id,
                decision=decisao.id,
                subject=item.subject.subject_type.value,
            )
        )
        return decisao

    def _decisao(
        self,
        item: ResolutionReviewItem,
        chosen: EntityId | None,
        actor: Actor,
        reason: str,
        at: Instant,
    ) -> ResolutionDecision:
        versoes = DecisionVersions(
            resolver=CURRENT_RESOLVER_VERSION,
            normalizer=item.subject.source_value.normalizer_version,
            policy=CURRENT_RESOLUTION_POLICY_VERSION,
        )
        evidencia = (
            ResolutionEvidence.matched(
                EvidenceKind.PROVIDER_MAPPING,
                weight=1.0,
                explanation=ExplanationCode.HUMAN_DECISION,
                source_value=item.subject.source_value.raw,
                canonical_value=str(chosen) if chosen else None,
            ),
        )
        # A ENTRADA DA DECISÃO MANUAL É A DO ITEM QUE A ORIGINOU. A
        # referência do registro carrega dataset, arquivo e linha; a versão e
        # a impressão vêm da execução que criou o item — e é por isso que o
        # item guarda `run_id`.
        entrada = ResolutionInput(
            dataset_id=DatasetId.parse(item.subject.record_ref.split(":")[0]),
            dataset_version=DatasetVersion(major=1, minor=0),
            manifest_fingerprint=ContentHash(item.run_id.replace("-", "").ljust(64, "0")[:64]),
        )
        comum = {
            "subject_type": item.subject.subject_type,
            "provider_id": item.subject.provider_id,
            "source_value": item.subject.source_value,
            "versions": versoes,
            "decided_at": at,
            "decided_by": actor,
            "input_ref": entrada,
            # A DECISÃO HUMANA TAMBÉM APONTA PARA A LINHA. Sem isto, o registro
            # que o operador acabou de resolver continuaria invisível para a
            # fusão — e o ciclo «revisar, decidir, fundir» ficaria pela metade.
            "record_ref": item.subject.record_ref,
            "evidence": evidencia,
            "reason": reason,
        }
        if chosen is None:
            return ResolutionDecision.undecided(
                status=ResolutionStatus.REJECTED,
                method=ResolutionMethod.MANUAL_REVIEW,
                confidence=ResolutionConfidence.none(),
                **comum,  # type: ignore[arg-type]
            )
        return ResolutionDecision.resolved(
            canonical_entity_id=chosen,
            method=ResolutionMethod.MANUAL_REVIEW,
            # CONFIANÇA 1,0 NUMA DECISÃO HUMANA. Ela não é uma medida de
            # evidência automática: é a afirmação de que uma pessoa olhou e
            # decidiu, que é a autoridade mais forte que este sistema tem.
            confidence=ResolutionConfidence.certain(),
            **comum,  # type: ignore[arg-type]
        )

    async def _memorizar(
        self,
        item: ResolutionReviewItem,
        chosen: EntityId,
        decision: ResolutionDecision,
        actor: Actor,
        at: Instant,
    ) -> None:
        """Grava o que a decisão humana ensinou: alias e, se houver, mapeamento.

        É O QUE FECHA O CICLO (§88). Sem isto, o mesmo nome cairia na fila em
        toda execução, e o operador decidiria a mesma coisa indefinidamente.
        """
        alias = EntityAlias(
            id=decision.id,
            entity_type=item.subject.subject_type,
            entity_id=chosen,
            alias_original=item.subject.source_value.raw,
            alias_normalized=item.subject.source_value.normalized,
            normalizer_version=item.subject.source_value.normalizer_version,
            created_at=at,
            created_by=actor.id,
            provider_id=item.subject.provider_id,
            resolution_decision_id=decision.id,
        )
        await self.aliases.create_if_absent(alias)

        if decision.provider_ref is not None:
            proposto = ProviderEntityMapping.create(
                provider_ref=decision.provider_ref,
                entity_type=item.subject.subject_type,
                canonical_entity_id=chosen,
                resolution_decision_id=decision.id,
                at=at,
                created_by=actor.id,
            )
            existente = await self.provider_mappings.create_if_absent(proposto)
            # REAPONTAR EM SILÊNCIO REESCREVERIA TODO O HISTÓRICO já lido sob
            # a tradução antiga. O conflito explícito obriga alguém a decidir
            # qual dos dois está errado.
            assert_mapping_is_consistent(existente, proposto)


@final
@dataclass(frozen=True, slots=True)
class GetResolutionRun:
    runs: ResolutionRunRepositoryPort

    async def execute(self, run_id: str) -> ResolutionRun:
        execucao = await self.runs.by_id(run_id)
        if execucao is None:
            raise NotFoundError(f"execução de resolução {run_id} não encontrada")
        return execucao


@final
@dataclass(frozen=True, slots=True)
class ListResolutionDecisions:
    decisions: ResolutionDecisionRepositoryPort

    async def execute(
        self,
        run_id: str,
        *,
        subject: SubjectType | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[Sequence[ResolutionDecision], int]:
        return await self.decisions.by_run(
            run_id, subject=subject, limit=limit, offset=offset
        )


@final
@dataclass(frozen=True, slots=True)
class ListResolutionReviewItems:
    review: ReviewQueueRepositoryPort

    async def execute(
        self, *, filters: ReviewFilter, limit: int = 50, offset: int = 0
    ) -> tuple[Sequence[ResolutionReviewItem], int]:
        return await self.review.list(filters=filters, limit=limit, offset=offset)


def required_roles_for_matches() -> frozenset[SemanticRole]:
    """Os papéis sem os quais um dataset de partidas não é resolvível."""
    return MATCH_REQUIRED_ROLES
