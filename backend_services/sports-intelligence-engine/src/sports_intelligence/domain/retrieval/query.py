"""A query — o snapshot de AVALIAÇÃO que procura vizinhos históricos.

DUAS COISAS, E SEPARÁ-LAS É A DECISÃO:

    QuerySnapshot                 a LINHA: chave, competição, instante, valores
    HistoricalRetrievalQuery      o PEDIDO: a linha, as políticas e o K

Uma query que carregasse os valores dentro do pedido faria «este é o mesmo
pedido?» depender de 105 números, e a resposta certa é que dois pedidos são o
mesmo quando apontam para a mesma linha sob as mesmas regras.

POR QUE A QUERY VEM DA AVALIAÇÃO. O PR-05.5.2 provou `ArtifactSet = f(REFERENCE)`:
a escala foi calibrada sem enxergar nenhuma partida de avaliação. Uma query de
avaliação contra candidatos de referência é, portanto, a configuração causal
limpa — a partida da query não participou da escala que a mede.

    E É A CONFIGURAÇÃO QUE PERMITE MEDIR. Goldens, `Recall@K` de um índice
    aproximado no futuro, e comparação entre políticas: todos precisam de um
    lado que não contaminou o outro.

O CASO COMPLETO É DA QUERY TAMBÉM, e a assimetria seria tentadora. Se a query
não tiver valor em algum eixo do perfil, a saída NÃO é reduzir o perfil àquilo
que ela tem: isso faria cada query medir uma coisa diferente, e dois resultados
deixariam de ser comparáveis entre si sem que nada no objeto denunciasse. A
saída é dizer, com tipo próprio, que ela não é comparável sob este perfil.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, final

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.normalized.rows import (
    NormalizationAvailability,
)
from sports_intelligence.domain.features.normalized.versions import (
    NormalizedFeatureRepresentationSpec,
)
from sports_intelligence.domain.retrieval.candidate_policy import (
    DEFAULT_CANDIDATE_POLICY,
    CandidateUniversePolicy,
)
from sports_intelligence.domain.retrieval.profile import (
    DEFAULT_RETRIEVAL_PROFILE,
    ResolvedRetrievalProfile,
    RetrievalFeatureProfile,
)
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from sports_intelligence.domain.shared.errors import DataQualityError, ValidationError

#: O teto operacional de `K`. Ele NÃO trunca o universo — o oráculo examina
#: todo candidato elegível de qualquer jeito —, e existe para que um `K` de
#: um milhão vindo da CLI não vire um relatório impossível de ler.
MAX_K: Final[int] = 1_000


@final
@dataclass(frozen=True, slots=True)
class QuerySnapshot:
    """A linha de AVALIAÇÃO que faz a pergunta.

    ELA CARREGA A MÁSCARA JUNTO DOS VALORES. Sem ela, «este eixo vale 0,0» e
    «este eixo não tem valor» chegam iguais — e o caso completo deixaria de
    poder ser decidido.
    """

    key: HistoricalFeatureSnapshotKey
    split: DatasetSplit
    #: O CÓDIGO da competição, e NÃO o `CompetitionId`. O código é o que o
    #: Parquet grava na partição; a identidade vem do escopo do corpus, e o
    #: leitor não a tem. Derivá-la do código aqui produziria um id que se
    #: parece com o verdadeiro e não é — o `ResolvedRetrievalProfile` carrega
    #: o autêntico, vindo do pacote de artefatos.
    competition: str
    season: str
    position: GridTimePoint
    row_digest: str
    representation_fingerprint: str
    plan_fingerprint: str
    artifact_set_fingerprint: str
    values: Mapping[str, float | None]
    availabilities: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.split is not DatasetSplit.EVALUATION:
            raise ValidationError(
                f"query vinda de {self.split.value}: a autoridade de query da V1 é "
                "AVALIAÇÃO, e uma query de referência procuraria vizinhos numa "
                "população que a própria partida ajudou a calibrar",
                context={"split": self.split.value, "key": self.key.text},
            )
        if not self.row_digest.strip():
            raise ValidationError(
                f"query {self.key} sem digesto de linha: ele é o que amarra o "
                "resultado à linha exata que o produziu"
            )

    # ------------------------------------------------------- o caso completo --

    def vector_for(self, profile: ResolvedRetrievalProfile) -> tuple[float, ...] | None:
        """Os valores dos eixos do perfil, em ordem — ou `None`.

        `None` SIGNIFICA «NÃO COMPARÁVEL SOB ESTE PERFIL», e não «vetor vazio».
        Devolver uma lista curta faria o chamador somar sobre menos eixos sem
        perceber; devolver `None` obriga a decidir.
        """
        valores: list[float] = []
        for chave in profile.feature_keys:
            if self.availabilities.get(chave) != NormalizationAvailability.AVAILABLE.value:
                return None
            valor = self.values.get(chave)
            if valor is None:
                return None
            valores.append(valor)
        return tuple(valores)

    def missing_axes(self, profile: ResolvedRetrievalProfile) -> tuple[str, ...]:
        """Quais eixos do perfil faltam. Para a mensagem, e para o relatório."""
        return tuple(
            chave
            for chave in profile.feature_keys
            if self.availabilities.get(chave) != NormalizationAvailability.AVAILABLE.value
            or self.values.get(chave) is None
        )

    def is_comparable_under(self, profile: ResolvedRetrievalProfile) -> bool:
        return not profile.is_empty and self.vector_for(profile) is not None

    def __str__(self) -> str:
        return f"{self.key.text}@{self.competition}/{self.position.text}"


@final
@dataclass(frozen=True, slots=True)
class HistoricalRetrievalQuery:
    """O pedido: qual linha, sob quais regras, quantos vizinhos.

    ELE APONTA PARA A LINHA POR CHAVE, e carrega a representação esperada. A
    chave diz QUAL linha; a representação diz sob QUAL escala ela foi escrita —
    e sem a segunda, «a linha 42 do dataset X» seria comparável com a linha 42
    de um dataset que usou outro conjunto de artefatos.
    """

    dataset_version_id: str
    dataset_name: str
    dataset_version: str
    representation: NormalizedFeatureRepresentationSpec
    key: HistoricalFeatureSnapshotKey
    k: int
    policy: CandidateUniversePolicy = DEFAULT_CANDIDATE_POLICY
    profile: RetrievalFeatureProfile = DEFAULT_RETRIEVAL_PROFILE

    def __post_init__(self) -> None:
        if self.k < 1:
            raise ValidationError(
                f"K = {self.k}: um pedido de zero vizinhos não é uma pergunta",
                context={"k": str(self.k)},
            )
        if self.k > MAX_K:
            raise ValidationError(
                f"K = {self.k} acima do teto operacional de {MAX_K}: o oráculo "
                "examinaria o universo inteiro de qualquer jeito, mas o resultado "
                "seria um relatório que ninguém lê",
                context={"k": str(self.k), "max": str(MAX_K)},
            )
        if not self.dataset_version_id.strip():
            raise ValidationError("query sem versão de dataset normalizado")

    # ------------------------------------------------------------ conferência --

    def assert_snapshot_matches(self, snapshot: QuerySnapshot) -> None:
        """A linha carregada é a que o pedido pediu, sob a escala que ele diz.

        AS TRÊS IMPRESSÕES SÃO CONFERIDAS, e não só a chave. Uma linha da chave
        certa escrita sob outro plano ou outro conjunto de artefatos é um vetor
        de números na mesma ordem e em outra grandeza — o defeito mais caro
        possível, porque tudo continua parecendo funcionar.
        """
        if snapshot.key != self.key:
            raise ValidationError(
                f"a linha carregada é {snapshot.key} e o pedido é {self.key}",
                context={"loaded": snapshot.key.text, "requested": self.key.text},
            )
        for rotulo, esperado, encontrado in (
            (
                "representação",
                self.representation.fingerprint,
                snapshot.representation_fingerprint,
            ),
            (
                "plano",
                self.representation.plan_fingerprint,
                snapshot.plan_fingerprint,
            ),
            (
                "conjunto de artefatos",
                self.representation.artifact_set_fingerprint,
                snapshot.artifact_set_fingerprint,
            ),
        ):
            if esperado != encontrado:
                raise ValidationError(
                    f"a linha {snapshot.key} declara {rotulo} {encontrado[:12]} e o "
                    f"pedido espera {esperado[:12]}: os números estariam na mesma "
                    "ordem e em outra grandeza, e nada denunciaria",
                    context={"expected": esperado, "found": encontrado},
                )

    def __str__(self) -> str:
        return f"{self.key.text} K={self.k} [{self.policy.name}]"


#: O motivo tipado, para o relatório e para quem trata o erro sem ler texto.
QUERY_NOT_COMPARABLE: Final[str] = "QUERY_NOT_COMPARABLE_UNDER_PROFILE"


@final
class QueryNotComparableError(DataQualityError):
    """A query não tem todos os eixos do perfil resolvido.

    É `DataQualityError` E NÃO `ValidationError`, e a diferença é a ação. Uma
    falha de validação se conserta reenviando o pedido; esta não — o pedido
    está correto, a linha existe, e o que falta é DADO. Quem a recebe não deve
    tentar de novo: deve olhar a cobertura, ou esperar o PR-06.2.

    ELA NÃO É DEFEITO DE NINGUÉM. O PR-05.5.2 mediu que 40,7 % das células dos
    eixos robustos saem sem escala; uma query cair nessa fração é o
    comportamento esperado do baseline de caso completo, e a lista de eixos que
    ela carrega é exatamente o insumo científico do PR seguinte.

    A ALTERNATIVA SERIA REDUZIR O PERFIL À QUERY, e ela é pior: cada query
    mediria uma coisa diferente, e dois resultados deixariam de ser comparáveis
    entre si sem que nada no objeto dissesse isso.
    """

    def __init__(
        self,
        *,
        key: HistoricalFeatureSnapshotKey,
        profile_fingerprint: str,
        missing_axes: Sequence[str],
        axis_count: int,
    ) -> None:
        faltando = tuple(missing_axes)
        amostra = ", ".join(faltando[:3])
        reticencias = "…" if len(faltando) > 3 else ""
        super().__init__(
            f"{QUERY_NOT_COMPARABLE}: a query {key.text} não tem {len(faltando)} dos "
            f"{axis_count} eixos do perfil ({amostra}{reticencias}). O baseline do "
            "PR-06.1 é de CASO COMPLETO: reduzir o perfil a esta query faria cada "
            "consulta medir uma grandeza diferente",
            context={
                "axis_count": axis_count,
                "key": key.text,
                "missing_axes": list(faltando),
                "missing_count": len(faltando),
                "profile_fingerprint": profile_fingerprint,
                "reason": QUERY_NOT_COMPARABLE,
            },
        )
        self.key = key
        self.profile_fingerprint = profile_fingerprint
        self.missing_axes = faltando
        self.axis_count = axis_count

    @property
    def reason(self) -> str:
        return QUERY_NOT_COMPARABLE
