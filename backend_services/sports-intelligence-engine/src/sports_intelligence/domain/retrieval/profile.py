"""Quais eixos entram na distância — e por que só os robustos ajustados.

O PERFIL BASE É UMA REGRA; O PERFIL RESOLVIDO É O QUE ELA PRODUZ PARA UMA
COMPETIÇÃO. A separação não é cerimônia: a regra é a mesma em toda liga, e o
conjunto de eixos que sobra depende do que o ajuste ENCONTROU naquela liga.

    RetrievalFeatureProfile     «eixos ROBUST cujo artefato está FITTED»
    ResolvedRetrievalProfile    para a Premier League, estes 14 eixos

POR QUE SÓ OS EIXOS `ROBUST`. Eles já estão em escala estatística comparável
por competição — `(x - mediana) / IQR` sobre a referência daquela liga. Os
`PASS_THROUGH` não passaram por escala nenhuma, e somá-los na mesma distância
seria somar:

    minute                 0 a 90        uma coordenada de relógio
    corners_home_5m        0 a 3         uma contagem esparsa
    market_1x2_home_support 0 a 12       quantas casas publicaram
    xg_home_5m normalizado -2 a +2       um desvio robusto

O eixo de maior magnitude domina, e a distância passa a medir principalmente o
relógio. Isso não é uma escolha de similaridade — é um acidente de unidade.

POR QUE SÓ OS `FITTED`. Um artefato `DEGENERATE_SCALE` diz que aquela liga não
tem dispersão naquele eixo; um `INSUFFICIENT_SAMPLE` diz que ela não juntou
observações bastantes. Nos dois casos NÃO EXISTE ESCALA, e a célula
correspondente sai vazia no dataset normalizado (ADR-0035). Um eixo assim no
perfil produziria uma coluna que nunca tem valor — e, sob a regra de caso
completo, tornaria a competição inteira incomparável.

E A CAUSALIDADE SE PRESERVA DE GRAÇA. O estado do artefato é decidido
exclusivamente pela REFERÊNCIA (ADR-0039): mexer na AVALIAÇÃO não muda quem
está `FITTED`, logo não muda o perfil resolvido. A impressão do perfil é, por
construção, cega para a avaliação — e há teste de propriedade sobre isso.

O PERFIL CASA POR IMPRESSÃO DE FEATURE, e não por nome de coluna. Duas versões
da mesma feature têm a mesma chave e escalas diferentes; comparar `n_xg_home_5m`
de um dataset com o de outro só porque a coluna se chama igual é o defeito que
a impressão existe para pegar.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.features.fitting.artifact import FitStatus
from sports_intelligence.domain.features.normalized.artifacts import (
    CompetitionNormalizerArtifactBundle,
)
from sports_intelligence.domain.features.normalized.plan import (
    NormalizationPlan,
    TransformStrategy,
)
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import CompetitionId

PROFILE_FINGERPRINT_ALGORITHM: Final[str] = "retrieval-profile-sha256-v1"

RESOLVED_PROFILE_FINGERPRINT_ALGORITHM: Final[str] = "resolved-retrieval-profile-sha256-v1"

#: O perfil diagnóstico da V1. O nome carrega as três decisões dele —
#: robustos, caso completo, exato — para que ninguém o cite como «o perfil».
ROBUST_COMPLETE_CASE_EXACT_BASELINE_V1: Final[str] = "ROBUST_COMPLETE_CASE_EXACT_BASELINE_V1"

#: O perfil do PR-06.2. MESMOS EIXOS, outra semântica de ausência — e é a
#: igualdade dos eixos que torna a comparação entre os dois uma medição do
#: EFEITO DA POLÍTICA, e não de duas coisas diferentes ao mesmo tempo.
ROBUST_AVAILABILITY_AWARE_EXACT_V1: Final[str] = "ROBUST_AVAILABILITY_AWARE_EXACT_V1"


@final
class AxisSelection(StrEnum):
    """Como o perfil escolhe os eixos. Catálogo FECHADO."""

    #: Eixos `ROBUST_MEDIAN_IQR_V1` cujo artefato da competição está `FITTED`.
    ROBUST_FITTED = "ROBUST_FITTED"


@final
class MissingPolicy(StrEnum):
    """O que a distância faz com um eixo ausente. Catálogo FECHADO.

    DOIS MEMBROS, E NENHUM DELES IMPUTA. `COMPLETE_CASE` é o mais restritivo
    que existe: ou o par tem os dois valores em TODOS os eixos, ou não há
    distância. `AVAILABILITY_AWARE` afrouxa a ELEGIBILIDADE e cobra a ausência
    — ela não a preenche.

        COMPLETE_CASE      s = m, ou nada
        AVAILABILITY_AWARE s ≥ piso, e cada eixo ausente custa 1/m

    O QUE CONTINUA FORA DO CATÁLOGO é o que importa: imputação por zero, por
    média, distância sobre a interseção com denominador variável, e limiar de
    cobertura implícito. Nenhum deles tem nome aqui, e por isso nenhum deles
    pode ser configurado por engano.
    """

    COMPLETE_CASE = "COMPLETE_CASE"
    #: Caso compartilhado com piso de cobertura e penalidade por ausência
    #: (PR-06.2). Ver `coverage.py` e `availability_distance.py`.
    AVAILABILITY_AWARE = "AVAILABILITY_AWARE"


@final
class WeightPolicy(StrEnum):
    """Como os eixos são ponderados. Catálogo FECHADO."""

    EQUAL = "EQUAL"


@final
@dataclass(frozen=True, slots=True)
class RetrievalFeatureProfile:
    """A REGRA de seleção de eixos. Ela não conhece competição nenhuma."""

    name: str = ROBUST_COMPLETE_CASE_EXACT_BASELINE_V1
    version: int = 1
    axis_selection: AxisSelection = AxisSelection.ROBUST_FITTED
    missing_policy: MissingPolicy = MissingPolicy.COMPLETE_CASE
    weight_policy: WeightPolicy = WeightPolicy.EQUAL

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("perfil de recuperação sem nome")
        if self.version < 1:
            raise ValidationError(f"versão de perfil inválida: {self.version}")

    @property
    def identity(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def is_complete_case(self) -> bool:
        """Se a elegibilidade exige TODOS os eixos do perfil."""
        return self.missing_policy is MissingPolicy.COMPLETE_CASE

    @property
    def is_availability_aware(self) -> bool:
        """Se a elegibilidade é por cobertura compartilhada (PR-06.2)."""
        return self.missing_policy is MissingPolicy.AVAILABILITY_AWARE

    @property
    def is_diagnostic(self) -> bool:
        """Se este perfil é um BASELINE, e não a similaridade final.

        ELE EXISTE PARA SER LIDO EM RELATÓRIO. «Diagnóstico» é uma afirmação
        sobre o que o número significa, e deixá-la só na documentação faria
        alguém citar um top-K deste perfil como resposta de produto.

        OS DOIS PERFIS DA V1 SÃO DIAGNÓSTICOS, e a constante é honesta: o
        `COMPLETE_CASE` porque recusa a ausência inteira, o
        `AVAILABILITY_AWARE` porque tem pesos iguais e penalidade uniforme — a
        ponderação é do PR-06.5 e a confiança é do PR-06.7. O dia em que
        existir um perfil de produto, este membro entra no catálogo e esta
        propriedade passa a distinguir de verdade.
        """
        return self.missing_policy in (
            MissingPolicy.COMPLETE_CASE,
            MissingPolicy.AVAILABILITY_AWARE,
        )

    def as_canonical(self) -> dict[str, object]:
        return {
            "algorithm": PROFILE_FINGERPRINT_ALGORITHM,
            "axis_selection": self.axis_selection.value,
            "missing_policy": self.missing_policy.value,
            "name": self.name,
            "version": self.version,
            "weight_policy": self.weight_policy.value,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    # ------------------------------------------------------------ resolução --

    def resolve(
        self,
        *,
        plan: NormalizationPlan,
        bundle: CompetitionNormalizerArtifactBundle,
    ) -> ResolvedRetrievalProfile:
        """Os eixos que sobram para ESTA competição.

        A ORDEM É A DO PLANO, e não a do pacote nem a de um `sorted()` local. O
        plano descreve eixos ordenados, e a soma da distância percorre essa
        ordem — duas resoluções que ordenassem diferente produziriam somas de
        ponto flutuante diferentes sobre os mesmos números.

        A IMPRESSÃO DA FEATURE VEM DO PLANO E É CONFERIDA CONTRA O ARTEFATO. Um
        artefato ajustado para outra versão da mesma feature tem a mesma chave
        e outra escala; casá-los por nome produziria uma distância entre
        grandezas diferentes.
        """
        if bundle.plan_fingerprint != plan.fingerprint:
            raise ValidationError(
                f"o pacote de {bundle.competition} foi ajustado sob outro plano: "
                "resolver o perfil com ele escolheria eixos sob uma classificação "
                "que ninguém tomou para este dataset",
                context={
                    "plan": plan.fingerprint,
                    "bundle_plan": bundle.plan_fingerprint,
                },
            )
        por_chave = {a.feature_key: a for a in bundle.artifacts}
        chaves: list[str] = []
        impressoes: list[str] = []
        descartados: dict[str, int] = {estado.value: 0 for estado in FitStatus}
        sem_artefato = 0

        for transformacao in plan.transforms:
            if transformacao.strategy is not TransformStrategy.ROBUST_MEDIAN_IQR:
                continue
            artefato = por_chave.get(transformacao.feature_key)
            if artefato is None:
                # A COMPETIÇÃO NÃO TEM ARTEFATO PARA O EIXO. Ela aparece só na
                # avaliação, ou o pacote está incompleto — as duas coisas o
                # tiram do perfil, e a contagem separada diz qual foi.
                sem_artefato += 1
                continue
            if artefato.feature_fingerprint != transformacao.feature_fingerprint:
                raise ValidationError(
                    f"o artefato de {transformacao.feature_key} em "
                    f"{bundle.competition} foi ajustado para outra versão da feature: "
                    "a chave é a mesma e a escala não, e casá-los por nome produziria "
                    "uma distância entre grandezas diferentes",
                    context={
                        "feature": transformacao.feature_key,
                        "plan": transformacao.feature_fingerprint,
                        "artifact": artefato.feature_fingerprint,
                    },
                )
            if artefato.status is not FitStatus.FITTED:
                descartados[artefato.status.value] += 1
                continue
            chaves.append(transformacao.feature_key)
            impressoes.append(transformacao.feature_fingerprint)

        return ResolvedRetrievalProfile(
            base=self,
            competition=bundle.competition,
            competition_id=bundle.competition_id,
            competition_bundle_fingerprint=bundle.fingerprint,
            plan_fingerprint=plan.fingerprint,
            feature_keys=tuple(chaves),
            feature_fingerprints=tuple(impressoes),
            excluded_by_status={
                estado: contagem for estado, contagem in sorted(descartados.items()) if contagem
            },
            excluded_without_artifact=sem_artefato,
        )

    def __str__(self) -> str:
        return f"{self.identity} [{self.fingerprint[:12]}]"


@final
@dataclass(frozen=True, slots=True)
class ResolvedRetrievalProfile:
    """Os eixos de UMA competição, em ordem, com identidade própria.

    A IDENTIDADE COBRE A IMPRESSÃO DO PACOTE, e é isso que torna o perfil
    verificável: dois perfis resolvidos com a mesma impressão foram resolvidos
    sobre os MESMOS artefatos, e não apenas sobre a mesma lista de nomes.
    """

    base: RetrievalFeatureProfile
    competition: str
    competition_id: CompetitionId
    competition_bundle_fingerprint: str
    plan_fingerprint: str
    feature_keys: tuple[str, ...] = ()
    feature_fingerprints: tuple[str, ...] = ()
    #: Quantos eixos `ROBUST` saíram por cada estado de ajuste. Diagnóstico, e
    #: não identidade: ele explica o tamanho do perfil sem entrar na impressão.
    excluded_by_status: Mapping[str, int] = field(default_factory=dict)
    excluded_without_artifact: int = 0

    def __post_init__(self) -> None:
        if len(self.feature_keys) != len(self.feature_fingerprints):
            raise ValidationError(
                f"perfil de {self.competition} com {len(self.feature_keys)} chaves e "
                f"{len(self.feature_fingerprints)} impressões: elas são pares, e um "
                "desalinhamento faria a distância usar a escala de outro eixo"
            )
        if len(set(self.feature_keys)) != len(self.feature_keys):
            repetidos = sorted({k for k in self.feature_keys if self.feature_keys.count(k) > 1})
            raise ValidationError(
                f"perfil de {self.competition} com eixo repetido: {repetidos[:3]}. "
                "Ele entraria duas vezes na soma e pesaria o dobro"
            )

    # ------------------------------------------------------------ leitura --

    @property
    def axis_count(self) -> int:
        return len(self.feature_keys)

    @property
    def is_empty(self) -> bool:
        """Se nenhum eixo sobrou.

        ISSO NÃO É ERRO AQUI. É uma competição em que o ajuste não encontrou
        escala em eixo nenhum — e quem decide o que fazer com isso é a query,
        que tem o contexto para dizer «não comparável» com o motivo certo.
        """
        return not self.feature_keys

    def as_canonical(self) -> dict[str, object]:
        """A identidade — eixos em ordem, com impressão, e o pacote que os deu.

        AS CONTAGENS DE DESCARTE FICAM DE FORA. Elas são diagnóstico: duas
        resoluções que chegassem aos mesmos eixos por caminhos diferentes são o
        mesmo perfil, e incluí-las faria a impressão dizer «diferente».
        """
        return {
            "algorithm": RESOLVED_PROFILE_FINGERPRINT_ALGORITHM,
            "axes": [
                {"feature_fingerprint": impressao, "feature_key": chave}
                for chave, impressao in zip(
                    self.feature_keys, self.feature_fingerprints, strict=True
                )
            ],
            "base": self.base.as_canonical(),
            "competition": self.competition,
            "competition_bundle_fingerprint": self.competition_bundle_fingerprint,
            "competition_id": str(self.competition_id),
            "plan_fingerprint": self.plan_fingerprint,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def diagnostics(self) -> Mapping[str, int]:
        """Por que o perfil tem o tamanho que tem."""
        return {
            "axis_count": self.axis_count,
            "excluded_without_artifact": self.excluded_without_artifact,
            **{f"excluded_{k}": v for k, v in sorted(self.excluded_by_status.items())},
        }

    def assert_comparable_with(self, other: ResolvedRetrievalProfile) -> None:
        """Dois perfis resolvidos descrevem a MESMA distância — ou nenhuma."""
        if self.fingerprint == other.fingerprint:
            return
        raise ValidationError(
            f"perfis resolvidos diferentes para {self.competition} e "
            f"{other.competition}: uma distância calculada sob eixos diferentes não "
            "se compara com outra, e as duas parecem números da mesma grandeza",
            context={"left": self.fingerprint, "right": other.fingerprint},
        )

    def __str__(self) -> str:
        return (
            f"{self.base.name}/{self.competition}: {self.axis_count} eixos "
            f"[{self.fingerprint[:12]}]"
        )


#: O perfil de produção da V1 — diagnóstico, e nomeado como tal.
DEFAULT_RETRIEVAL_PROFILE: Final[RetrievalFeatureProfile] = RetrievalFeatureProfile()

#: O perfil ciente de disponibilidade do PR-06.2.
#:
#: A `axis_selection` É A MESMA, e isso não é economia de digitação: é o que
#: garante `ResolvedAxes(CompleteCase) == ResolvedAxes(AvailabilityAware)` para
#: qualquer competição — e é essa igualdade que permite atribuir a diferença
#: entre os dois resultados à política de ausência, e a nada mais.
AVAILABILITY_AWARE_RETRIEVAL_PROFILE: Final[RetrievalFeatureProfile] = RetrievalFeatureProfile(
    name=ROBUST_AVAILABILITY_AWARE_EXACT_V1,
    axis_selection=AxisSelection.ROBUST_FITTED,
    missing_policy=MissingPolicy.AVAILABILITY_AWARE,
    weight_policy=WeightPolicy.EQUAL,
)


def profile_summary(profile: ResolvedRetrievalProfile) -> Sequence[str]:
    """As linhas do resumo legível — para a CLI e para o relatório."""
    linhas = [
        f"{profile.base.identity} / {profile.competition}",
        f"eixos: {profile.axis_count}",
    ]
    linhas.extend(f"  {chave}" for chave in profile.feature_keys)
    linhas.extend(
        f"{rotulo}: {contagem}"
        for rotulo, contagem in sorted(profile.diagnostics().items())
        if rotulo != "axis_count"
    )
    return linhas
