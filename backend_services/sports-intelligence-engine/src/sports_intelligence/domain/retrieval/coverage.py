"""Quanta evidência é evidência bastante — o piso, e a aritmética dele.

O PROBLEMA QUE ESTE MÓDULO RESOLVE. O PR-06.1 recusava o par inteiro quando um
único eixo faltava. Afrouxar isso sem regra produz o defeito oposto, e ele é
pior: um candidato com UM eixo em comum, idêntico à query naquele eixo, teria
discrepância observada zero — e ocuparia o primeiro lugar por não ter sido
medido em mais nada.

    ausência não pode virar similaridade barata

A REGRA TEM DUAS PARTES, e as duas são necessárias:

    piso ABSOLUTO      s ≥ 4 eixos compartilhados. Uma comparação sobre três
                       dimensões não descreve estado de jogo, por melhor que
                       seja a razão
    piso RELATIVO      5s ≥ 3m. Um par com quatro eixos de cinco está bem
                       sustentado; quatro de cem, não

O DENOMINADOR É O PERFIL, e nunca «quantas dimensões sobraram». Essa é a
decisão que impede a fraude aritmética: com denominador variável, um candidato
com duas dimensões teria `2/2 = 100 %` de cobertura e pareceria tão bem
sustentado quanto um com vinte.

    Coverage_shared = s / m       m = |perfil resolvido|, SEMPRE

OS LIMIARES SÃO RACIONAIS, E O MOTIVO NÃO É UM DEFEITO MEDIDO. A justificativa
fácil seria «`0.6` não existe em `float64`, logo a comparação erra na
fronteira» — e ela é FALSA. Foi medida: para todo par `(s, m)` com `m` até
duzentos mil, e em três formulações naturais

    s/m >= num/den        s >= (num/den)*m        (s*den)/m >= num

sobre quatro pisos diferentes, o resultado em ponto flutuante coincide com o
resultado exato em TODOS os casos. Não há divergência para consertar.

    o motivo é que, na fronteira, `s/m` e `num/den` são a MESMA razão — e o
    arredondamento para o mais próximo leva as duas ao mesmo `float64`. Fora
    da fronteira, a distância entre os dois lados é ordens de grandeza maior
    que o erro de arredondamento.

O MOTIVO VERDADEIRO É QUE A COMPARAÇÃO INTEIRA NÃO PRECISA DESSE ARGUMENTO.

    5 * s >= 3 * m        exata por construção, em `int` de precisão arbitrária

A versão em `float` é correta SOB uma propriedade do arredondamento que tem de
ser reestabelecida sempre que o piso mudar, o perfil crescer, ou alguém
reescrever a comparação de outro jeito — e o custo de reestabelecê-la é
exatamente a medição acima. A versão inteira dispensa a obrigação.

    ESTE É O MESMO PADRÃO DO `fsum` NO PR-06.1: a razão fácil era falsa, e a
    razão verdadeira é de contrato — não depender de um detalhe que hoje
    funciona.

AS FRAÇÕES CONTINUAM EXISTINDO — elas vão para o relatório, e são derivadas.
O que elas não fazem é decidir.

O PISO NÃO SE AJUSTA SOZINHO. Se o perfil de uma competição tiver menos eixos
que o mínimo absoluto, a resposta é recusar a competição inteira com tipo
próprio — e não baixar o mínimo até ela caber. Um piso que cede à pressão do
dado não é um piso.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, final

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import DataQualityError, ValidationError

COVERAGE_POLICY_FINGERPRINT_ALGORITHM: Final[str] = "availability-coverage-policy-sha256-v1"

#: A política de cobertura da V1. O nome diz o que ela é: um piso MÍNIMO DE
#: EVIDÊNCIA, e não uma pontuação de qualidade.
MINIMUM_EVIDENCE_COVERAGE_V1: Final[str] = "MINIMUM_EVIDENCE_COVERAGE_V1"

#: Os motivos tipados, para quem trata o erro sem ler texto.
PROFILE_INSUFFICIENT_EVIDENCE_AXES: Final[str] = "PROFILE_INSUFFICIENT_EVIDENCE_AXES"
QUERY_INSUFFICIENT_COVERAGE: Final[str] = "QUERY_INSUFFICIENT_COVERAGE"


def ceil_div(numerator: int, denominator: int) -> int:
    """`ceil(numerator / denominator)` em aritmética INTEIRA.

    ELA NÃO CONVERTE PARA `float` EM MOMENTO NENHUM. `math.ceil(a / b)`
    arredonda a divisão ANTES do teto, e para numeradores grandes os dois
    resultados divergem: `ceil(10**17 / 3)` em ponto flutuante dá
    `33333333333333332`, e o valor exato é `33333333333333334` — erra por DOIS.

    NA FAIXA DE UM PERFIL DE FUTEBOL AS DUAS FORMAS CONCORDAM, e afirmar o
    contrário seria falso. O motivo de usar esta aqui não é que o float falhe
    na escala operacional: é que a policy representa uma RAZÃO MATEMÁTICA
    EXATA, e a aritmética inteira a torna exata por construção — sem depender
    de nenhuma hipótese sobre qual é a faixa segura de IEEE-754.

    A forma `-((-a) // b)` usa a divisão que ARREDONDA PARA BAIXO do Python e
    a espelha duas vezes; ela é exata para todo `int`, que é de precisão
    arbitrária.
    """
    if denominator < 1:
        raise ValidationError(f"divisão inteira com denominador {denominator}")
    return -((-numerator) // denominator)


@final
@dataclass(frozen=True, slots=True)
class RationalFloor:
    """Um piso `numerador/denominador`, comparado em aritmética INTEIRA.

    ELE EXISTE PARA NÃO PRECISAR DE PROVA. Ver o cabeçalho do módulo: a
    comparação em ponto flutuante dá o mesmo resultado em tudo que foi medido,
    e é correta sob um argumento sobre arredondamento que teria de ser refeito
    a cada mudança de piso. A comparação inteira é exata por construção.
    """

    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        if self.denominator < 1:
            raise ValidationError(f"piso com denominador {self.denominator}")
        if self.numerator < 0:
            raise ValidationError(f"piso com numerador {self.numerator}")
        if self.numerator > self.denominator:
            raise ValidationError(
                f"piso de {self.numerator}/{self.denominator}: acima de 1, nenhuma "
                "cobertura o alcançaria e toda comparação seria recusada"
            )

    def minimum_part(self, whole: int) -> int:
        """O MENOR `part` inteiro que satisfaz o piso — `ceil(num*whole/den)`.

        ELA EXISTE PARA QUE O PISO SEJA UM NÚMERO, e não só uma decisão. «Este
        candidato foi recusado» é diferente de «este candidato foi recusado
        porque precisava de onze células e tinha dez», e a segunda frase só é
        dizível quando o piso pode ser calculado.

        `ceil` INTEIRO, e nunca `math.ceil(0.6 * n)`: a divisão em ponto
        flutuante introduziria um arredondamento antes do teto, e o piso de um
        perfil grande passaria a depender dele.

            ceil_div(a, b) = -((-a) // b)        exato em `int`

        E ELA É EQUIVALENTE A `admits`, por construção: para `part` inteiro,
        `den·part >= num·whole  <=>  part >= ceil(num·whole/den)`. Há teste de
        propriedade sobre a equivalência, porque duas formas da mesma regra é
        como uma delas passa a decidir sozinha.
        """
        if whole < 1:
            return 0
        return ceil_div(self.numerator * whole, self.denominator)

    def admits(self, *, part: int, whole: int) -> bool:
        """`part / whole >= numerador / denominador`, sem tocar em `float`.

        A MULTIPLICAÇÃO CRUZADA É EXATA em `int` de Python, que é de precisão
        arbitrária — e é exata sem depender de nada sobre o arredondamento de
        `part / whole`. Ver o cabeçalho: a versão em `float` acerta em tudo que
        foi medido, e acerta por um motivo que precisa ser reconferido.
        """
        if whole < 1:
            return False
        return self.denominator * part >= self.numerator * whole

    @property
    def as_float(self) -> float:
        """O piso como número, PARA IMPRIMIR. Ele nunca decide nada."""
        return self.numerator / self.denominator

    @property
    def text(self) -> str:
        return f"{self.numerator}/{self.denominator}"

    def as_canonical(self) -> dict[str, object]:
        return {"denominator": self.denominator, "numerator": self.numerator}

    def __str__(self) -> str:
        return self.text


@final
@dataclass(frozen=True, slots=True)
class AvailabilityCoveragePolicy:
    """O contrato do piso de evidência. Imutável e impresso.

    ELA É SEPARADA DO PERFIL, e a separação tem consequência: o mesmo perfil
    resolvido sob dois pisos produz dois resultados diferentes, e a impressão
    da distância cobre os dois — logo os dois números nunca se confundem.
    """

    name: str = MINIMUM_EVIDENCE_COVERAGE_V1
    version: int = 1
    #: O tamanho mínimo do PERFIL. Abaixo dele a competição inteira é recusada:
    #: um perfil de três eixos não descreve estado de jogo, e afrouxar o piso
    #: para acomodá-lo faria a recuperação responder com o que sobrou.
    minimum_profile_axes: int = 4
    #: Quantos eixos a QUERY precisa ter, em absoluto.
    minimum_query_available_axes: int = 4
    #: Quantos eixos o PAR precisa compartilhar, em absoluto.
    minimum_shared_axes: int = 4
    #: `|Q| / m >= 3/5`.
    query_coverage_floor: RationalFloor = RationalFloor(3, 5)
    #: `|S| / m >= 3/5`.
    shared_coverage_floor: RationalFloor = RationalFloor(3, 5)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("política de cobertura sem nome")
        if self.version < 1:
            raise ValidationError(f"versão de política inválida: {self.version}")
        for rotulo, minimo in (
            ("minimum_profile_axes", self.minimum_profile_axes),
            ("minimum_query_available_axes", self.minimum_query_available_axes),
            ("minimum_shared_axes", self.minimum_shared_axes),
        ):
            if minimo < 1:
                raise ValidationError(
                    f"{rotulo} = {minimo}: um piso de zero eixos admitiria um par que "
                    "não compartilha dimensão nenhuma, e a distância dele seria "
                    "penalidade pura com discrepância observada vazia"
                )
        if self.minimum_shared_axes > self.minimum_profile_axes:
            raise ValidationError(
                f"piso de {self.minimum_shared_axes} eixos compartilhados sobre um "
                f"perfil mínimo de {self.minimum_profile_axes}: nenhum par no perfil "
                "mínimo seria comparável, e a política recusaria tudo em silêncio"
            )

    # ------------------------------------------------------------ leitura --

    @property
    def identity(self) -> str:
        return f"{self.name}@{self.version}"

    # -------------------------------------------------------- as decisões --

    def admits_profile(self, axis_count: int) -> bool:
        return axis_count >= self.minimum_profile_axes

    def admits_query(self, *, available: int, profile_axes: int) -> bool:
        """A query tem evidência bastante para PERGUNTAR."""
        return available >= self.minimum_query_available_axes and self.query_coverage_floor.admits(
            part=available, whole=profile_axes
        )

    def admits_pair(self, *, shared: int, profile_axes: int) -> bool:
        """O par tem evidência bastante para ser COMPARADO."""
        return shared >= self.minimum_shared_axes and self.shared_coverage_floor.admits(
            part=shared, whole=profile_axes
        )

    def assert_profile_admissible(self, *, axis_count: int, competition: str) -> None:
        if self.admits_profile(axis_count):
            return
        raise ProfileInsufficientEvidenceError(
            competition=competition,
            axis_count=axis_count,
            minimum=self.minimum_profile_axes,
            policy_identity=self.identity,
        )

    # -------------------------------------------------------------- forma --

    def as_canonical(self) -> dict[str, object]:
        return {
            "algorithm": COVERAGE_POLICY_FINGERPRINT_ALGORITHM,
            "minimum_profile_axes": self.minimum_profile_axes,
            "minimum_query_available_axes": self.minimum_query_available_axes,
            "minimum_shared_axes": self.minimum_shared_axes,
            "name": self.name,
            "query_coverage_floor": self.query_coverage_floor.as_canonical(),
            "shared_coverage_floor": self.shared_coverage_floor.as_canonical(),
            "version": self.version,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def __str__(self) -> str:
        return (
            f"{self.identity} · >={self.minimum_shared_axes} eixos e "
            f">={self.shared_coverage_floor.text} [{self.fingerprint[:12]}]"
        )


#: A política de produção da V1.
DEFAULT_COVERAGE_POLICY: Final[AvailabilityCoveragePolicy] = AvailabilityCoveragePolicy()


@final
@dataclass(frozen=True, slots=True)
class CoverageAssessment:
    """Quanta evidência ESTE par tem — em contagens, e depois em frações.

    AS CONTAGENS SÃO A AUTORIDADE, e as frações são derivadas. A ordem importa
    porque é ela que mantém a decisão em aritmética exata: os `float` deste
    objeto existem para o relatório, e nenhuma comparação de elegibilidade os
    consulta.
    """

    profile_axis_count: int
    query_available_count: int
    candidate_available_count: int
    shared_count: int
    policy: AvailabilityCoveragePolicy = DEFAULT_COVERAGE_POLICY

    def __post_init__(self) -> None:
        if self.profile_axis_count < 1:
            raise ValidationError("cobertura sobre um perfil sem eixos")
        for rotulo, contagem in (
            ("query_available_count", self.query_available_count),
            ("candidate_available_count", self.candidate_available_count),
            ("shared_count", self.shared_count),
        ):
            if contagem < 0:
                raise ValidationError(f"{rotulo} negativo: {contagem}")
            if contagem > self.profile_axis_count:
                raise ValidationError(
                    f"{rotulo} = {contagem} sobre um perfil de "
                    f"{self.profile_axis_count} eixos: um subconjunto maior que o "
                    "conjunto significa que a máscara é de outro perfil"
                )
        if self.shared_count > min(self.query_available_count, self.candidate_available_count):
            raise ValidationError(
                f"{self.shared_count} eixos compartilhados entre uma query com "
                f"{self.query_available_count} e um candidato com "
                f"{self.candidate_available_count}: a interseção não pode ser maior "
                "que o menor dos dois lados"
            )

    # ---------------------------------------------------------- contagens --

    @property
    def unshared_count(self) -> int:
        """`u = m - s`. Quantos eixos do perfil o par NÃO compartilha.

        ELE É CONTADO SOBRE O PERFIL, e não sobre a união das disponibilidades:
        um eixo que nenhum dos dois tem continua sendo um eixo do perfil que a
        comparação não pôde usar, e é exatamente isso que a penalidade cobra.
        """
        return self.profile_axis_count - self.shared_count

    # ------------------------------------------------------------ frações --

    @property
    def query_coverage(self) -> float:
        """`|Q| / m`. DIAGNÓSTICO — a decisão é `policy.admits_query`."""
        return self.query_available_count / self.profile_axis_count

    @property
    def candidate_coverage(self) -> float:
        return self.candidate_available_count / self.profile_axis_count

    @property
    def shared_profile_coverage(self) -> float:
        """`|S| / m`. A cobertura AUTORIDADE, com denominador fixo."""
        return self.shared_count / self.profile_axis_count

    @property
    def shared_query_coverage(self) -> float | None:
        """`|S| / |Q|`. Quanto do que a query TEM o candidato acompanhou.

        ELA É EVIDÊNCIA E NÃO SUBSTITUI A OUTRA. Um par com `|Q| = 4` e
        `|S| = 4` tem 100 % aqui e pode estar muito abaixo do piso do perfil —
        e é o piso do perfil que decide.

        `None` QUANDO A QUERY NÃO TEM NADA, e não zero: zero seria um valor
        legítimo de uma razão que não existe.
        """
        if self.query_available_count < 1:
            return None
        return self.shared_count / self.query_available_count

    # --------------------------------------------------------- os limiares --

    @property
    def meets_query_floor(self) -> bool:
        return self.policy.admits_query(
            available=self.query_available_count, profile_axes=self.profile_axis_count
        )

    @property
    def meets_shared_floor(self) -> bool:
        return self.policy.admits_pair(
            shared=self.shared_count, profile_axes=self.profile_axis_count
        )

    @property
    def is_complete_case(self) -> bool:
        """Se o par compartilha o perfil inteiro — `s = m`."""
        return self.shared_count == self.profile_axis_count

    @property
    def is_at_shared_floor(self) -> bool:
        """Se o par está EXATAMENTE no piso, e não acima dele.

        ELE EXISTE PARA SER CONTADO (§156). Um top-K colado no mínimo é sinal
        de que a política está operando perto demais da ausência — e esse sinal
        não aparece numa média de cobertura.

        «NO PISO» SÃO DOIS PISOS, e qualquer um deles conta: o par que tem
        exatamente `minimum_shared_axes` eixos, e o par cuja razão bate a
        igualdade `5s = 3m`. Os dois estão a um eixo de serem recusados.
        """
        piso = self.policy.shared_coverage_floor
        return self.meets_shared_floor and (
            self.shared_count == self.policy.minimum_shared_axes
            or piso.denominator * self.shared_count == piso.numerator * self.profile_axis_count
        )

    # -------------------------------------------------------------- forma --

    def as_canonical(self) -> dict[str, object]:
        """A forma que entra na impressão da evidência — SÓ CONTAGENS.

        AS FRAÇÕES FICAM DE FORA. Elas são derivadas exatas das contagens, e
        gravá-las na impressão colocaria três `float` no lugar de três `int`
        sem acrescentar informação nenhuma.
        """
        return {
            "candidate_available_count": self.candidate_available_count,
            "profile_axis_count": self.profile_axis_count,
            "query_available_count": self.query_available_count,
            "shared_count": self.shared_count,
        }

    def diagnostics(self) -> Mapping[str, object]:
        return {
            "candidate_available_count": self.candidate_available_count,
            "candidate_coverage": self.candidate_coverage,
            "meets_query_floor": self.meets_query_floor,
            "meets_shared_floor": self.meets_shared_floor,
            "profile_axis_count": self.profile_axis_count,
            "query_available_count": self.query_available_count,
            "query_coverage": self.query_coverage,
            "shared_count": self.shared_count,
            "shared_profile_coverage": self.shared_profile_coverage,
            "shared_query_coverage": self.shared_query_coverage,
            "unshared_count": self.unshared_count,
        }

    def __str__(self) -> str:
        return (
            f"s={self.shared_count}/{self.profile_axis_count} ({self.shared_profile_coverage:.1%})"
        )


@final
class ProfileInsufficientEvidenceError(DataQualityError):
    """O perfil resolvido da competição é pequeno demais para comparar nada.

    ELE NÃO É «QUERY NÃO COMPARÁVEL», e a diferença é onde está a causa. A
    query pode estar completa; o que falta é ESCALA na competição inteira — o
    ajuste não encontrou dispersão em eixos bastantes, e nenhuma query daquela
    liga será comparável enquanto isso não mudar.

    A SAÍDA NÃO É BAIXAR O MÍNIMO. Um piso que cede à pressão do dado deixa de
    ser piso: a competição passaria a devolver top-K sobre três dimensões, e o
    número sairia com a mesma cara de um sobre trinta.
    """

    def __init__(
        self, *, competition: str, axis_count: int, minimum: int, policy_identity: str
    ) -> None:
        super().__init__(
            f"{PROFILE_INSUFFICIENT_EVIDENCE_AXES}: o perfil resolvido de "
            f"{competition} tem {axis_count} eixo(s), e a política "
            f"{policy_identity} exige {minimum}. Reduzir o mínimo para acomodar "
            "esta competição faria a recuperação responder com o que sobrou",
            context={
                "axis_count": axis_count,
                "competition": competition,
                "minimum_profile_axes": minimum,
                "policy": policy_identity,
                "reason": PROFILE_INSUFFICIENT_EVIDENCE_AXES,
            },
        )
        self.competition = competition
        self.axis_count = axis_count
        self.minimum = minimum

    @property
    def reason(self) -> str:
        return PROFILE_INSUFFICIENT_EVIDENCE_AXES


@final
class QueryInsufficientCoverageError(DataQualityError):
    """A query não alcança o piso de evidência do perfil.

    NENHUMA DISTÂNCIA É CALCULADA, e o universo pode ser descrito assim mesmo:
    «quantos candidatos existiriam» continua sendo uma pergunta respondível, e
    respondê-la é o que permite distinguir «não há candidato» de «a query não
    tinha o que perguntar».

    O PERFIL NÃO É REDUZIDO À QUERY. Ver `profile.py`: cada query mediria uma
    grandeza diferente, e dois resultados deixariam de ser comparáveis entre si
    sem que nada no objeto dissesse isso.
    """

    def __init__(
        self,
        *,
        key: HistoricalFeatureSnapshotKey,
        profile_fingerprint: str,
        available_axes: int,
        axis_count: int,
        missing_axes: Sequence[str],
        policy: AvailabilityCoveragePolicy,
    ) -> None:
        faltando = tuple(missing_axes)
        amostra = ", ".join(faltando[:3])
        reticencias = "…" if len(faltando) > 3 else ""
        super().__init__(
            f"{QUERY_INSUFFICIENT_COVERAGE}: a query {key.text} tem {available_axes} "
            f"dos {axis_count} eixos do perfil, e a política {policy.identity} exige "
            f"pelo menos {policy.minimum_query_available_axes} eixos e "
            f"{policy.query_coverage_floor.text} do perfil. Faltam: "
            f"{amostra}{reticencias}",
            context={
                "available_axes": available_axes,
                "axis_count": axis_count,
                "key": key.text,
                "minimum_axes": policy.minimum_query_available_axes,
                "minimum_ratio": policy.query_coverage_floor.text,
                "missing_axes": list(faltando),
                "policy": policy.identity,
                "profile_fingerprint": profile_fingerprint,
                "reason": QUERY_INSUFFICIENT_COVERAGE,
            },
        )
        self.key = key
        self.available_axes = available_axes
        self.axis_count = axis_count
        self.missing_axes = faltando
        self.policy = policy

    @property
    def reason(self) -> str:
        return QUERY_INSUFFICIENT_COVERAGE


def coverage_summary(assessment: CoverageAssessment) -> Sequence[str]:
    """As linhas do resumo legível — para a CLI e para o relatório."""
    relativa = assessment.shared_query_coverage
    return [
        f"perfil          {assessment.profile_axis_count} eixos",
        f"query           {assessment.query_available_count} ({assessment.query_coverage:.1%})",
        f"candidato       {assessment.candidate_available_count} "
        f"({assessment.candidate_coverage:.1%})",
        f"compartilhados  {assessment.shared_count} "
        f"({assessment.shared_profile_coverage:.1%} do perfil)",
        "  do que a query tem  " + ("-" if relativa is None else format(relativa, ".1%")),
        f"ausentes        {assessment.unshared_count}",
        f"piso            {assessment.policy.shared_coverage_floor.text} e "
        f"{assessment.policy.minimum_shared_axes} eixos",
    ]
