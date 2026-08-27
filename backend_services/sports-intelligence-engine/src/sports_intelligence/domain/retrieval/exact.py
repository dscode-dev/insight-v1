"""O oráculo — todo candidato comparável avaliado, top-K em memória limitada.

    ExactTopK(q) = TopK_(d², chave)( { d²(q,c) : c ∈ C_q } )

DUAS COISAS QUE PARECEM SE CONTRADIZER E NÃO SE CONTRADIZEM:

    EXAUSTIVO    todo candidato comparável tem distância calculada. Nenhuma
                 poda por distância, nenhuma parada antecipada, nenhuma
                 amostra
    LIMITADO     a memória é `O(K + lote)`, e não `O(candidatos)`

O HEAP É O QUE AS CONCILIA. Ele guarda `K` elementos e descarta o resto — mas
descarta DEPOIS de calcular a distância, e não antes. A diferença entre isto e
uma busca aproximada é exatamente essa: aqui o candidato descartado foi medido
e perdeu; lá ele nunca foi visitado.

    heap limitado  ≠  busca aproximada
    O(C log K)        e não O(C log C)

O HEAP É DE MÁXIMO SOBRE UMA CHAVE INVERTIDA. `heapq` é de mínimo, e o que
precisamos descartar é o PIOR dos `K` melhores. A inversão precisa cobrir a
chave inteira — distância e desempate —, porque um heap que invertesse só a
distância desempataria ao contrário e produziria um top-K correto em conteúdo e
errado em ordem quando houvesse empate no corte.

A ORDEM DE ITERAÇÃO NÃO PODE IMPORTAR, e há três lugares onde ela poderia:

    o heap         `heappushpop` compara pela chave completa, então dois
                   candidatos empatados entram e saem pela chave canônica, e
                   não pela ordem de chegada
    o corte do K   quando o K-ésimo e o (K+1)-ésimo empatam em distância, quem
                   fica é decidido pela chave — e não por quem chegou antes
    a saída        o heap é esvaziado e reordenado pela chave canônica
                   completa antes de virar resultado

    UM `<` NO LUGAR DE UM `<=` EM QUALQUER DOS TRÊS produziria um ranking que
    muda com o tamanho do lote — e o teste de propriedade de lote existe
    justamente porque esse defeito é invisível em corpus pequeno.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable
from dataclasses import dataclass
from typing import final

from sports_intelligence.domain.retrieval.candidate import (
    CandidateRow,
    CandidateUniverseAccumulator,
    CandidateUniverseDescriptor,
)
from sports_intelligence.domain.retrieval.candidate_policy import (
    CandidateUniversePolicy,
    IneligibilityReason,
)
from sports_intelligence.domain.retrieval.distance import DistanceDefinition
from sports_intelligence.domain.retrieval.neighbor import HistoricalNeighbor
from sports_intelligence.domain.retrieval.profile import ResolvedRetrievalProfile
from sports_intelligence.domain.retrieval.query import (
    HistoricalRetrievalQuery,
    QueryNotComparableError,
    QuerySnapshot,
)
from sports_intelligence.domain.retrieval.result import ExactRetrievalResult
from sports_intelligence.domain.shared.errors import ValidationError


@final
@dataclass(frozen=True, slots=True, order=True)
class _Classificado:
    """Um candidato medido, com a chave de ordenação COMPLETA.

    `order=True` E OS CAMPOS NESTA ORDEM: a comparação é `(d², chave)`, que é
    exatamente a ordem canônica do ranking. Deixar a chave de fora faria o heap
    desempatar por acaso.
    """

    squared_distance: float
    canonical_key: str
    row: CandidateRow


@final
class _TopK:
    """O heap limitado. `K` elementos, e o pior deles sempre no topo.

    ELE GUARDA A CHAVE INVERTIDA. `heapq` é de mínimo; para descartar o pior
    dos `K` melhores precisamos que o pior esteja no topo, e a inversão cobre
    distância E desempate — ver o cabeçalho do módulo.
    """

    __slots__ = ("_heap", "_k", "_vistos")

    def __init__(self, k: int) -> None:
        if k < 1:
            raise ValidationError(f"top-K com K = {k}")
        self._k = k
        self._heap: list[tuple[float, _ChaveInvertida, _Classificado]] = []
        self._vistos = 0

    def offer(self, item: _Classificado) -> None:
        """Oferece um candidato JÁ MEDIDO. Ele entra, ou perde — e some."""
        self._vistos += 1
        entrada = (-item.squared_distance, _ChaveInvertida(item.canonical_key), item)
        if len(self._heap) < self._k:
            heapq.heappush(self._heap, entrada)
            return
        # `heappushpop` COMPARA E DESCARTA NUMA OPERAÇÃO. Com a chave invertida,
        # o topo é o PIOR dos K melhores: se o novo for melhor que ele, ele sai.
        heapq.heappushpop(self._heap, entrada)

    @property
    def offered(self) -> int:
        """Quantos candidatos foram MEDIDOS — e não quantos sobraram."""
        return self._vistos

    @property
    def size(self) -> int:
        return len(self._heap)

    def drain(self) -> list[_Classificado]:
        """Os `min(K, medidos)` melhores, na ordem canônica ASCENDENTE.

        A REORDENAÇÃO FINAL É SOBRE O ITEM, e não sobre a chave invertida: o
        heap devolve na ordem dele, e o ranking é `(d², chave)` crescente.
        """
        return sorted(item for _, _, item in self._heap)


@final
@dataclass(frozen=True, slots=True)
class _ChaveInvertida:
    """Uma chave de texto que compara ao contrário.

    ELA EXISTE PORQUE A INVERSÃO DA DISTÂNCIA É ARITMÉTICA (`-d²`) E A DA CHAVE
    NÃO É. Sem ela, o heap ordenaria a distância invertida e a chave direta — e
    um empate no corte do `K` escolheria o candidato de chave MAIOR, que é o
    oposto da ordem canônica.
    """

    key: str

    #: `heapq` SÓ PRECISA DE `__lt__`, e por isso `order=True` não entra: o
    #: gerador de comparações do `dataclass` recusa conviver com um `__lt__`
    #: escrito à mão, e é justamente o à mão que faz a inversão.
    def __lt__(self, other: _ChaveInvertida) -> bool:
        return self.key > other.key


@final
@dataclass(frozen=True, slots=True)
class ExactHistoricalRetriever:
    """A varredura exata. Pura: não lê nada, não escreve nada.

    ELA RECEBE OS CANDIDATOS PRONTOS, em vez de ir buscá-los. É o que torna a
    invariância de ordem e de lote demonstrável por teste de propriedade sobre
    listas em memória — sem PostgreSQL, sem bucket, sem Parquet.
    """

    policy: CandidateUniversePolicy
    profile: ResolvedRetrievalProfile
    distance: DistanceDefinition

    def __post_init__(self) -> None:
        if self.distance.profile.fingerprint != self.profile.fingerprint:
            raise ValidationError(
                "a definição de distância percorre outro perfil resolvido: os eixos "
                "somados não seriam os eixos declarados, e o número sairia plausível",
                context={
                    "profile": self.profile.fingerprint,
                    "distance_profile": self.distance.profile.fingerprint,
                },
            )

    def retrieve(
        self,
        *,
        query: HistoricalRetrievalQuery,
        snapshot: QuerySnapshot,
        candidates: Iterable[CandidateRow],
        reference_content_fingerprint: str,
    ) -> ExactRetrievalResult:
        """O top-K exato. Todo candidato comparável é medido antes da escolha."""
        query.assert_snapshot_matches(snapshot)
        self._conferir_query(snapshot)
        vetor_da_query = snapshot.vector_for(self.profile)
        if vetor_da_query is None:
            raise QueryNotComparableError(
                key=snapshot.key,
                profile_fingerprint=self.profile.fingerprint,
                missing_axes=snapshot.missing_axes(self.profile),
                axis_count=self.profile.axis_count,
            )

        universo = CandidateUniverseAccumulator()
        topo = _TopK(query.k)
        for candidato in candidates:
            self._conferir_alinhamento(candidato, snapshot)
            universo.admit(candidato)
            motivo = self._inelegibilidade(candidato, snapshot)
            if motivo is not None:
                universo.reject(motivo)
                continue
            vetor = candidato.vector_for(self.profile)
            if vetor is None:  # pragma: no cover — `_inelegibilidade` já cobriu
                universo.reject(IneligibilityReason.INCOMPLETE_PROFILE)
                continue
            topo.offer(
                _Classificado(
                    squared_distance=self.distance.evaluate(vetor_da_query, vetor),
                    canonical_key=candidato.key.text,
                    row=candidato,
                )
            )

        descritor = universo.finalize(
            policy=self.policy,
            competition=snapshot.competition,
            position=snapshot.position,
            query_key=snapshot.key,
            reference_content_fingerprint=reference_content_fingerprint,
            dataset_version_id=query.dataset_version_id,
            representation_fingerprint=query.representation.fingerprint,
        )
        return self._resultado(query, snapshot, descritor, topo)

    # ------------------------------------------------------------ as guardas --

    def _conferir_query(self, snapshot: QuerySnapshot) -> None:
        if self.profile.is_empty:
            raise QueryNotComparableError(
                key=snapshot.key,
                profile_fingerprint=self.profile.fingerprint,
                missing_axes=(),
                axis_count=0,
            )
        if snapshot.competition != self.profile.competition:
            raise ValidationError(
                f"a query é de {snapshot.competition} e o perfil foi resolvido para "
                f"{self.profile.competition}: os eixos e as escalas são de outra liga",
                context={
                    "query": snapshot.competition,
                    "profile": self.profile.competition,
                },
            )

    def _conferir_alinhamento(self, candidate: CandidateRow, snapshot: QuerySnapshot) -> None:
        """O que o leitor já deveria ter filtrado — conferido mesmo assim.

        DEFESA EM PROFUNDIDADE, e não desconfiança gratuita: a poda por
        partição e o predicado são do ADAPTADOR, e um adaptador novo — um
        duplo de teste, um leitor diferente — entregaria candidatos errados sem
        que nada denunciasse. Aqui a violação para, e diz qual foi.
        """
        if candidate.competition != snapshot.competition:
            raise ValidationError(
                f"candidato de {candidate.competition} para uma query de "
                f"{snapshot.competition}: a escala é ajustada por competição, e "
                "cruzá-las compara números normalizados por medianas diferentes",
                context={"candidate": candidate.key.text},
            )
        if not candidate.position.aligns_with(snapshot.position):
            raise ValidationError(
                f"candidato em {candidate.position.text} para uma query em "
                f"{snapshot.position.text}: sob "
                f"{self.policy.time_alignment.value} o instante é EXATO, e um "
                "deslocamento de relógio viraria a maior parcela da distância",
                context={
                    "candidate": candidate.position.text,
                    "query": snapshot.position.text,
                },
            )

    def _inelegibilidade(
        self, candidate: CandidateRow, snapshot: QuerySnapshot
    ) -> IneligibilityReason | None:
        """Por que este candidato do universo não recebe distância — ou `None`.

        A ORDEM DAS PERGUNTAS IMPORTA. «Mesma partida» e «representação
        divergente» são ESTRUTURAIS — elas não deveriam acontecer —, e
        `INCOMPLETE_PROFILE` é o caso normal. Perguntar o normal primeiro
        contaria um defeito estrutural como ausência de dado, e a evidência do
        PR-06.2 sairia inflada.
        """
        if self.policy.excludes_same_match and candidate.match_id == self._match_da_query(snapshot):
            return IneligibilityReason.SAME_MATCH
        if candidate.representation_fingerprint != snapshot.representation_fingerprint:
            return IneligibilityReason.REPRESENTATION_MISMATCH
        if candidate.vector_for(self.profile) is None:
            return IneligibilityReason.INCOMPLETE_PROFILE
        return None

    @staticmethod
    def _match_da_query(snapshot: QuerySnapshot) -> str:
        """A partida da query. Ela vem da CHAVE, e não de um campo à parte.

        `HistoricalFeatureSnapshotKey` É `(match_key, grid_index)`, e o
        `match_key` é o texto do `MatchId`. Guardar a partida duas vezes abriria
        a chance de as duas divergirem — e a exclusão da própria partida
        passaria a depender de qual delas o código olhou.
        """
        return snapshot.key.match_key

    # ----------------------------------------------------------- o resultado --

    def _resultado(
        self,
        query: HistoricalRetrievalQuery,
        snapshot: QuerySnapshot,
        descriptor: CandidateUniverseDescriptor,
        topo: _TopK,
    ) -> ExactRetrievalResult:
        vizinhos = tuple(
            HistoricalNeighbor(
                rank=posicao,
                key=item.row.key,
                match_id=item.row.match_id,
                competition=item.row.competition,
                season=item.row.season,
                position=item.row.position,
                row_digest=item.row.row_digest,
                squared_distance=item.squared_distance,
                resolved_profile_fingerprint=self.profile.fingerprint,
                distance_definition_fingerprint=self.distance.fingerprint,
            )
            for posicao, item in enumerate(topo.drain(), start=1)
        )
        return ExactRetrievalResult(
            query_key=snapshot.key,
            query_row_digest=snapshot.row_digest,
            competition=snapshot.competition,
            candidate_policy_fingerprint=self.policy.fingerprint,
            candidate_universe_fingerprint=descriptor.fingerprint,
            retrieval_profile_fingerprint=self.profile.base.fingerprint,
            resolved_profile_fingerprint=self.profile.fingerprint,
            distance_definition_fingerprint=self.distance.fingerprint,
            axis_count=self.profile.axis_count,
            requested_k=query.k,
            universe_count=descriptor.candidate_count,
            comparable_count=topo.offered,
            neighbors=vizinhos,
            ineligible=dict(descriptor.ineligible),
            exhaustive=True,
        )
