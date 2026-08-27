"""O caso de uso da recuperação exata — e as conferências que a autorizam.

A SEQUÊNCIA, e cada passo recusa uma coisa diferente:

    1. a versão normalizada     `READY`, e nenhum outro estado
    2. o conjunto de artefatos  o que a versão declarou, e não «o mais recente»
    3. a query                  existe, é de AVALIAÇÃO, e a representação bate
    4. o perfil resolvido       eixos ROBUST FITTED da competição DA QUERY
    5. o universo               REFERÊNCIA, mesma liga, mesmo instante
    6. o oráculo                todo comparável medido, top-K exato

NENHUMA LEITURA DE FATO CANÔNICO EM PASSO NENHUM. O PostgreSQL entra só nos
passos 1 e 2 — metadados de versão e os números do ajuste —, e as linhas vêm do
Parquet. Partida, evento, escalação, cotação e resultado não são tocados: a
recuperação não volta ao corpus, e é isso que torna o §102 verdadeiro por
construção em vez de por disciplina.

O PERFIL É RESOLVIDO PARA A COMPETIÇÃO DA QUERY, e a ordem importa: primeiro a
query é carregada, depois a liga dela decide quais eixos existem. Resolver o
perfil antes obrigaria a adivinhar a competição — e o §11 diz que ela vem da
query.

`READY` E SÓ `READY` (§93, §94). O ciclo de vida permite ler `SUPERSEDED`
historicamente, e este PR não usa essa permissão: a autoridade de recuperação é
a versão publicada, e ampliar isso sem necessidade seria inventar regra.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, final

from sports_intelligence.domain.corpus.versions import DatasetVersionStatus
from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.features.normalized.artifacts import (
    NormalizerArtifactSet,
)
from sports_intelligence.domain.features.normalized.plan import NormalizationPlan
from sports_intelligence.domain.features.normalized.versions import (
    NormalizedHistoricalFeatureDatasetVersion,
)
from sports_intelligence.domain.retrieval.candidate import CandidateRow
from sports_intelligence.domain.retrieval.candidate_policy import (
    DEFAULT_CANDIDATE_POLICY,
    CandidateUniversePolicy,
)
from sports_intelligence.domain.retrieval.distance import DistanceDefinition
from sports_intelligence.domain.retrieval.exact import ExactHistoricalRetriever
from sports_intelligence.domain.retrieval.profile import (
    DEFAULT_RETRIEVAL_PROFILE,
    ResolvedRetrievalProfile,
    RetrievalFeatureProfile,
)
from sports_intelligence.domain.retrieval.query import (
    HistoricalRetrievalQuery,
    QuerySnapshot,
)
from sports_intelligence.domain.retrieval.result import ExactRetrievalResult
from sports_intelligence.domain.shared.errors import NotFoundError, ValidationError
from sports_intelligence.ports.object_store.retrieval import (
    HistoricalCandidateSourcePort,
)
from sports_intelligence.ports.repositories.normalized_dataset import (
    NormalizedFeatureDatasetRepositoryPort,
    NormalizerArtifactSetRepositoryPort,
)

#: Quantas linhas o leitor entrega por lote na varredura de candidatos.
#:
#: ELE NÃO MUDA O RESULTADO — há teste de propriedade sobre isso —, e muda só a
#: memória: o oráculo mede e descarta, então o lote é o único termo que cresce.
DEFAULT_CANDIDATE_BATCH_ROWS: Final[int] = 2_000

#: Como reconstruir o `NormalizationPlan` de uma versão normalizada.
PlanFactory = Callable[[NormalizedHistoricalFeatureDatasetVersion], NormalizationPlan]


@final
@dataclass(frozen=True, slots=True)
class RetrievalResolution:
    """Versão, ajuste, query e perfil — TUDO menos a definição de distância.

    ELA APARECEU NO PR-06.2, e o motivo é que os cinco primeiros passos são
    IDÊNTICOS nos dois caminhos. O que difere entre o oráculo de caso completo
    e a recuperação ciente de disponibilidade começa no sexto: a RÉGUA.

        passos 1 a 5   versão READY, conjunto declarado, plano conferido,
                       query carregada, perfil resolvido para a liga dela
        passo 6        `DistanceDefinition` ou
                       `AvailabilityAwareDistanceDefinition`

    Duplicar os cinco primeiros faria as duas recuperações divergirem no dia em
    que alguém corrigisse uma conferência de um lado só — e a comparação entre
    elas deixaria de medir a política de ausência, que é a única coisa que ela
    existe para medir.
    """

    version: NormalizedHistoricalFeatureDatasetVersion
    dataset_name: str
    artifact_set: NormalizerArtifactSet
    plan: NormalizationPlan
    snapshot: QuerySnapshot
    profile: ResolvedRetrievalProfile

    @property
    def competition(self) -> str:
        return self.snapshot.competition

    @property
    def version_text(self) -> str:
        return str(self.version.version)

    def summary(self) -> Mapping[str, Any]:
        return {
            "axis_count": self.profile.axis_count,
            "competition": self.competition,
            "position": self.snapshot.position.text,
            "profile_fingerprint": self.profile.fingerprint,
            **self.profile.diagnostics(),
        }


@final
@dataclass(frozen=True, slots=True)
class RetrievalContext:
    """O que a resolução da query montou, antes de a varredura começar.

    ELE EXISTE PARA SER INSPECIONADO. `DescribeCandidateUniverse` e o benchmark
    precisam do perfil e do instante sem pagar a varredura, e devolver isso
    numa tupla de seis elementos faria cada chamador lembrar a ordem.
    """

    version: NormalizedHistoricalFeatureDatasetVersion
    dataset_name: str
    artifact_set: NormalizerArtifactSet
    plan: NormalizationPlan
    snapshot: QuerySnapshot
    profile: ResolvedRetrievalProfile
    distance: DistanceDefinition

    @property
    def competition(self) -> str:
        return self.snapshot.competition

    @property
    def version_text(self) -> str:
        return str(self.version.version)

    def summary(self) -> Mapping[str, Any]:
        return {
            "axis_count": self.profile.axis_count,
            "competition": self.competition,
            "distance_fingerprint": self.distance.fingerprint,
            "position": self.snapshot.position.text,
            "profile_fingerprint": self.profile.fingerprint,
            **self.profile.diagnostics(),
        }


@final
@dataclass(frozen=True, slots=True)
class RetrieveExactHistoricalNeighbors:
    """O top-K exato de uma query de AVALIAÇÃO sobre candidatos de REFERÊNCIA."""

    normalized: NormalizedFeatureDatasetRepositoryPort
    artifacts: NormalizerArtifactSetRepositoryPort
    source: HistoricalCandidateSourcePort
    #: COMO RECONSTRUIR O PLANO daquela versão. Ele é uma FUNÇÃO e não uma
    #: constante porque o plano depende da fronteira da divisão (PR-05.1 §89),
    #: que é da versão crua de origem — e o caso de uso não a conhece.
    plan_factory: PlanFactory
    batch_rows: int = DEFAULT_CANDIDATE_BATCH_ROWS

    async def execute(
        self,
        *,
        version_id: str,
        key: HistoricalFeatureSnapshotKey,
        k: int,
        policy: CandidateUniversePolicy = DEFAULT_CANDIDATE_POLICY,
        profile: RetrievalFeatureProfile = DEFAULT_RETRIEVAL_PROFILE,
        batch_rows: int | None = None,
    ) -> ExactRetrievalResult:
        contexto = await self.resolve(
            version_id=version_id, key=key, profile=profile, feature_keys=None
        )
        pedido = HistoricalRetrievalQuery(
            dataset_version_id=contexto.version.id,
            dataset_name=contexto.dataset_name,
            dataset_version=contexto.version_text,
            representation=contexto.version.representation,
            key=key,
            k=k,
            policy=policy,
            profile=profile,
        )
        retriever = ExactHistoricalRetriever(
            policy=policy, profile=contexto.profile, distance=contexto.distance
        )
        return retriever.retrieve(
            query=pedido,
            snapshot=contexto.snapshot,
            candidates=await self._candidatos(contexto, batch_rows),
            reference_content_fingerprint=self.reference_fingerprint(contexto.version),
        )

    # ------------------------------------------------------------ a resolução --

    async def resolve_base(
        self,
        *,
        version_id: str,
        key: HistoricalFeatureSnapshotKey,
        profile: RetrievalFeatureProfile = DEFAULT_RETRIEVAL_PROFILE,
        feature_keys: Sequence[str] | None = None,
    ) -> RetrievalResolution:
        """Os cinco primeiros passos, SEM a régua — ver `RetrievalResolution`.

        ELA É PÚBLICA PORQUE O PR-06.2 A REUSA. A recuperação ciente de
        disponibilidade precisa exatamente destas conferências e de outra
        definição de distância; chamar `resolve` não serviria, porque ele
        constrói a régua do caso completo — e o construtor dela recusa, com
        razão, um perfil que declara cobrar a ausência.
        """
        versao = await self._versao(version_id)
        nome = await self._nome(versao)
        conjunto = await self._conjunto(versao)
        plano = self.plan_factory(versao)
        self._conferir_plano(plano, versao)

        # A QUERY VEM PRIMEIRO, e o perfil depois: a competição dela é o que
        # decide quais eixos existem (§11, §43).
        snapshot = await self._query(versao, nome, key, feature_keys or plano.robust_keys)
        pacote = conjunto.bundle_of(snapshot.competition)
        return RetrievalResolution(
            version=versao,
            dataset_name=nome,
            artifact_set=conjunto,
            plan=plano,
            snapshot=snapshot,
            profile=profile.resolve(plan=plano, bundle=pacote),
        )

    async def resolve(
        self,
        *,
        version_id: str,
        key: HistoricalFeatureSnapshotKey,
        profile: RetrievalFeatureProfile = DEFAULT_RETRIEVAL_PROFILE,
        feature_keys: Sequence[str] | None = None,
    ) -> RetrievalContext:
        """O mesmo, com a régua do CASO COMPLETO por cima.

        ELA É PÚBLICA porque a inspeção e o benchmark a usam. «Qual o perfil
        desta competição?» não pode custar uma varredura do universo.
        """
        base = await self.resolve_base(
            version_id=version_id, key=key, profile=profile, feature_keys=feature_keys
        )
        return RetrievalContext(
            version=base.version,
            dataset_name=base.dataset_name,
            artifact_set=base.artifact_set,
            plan=base.plan,
            snapshot=base.snapshot,
            profile=base.profile,
            distance=DistanceDefinition(profile=base.profile),
        )

    async def _versao(self, version_id: str) -> NormalizedHistoricalFeatureDatasetVersion:
        versao = await self.normalized.version_by_id(version_id)
        if versao is None:
            raise NotFoundError(
                f"a versão normalizada {version_id} não existe",
                context={"version_id": version_id},
            )
        if versao.status is not DatasetVersionStatus.READY:
            raise ValidationError(
                f"a versão normalizada {versao.version} está em {versao.status}: a "
                "autoridade de recuperação é a versão PUBLICADA, e vizinhos tirados "
                "de um dataset que ainda pode mudar não são reproduzíveis",
                context={"status": versao.status.value},
            )
        return versao

    async def _conjunto(
        self, versao: NormalizedHistoricalFeatureDatasetVersion
    ) -> NormalizerArtifactSet:
        """O ajuste QUE A VERSÃO DECLAROU, e não o mais recente.

        A DIFERENÇA É TUDO. Buscar «o conjunto publicado mais novo» resolveria
        o perfil sobre artefatos que não foram os usados para escrever as
        linhas — e a distância sairia sobre eixos que a coluna não tem.
        """
        conjunto = await self.artifacts.by_id(versao.representation.artifact_set_id)
        if conjunto is None:
            raise NotFoundError(
                f"o conjunto de artefatos {versao.representation.artifact_set_id} não "
                "existe: a versão aponta para um ajuste que sumiu",
                context={"artifact_set_id": versao.representation.artifact_set_id},
            )
        if conjunto.fingerprint != versao.representation.artifact_set_fingerprint:
            raise ValidationError(
                "o conjunto de artefatos carregado tem impressão diferente da que a "
                "versão declarou: os números não são os que escreveram estas linhas",
                context={
                    "declared": versao.representation.artifact_set_fingerprint,
                    "loaded": conjunto.fingerprint,
                },
            )
        return conjunto

    def _conferir_plano(
        self, plano: NormalizationPlan, versao: NormalizedHistoricalFeatureDatasetVersion
    ) -> None:
        if plano.fingerprint != versao.representation.plan_fingerprint:
            raise ValidationError(
                "o plano reconstruído não é o da versão normalizada: os eixos e as "
                "estratégias seriam de outra classificação, e o perfil escolheria "
                "colunas que este dataset não tem",
                context={
                    "plan": plano.fingerprint,
                    "version_plan": versao.representation.plan_fingerprint,
                },
            )

    async def _query(
        self,
        versao: NormalizedHistoricalFeatureDatasetVersion,
        dataset_name: str,
        key: HistoricalFeatureSnapshotKey,
        feature_keys: Sequence[str],
    ) -> QuerySnapshot:
        snapshot = await self.source.load_query(
            dataset_name=dataset_name,
            version=str(versao.version),
            key=key,
            feature_keys=list(feature_keys),
        )
        if snapshot is None:
            raise NotFoundError(
                f"a linha {key.text} não existe na metade de AVALIAÇÃO da versão "
                f"{versao.version}: ou a chave está errada, ou ela é de referência — "
                "e uma linha de referência não é uma query",
                context={"key": key.text, "version": str(versao.version)},
            )
        return snapshot

    # ----------------------------------------------------------- a varredura --

    async def candidates(
        self, resolution: RetrievalResolution, batch_rows: int | None = None
    ) -> list[CandidateRow]:
        """Os candidatos do universo daquela query, em lista.

        PÚBLICA PELO MESMO MOTIVO DE `resolve_base`: o PR-06.2 varre o MESMO
        universo, e uma segunda implementação da leitura faria os dois
        universos poderem divergir — que é exatamente o que o §5 proíbe.
        """
        return await self._candidatos_de(resolution, batch_rows)

    async def _candidatos(self, contexto: RetrievalContext, batch_rows: int | None) -> list[Any]:
        return await self._candidatos_de(contexto, batch_rows)

    async def _candidatos_de(
        self, resolution: RetrievalResolution | RetrievalContext, batch_rows: int | None
    ) -> list[CandidateRow]:
        """Os candidatos, materializados em lista.

        ELA É UMA LISTA E NÃO UM GERADOR, e a decisão é medida: o universo de
        um instante numa competição são as partidas daquela liga naquele
        minuto — centenas, e não centenas de milhares —, porque a grade produz
        UMA linha por partida por minuto. Segurar isso é `O(partidas)`, e o que
        o §129 proíbe é segurar o dataset.

        O ORÁCULO CONSOME UM ITERÁVEL, então trocar isto por um gerador
        assíncrono não muda o resultado — há teste de propriedade sobre lote e
        ordem. Se o benchmark mostrar que a lista pesa, a troca é local.
        """
        linhas: list[CandidateRow] = []
        async for lote in self.source.stream_candidates(
            dataset_name=resolution.dataset_name,
            version=resolution.version_text,
            competition=resolution.competition,
            position=resolution.snapshot.position,
            feature_keys=list(resolution.profile.feature_keys),
            batch_rows=batch_rows or self.batch_rows,
        ):
            linhas.extend(lote)
        return linhas

    async def _nome(self, versao: NormalizedHistoricalFeatureDatasetVersion) -> str:
        """O nome do dataset — do REGISTRO, e não de uma constante.

        ELE CUSTA UMA CONSULTA A MAIS POR QUERY, e a alternativa era pior:
        assumir `DEFAULT_NORMALIZED_DATASET_NAME` funcionaria enquanto houvesse
        um nome só, e no dia do segundo a recuperação montaria o prefixo do
        bucket errado — e a resposta seria «zero candidatos», que é
        indistinguível de uma competição vazia.
        """
        dataset = await self.normalized.dataset_by_id(versao.dataset_id)
        if dataset is None:
            raise NotFoundError(
                f"o dataset normalizado {versao.dataset_id} não existe: a versão "
                "aponta para uma identidade que sumiu, e sem o nome não há prefixo "
                "no object store",
                context={"dataset_id": versao.dataset_id},
            )
        return dataset.name

    @staticmethod
    def reference_fingerprint(versao: NormalizedHistoricalFeatureDatasetVersion) -> str:
        """A impressão da REFERÊNCIA normalizada — cega para a avaliação.

        É ELA QUE ENTRA NA IDENTIDADE DO UNIVERSO, e não a global. A global
        cobre as duas metades: usá-la faria uma partida acrescentada à
        avaliação mudar a impressão do universo sem que candidato nenhum
        mudasse (ADR-0039, §95).
        """
        impressao = versao.normalized_reference_content_fingerprint
        if impressao is None:
            raise ValidationError(
                f"a versão {versao.version} não tem impressão de REFERÊNCIA: sem ela, "
                "«este universo é o mesmo de antes» deixa de ser verificável",
                context={"version_id": versao.id},
            )
        return impressao.value


@final
@dataclass(frozen=True, slots=True)
class DescribeCandidateUniverse:
    """O universo de uma query, sem calcular distância nenhuma.

    ELE EXISTE PARA INSPEÇÃO E BENCHMARK. «Quantos candidatos esta query tem?»
    e «quais eixos sobraram nesta liga?» são perguntas que se faz antes de
    pagar a varredura — e responder as duas rodando a recuperação inteira faria
    o diagnóstico custar o mesmo que o resultado.
    """

    retriever: RetrieveExactHistoricalNeighbors
    source: HistoricalCandidateSourcePort

    async def execute(
        self,
        *,
        version_id: str,
        key: HistoricalFeatureSnapshotKey,
        profile: RetrievalFeatureProfile = DEFAULT_RETRIEVAL_PROFILE,
    ) -> Mapping[str, Any]:
        contexto = await self.retriever.resolve(version_id=version_id, key=key, profile=profile)
        universo = await self.source.count_candidates(
            dataset_name=contexto.dataset_name,
            version=contexto.version_text,
            competition=contexto.competition,
            position=contexto.snapshot.position,
        )
        return {
            **contexto.summary(),
            "query_comparable": contexto.snapshot.is_comparable_under(contexto.profile),
            "query_missing_axes": list(contexto.snapshot.missing_axes(contexto.profile)),
            "universe_count": universo,
        }


@final
@dataclass(frozen=True, slots=True)
class RetrievalDiagnostics:
    """As contagens agregadas de um conjunto de queries.

    ELAS SÃO O PRODUTO CIENTÍFICO DO PR (§114, §127). «Quantas queries são
    comparáveis?» e «que fração dos candidatos sobrevive ao caso completo?» são
    os dois números que justificam o PR-06.2 — e um relatório que só mostrasse
    rankings os esconderia.
    """

    queries_total: int = 0
    queries_comparable: int = 0
    queries_rejected: int = 0
    universe_rows: int = 0
    comparable_rows: int = 0
    ineligible: dict[str, int] = field(default_factory=dict)

    @property
    def query_comparability_rate(self) -> float:
        return 0.0 if not self.queries_total else self.queries_comparable / self.queries_total

    @property
    def candidate_comparable_ratio(self) -> float:
        return 0.0 if not self.universe_rows else self.comparable_rows / self.universe_rows

    def summary(self) -> Mapping[str, Any]:
        return {
            "candidate_comparable_ratio": self.candidate_comparable_ratio,
            "comparable_rows": self.comparable_rows,
            "queries_comparable": self.queries_comparable,
            "queries_rejected": self.queries_rejected,
            "queries_total": self.queries_total,
            "query_comparability_rate": self.query_comparability_rate,
            "universe_rows": self.universe_rows,
            **{f"ineligible_{k}": v for k, v in sorted(self.ineligible.items())},
        }
