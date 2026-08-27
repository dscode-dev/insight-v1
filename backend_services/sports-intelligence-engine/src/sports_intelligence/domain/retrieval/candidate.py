"""O universo de candidatos — quem entrou, quem não entrou, e a impressão.

TRÊS COISAS, E A ORDEM DELAS É O CONTRATO:

    CandidateRow           uma linha de REFERÊNCIA como o leitor a entrega
    CandidateUniverseAccumulator  a varredura, em fluxo e em ordem
    CandidateUniverseDescriptor   o que ela viu, com identidade própria

A IMPRESSÃO DO UNIVERSO É O QUE TORNA A INVARIANTE VERIFICÁVEL. Ela cobre a
política, a competição, o instante e as IDENTIDADES SEMÂNTICAS dos candidatos,
em ordem. Não cobre — e a lista é tão importante quanto a primeira:

    chave de objeto        duas gravações do mesmo conteúdo em arquivos
                           diferentes são o mesmo universo
    id de banco            idem
    ordem de iteração      idem: a impressão é sobre o CONJUNTO ordenado
                           canonicamente, e não sobre a ordem de chegada
    carimbo de tempo       idem

    SEM ISSO, «acrescentar uma partida à AVALIAÇÃO não muda o universo» seria
    indemonstrável: bastaria o escritor fechar um Parquet noutro lugar para a
    impressão mudar, e ninguém saberia dizer se o universo mudou de verdade.

A ORDEM CANÔNICA NÃO É A DE CHEGADA. O leitor entrega partição a partição, e
dentro delas em ordem de chave; a impressão ordena as identidades antes de
fechar. Isso é diferente do dataset normalizado, onde a impressão é de FLUXO e
recusa a inversão — e a diferença tem motivo: lá a ordem física é parte do que
se quer provar; aqui o universo é um CONJUNTO, e duas varreduras que o
percorram em ordens diferentes viram o mesmo universo.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, final

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.normalized.rows import (
    NormalizationAvailability,
)
from sports_intelligence.domain.retrieval.candidate_policy import (
    CandidateUniversePolicy,
    IneligibilityReason,
)
from sports_intelligence.domain.retrieval.profile import ResolvedRetrievalProfile
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError

UNIVERSE_FINGERPRINT_ALGORITHM: Final[str] = "candidate-universe-sha256-v1"


@final
@dataclass(frozen=True, slots=True)
class CandidateRow:
    """Uma linha de REFERÊNCIA alinhada à query, como o leitor a entrega.

    ELA CARREGA SÓ O QUE A RECUPERAÇÃO PRECISA — identidade, posição, digesto,
    os valores dos eixos do perfil e as máscaras deles. Não carrega as 105
    dimensões: o perfil resolvido usa uma fração delas, e ler o resto seria
    pagar a leitura inteira para descartar.
    """

    key: HistoricalFeatureSnapshotKey
    split: DatasetSplit
    match_id: str
    competition: str
    season: str
    position: GridTimePoint
    row_digest: str
    representation_fingerprint: str
    values: Mapping[str, float | None]
    availabilities: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.split is not DatasetSplit.REFERENCE:
            raise ValidationError(
                f"candidato vindo de {self.split.value}: o universo da V1 é REFERÊNCIA, "
                "e uma linha de avaliação como candidato seria medida por uma escala "
                "que ela ajudou a definir (ADR-0039)",
                context={"split": self.split.value, "key": self.key.text},
            )

    @property
    def semantic_identity(self) -> str:
        """A identidade que entra na impressão do universo.

        É `(chave, digesto)`, e não a chave sozinha: a chave diz QUAL linha, o
        digesto diz o QUE ela contém. Duas versões do dataset com a mesma chave
        e conteúdos diferentes não são o mesmo universo.
        """
        return f"{self.key.text}:{self.row_digest}"

    def vector_for(self, profile: ResolvedRetrievalProfile) -> tuple[float, ...] | None:
        """Os valores dos eixos do perfil, em ordem — ou `None` se faltar um."""
        valores: list[float] = []
        for chave in profile.feature_keys:
            if self.availabilities.get(chave) != NormalizationAvailability.AVAILABLE.value:
                return None
            valor = self.values.get(chave)
            if valor is None:
                return None
            valores.append(valor)
        return tuple(valores)

    def __str__(self) -> str:
        return f"{self.key.text}@{self.competition}/{self.position.text}"


@final
class CandidateUniverseAccumulator:
    """A varredura do universo — em fluxo, sem guardar as linhas.

    ELE GUARDA IDENTIDADES, E NÃO LINHAS. Um universo de dez mil candidatos são
    dez mil cadeias curtas, e não dez mil objetos com vetores: a impressão
    precisa das identidades, e o top-K precisa de `K` — nenhum dos dois precisa
    do universo inteiro em memória.

    ELE NÃO DECIDE ELEGIBILIDADE POR CONTA PRÓPRIA. Quem chama já filtrou por
    metade, competição e instante — o leitor faz isso por poda de partição e
    predicado. O que ele registra são as exclusões que só o domínio pode
    decidir: mesma partida, representação divergente, perfil incompleto.
    """

    __slots__ = ("_identidades", "_inelegiveis", "_vistos")

    def __init__(self) -> None:
        self._identidades: list[str] = []
        self._inelegiveis: dict[str, int] = {r.value: 0 for r in IneligibilityReason}
        self._vistos: set[str] = set()

    def admit(self, row: CandidateRow) -> None:
        """Registra um candidato do universo.

        A REPETIÇÃO É RECUSADA. A mesma linha entrando duas vezes apareceria
        duas vezes no top-K e mudaria a impressão do universo — e a causa mais
        provável seria uma partição lida em dobro, que é defeito de leitura e
        não do dado.
        """
        identidade = row.semantic_identity
        if identidade in self._vistos:
            raise ValidationError(
                f"candidato {row.key} admitido duas vezes no mesmo universo: ele "
                "apareceria em dobro no top-K, e a causa mais provável é uma "
                "partição lida duas vezes",
                context={"key": row.key.text},
            )
        self._vistos.add(identidade)
        self._identidades.append(identidade)

    def reject(self, reason: IneligibilityReason) -> None:
        """Conta um candidato do universo que não recebeu distância."""
        self._inelegiveis[reason.value] += 1

    @property
    def admitted(self) -> int:
        return len(self._identidades)

    def finalize(
        self,
        *,
        policy: CandidateUniversePolicy,
        competition: str,
        position: GridTimePoint,
        query_key: HistoricalFeatureSnapshotKey,
        reference_content_fingerprint: str,
        dataset_version_id: str,
        representation_fingerprint: str,
    ) -> CandidateUniverseDescriptor:
        return CandidateUniverseDescriptor(
            policy_fingerprint=policy.fingerprint,
            policy_identity=policy.identity,
            competition=competition,
            position=position,
            query_key=query_key,
            candidate_identities=tuple(sorted(self._identidades)),
            reference_content_fingerprint=reference_content_fingerprint,
            dataset_version_id=dataset_version_id,
            representation_fingerprint=representation_fingerprint,
            ineligible={
                motivo: contagem
                for motivo, contagem in sorted(self._inelegiveis.items())
                if contagem
            },
        )


@final
@dataclass(frozen=True, slots=True)
class CandidateUniverseDescriptor:
    """O universo que uma query resolveu, com identidade própria."""

    policy_fingerprint: str
    policy_identity: str
    competition: str
    position: GridTimePoint
    query_key: HistoricalFeatureSnapshotKey
    candidate_identities: tuple[str, ...] = ()
    #: LINHAGEM — persistida na descrição, e FORA da identidade semântica.
    dataset_version_id: str = ""
    representation_fingerprint: str = ""
    #: A impressão da REFERÊNCIA da versão normalizada. Ela entra na identidade
    #: porque o universo é um recorte dela — e ela é cega para a avaliação
    #: (ADR-0039), então a invariante do §95 se preserva.
    reference_content_fingerprint: str = ""
    ineligible: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(set(self.candidate_identities)) != len(self.candidate_identities):
            raise ValidationError(
                f"universo de {self.query_key} com candidato repetido: ele entraria "
                "duas vezes no top-K"
            )
        if list(self.candidate_identities) != sorted(self.candidate_identities):
            raise ValidationError(
                "universo fora de ordem canônica — use o acumulador: a impressão é "
                "sobre o CONJUNTO ordenado, e a ordem de leitura não pode decidi-la"
            )

    # ------------------------------------------------------------ leitura --

    @property
    def candidate_count(self) -> int:
        """Quantos candidatos entraram no universo."""
        return len(self.candidate_identities)

    @property
    def ineligible_count(self) -> int:
        return sum(self.ineligible.values())

    def as_canonical(self) -> dict[str, object]:
        """A identidade SEMÂNTICA do universo.

        A CHAVE DA QUERY ENTRA, e é deliberado: o universo é *daquela* query.
        Duas queries no mesmo instante da mesma competição resolvem o mesmo
        CONJUNTO de candidatos — menos a exclusão da própria partida, que é
        justamente o que difere entre elas.

        AS CONTAGENS DE INELEGIBILIDADE NÃO ENTRAM. Elas dependem do perfil, e
        o universo é anterior ao perfil: o mesmo universo sob dois perfis tem
        atrições diferentes e continua sendo o mesmo universo.
        """
        return {
            "algorithm": UNIVERSE_FINGERPRINT_ALGORITHM,
            "candidates": list(self.candidate_identities),
            "competition": self.competition,
            "policy_fingerprint": self.policy_fingerprint,
            "position": self.position.as_canonical(),
            "query_key": self.query_key.text,
            "reference_content_fingerprint": self.reference_content_fingerprint,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def lineage(self) -> Mapping[str, str]:
        """De ONDE ele veio — fora da identidade, pelo motivo do ADR-0039."""
        return {
            "dataset_version_id": self.dataset_version_id,
            "representation_fingerprint": self.representation_fingerprint,
        }

    def diagnostics(self) -> Mapping[str, int]:
        return {
            "candidate_count": self.candidate_count,
            "ineligible_count": self.ineligible_count,
            **{f"ineligible_{k}": v for k, v in sorted(self.ineligible.items())},
        }

    def __str__(self) -> str:
        return (
            f"universo {self.competition}/{self.position.text}: "
            f"{self.candidate_count} candidatos [{self.fingerprint[:12]}]"
        )


def universe_summary(descriptor: CandidateUniverseDescriptor) -> Sequence[str]:
    """As linhas do resumo legível — para a CLI e para o relatório."""
    linhas = [
        f"política   {descriptor.policy_identity}",
        f"competição {descriptor.competition}",
        f"instante   {descriptor.position.text}",
        f"candidatos {descriptor.candidate_count}",
    ]
    linhas.extend(
        f"  {motivo}: {contagem}" for motivo, contagem in sorted(descriptor.ineligible.items())
    )
    linhas.append(f"impressão  {descriptor.fingerprint[:16]}")
    return linhas
