"""Quanta evidência TEMPORAL é evidência bastante.

O PR-06.2 decidiu isso para eixos; aqui a unidade é outra, e a diferença é o
módulo inteiro:

    PR-06.2   a célula é um EIXO             m unidades
    PR-06.3   a célula é (HORIZONTE, EIXO)   n = |H| · m unidades

E ISSO CRIA UM PISO QUE O PR-06.2 NÃO PRECISAVA TER: o de HORIZONTES DISTINTOS.

    um candidato com o horizonte de 1 minuto perfeito e os outros dois vazios
    teria, num perfil de vinte eixos, vinte células de sessenta — um terço — e
    zero informação sobre tendência. «Movimento parecido» com base num minuto
    só é uma afirmação que a representação não sustenta.

    por isso: pelo menos DOIS horizontes EVIDENCIAIS, dos dois lados.

UM HORIZONTE É EVIDENCIAL quando ele sozinho passaria no piso do PR-06.2: pelo
menos quatro eixos, e pelo menos três quintos deles. Um horizonte com um eixo
de vinte existe estruturalmente e não descreve movimento nenhum — contá-lo como
«um horizonte» transformaria o piso de dois horizontes numa formalidade.

O DENOMINADOR É `n`, E ELE NÃO ENCOLHE (§75, §76). Se o horizonte de cinco
minutos estiver fora do período, as `m` células dele continuam no divisor:

    remover o horizonte     uma trajetória com UM minuto de história pareceria
                            tão evidenciada quanto uma com cinco
    manter no denominador   ela tem no máximo `2m/3m = 2/3` de cobertura, e o
                            piso decide se isso basta

**OITO CÉLULAS É UM MÍNIMO ABSOLUTO, E NÃO O PISO.** Esta é a distinção que o
módulo existe para não deixar passar. O piso EFETIVO de um par é o MAIOR entre
o mínimo absoluto e o piso racional sobre o espaço inteiro:

    E_s = max( 8, ceil(3n/5) )        n = |H| . m

    m =  4   n = 12   absoluto 8   racional  8   ->  efetivo  8   (empate)
    m =  6   n = 18   absoluto 8   racional 11   ->  efetivo 11
    m = 15   n = 45   absoluto 8   racional 27   ->  efetivo 27

    DOIS HORIZONTES MINIMAMENTE EVIDENCIAIS DÃO `4 + 4 = 8` CÉLULAS, e com
    `m = 6` isso NÃO basta: oito é menor que onze. Os dois pisos não se
    substituem, e um deles satisfeito não autoriza nada.

E O MESMO VALE POR HORIZONTE:

    E_h = max( 4, ceil(3m/5) )

O MÍNIMO ABSOLUTO DE OITO NÃO É ARBITRÁRIO: ele é o produto dos dois mínimos
que já existem — `4 eixos x 2 horizontes`. Mas ele quase nunca é o que decide:
para todo perfil ADMISSÍVEL (`m >= 4`) o piso racional o alcança ou o supera, e
só empata em `m = 4`.

OS LIMIARES SÃO RACIONAIS, E O TETO É INTEIRO. `math.ceil(0.6 * n)` arredonda a
divisão ANTES do teto, e o piso é calculado em `-((-3n) // 5)`.

    NÃO É QUE O FLOAT ERRE NUM PERFIL DE FUTEBOL. Foram medidos os dois
    milhões de primeiros `n`, e as duas formas concordam em todos.

    É QUE A FORMA INTEIRA É EXATA POR CONSTRUÇÃO e a de ponto flutuante é
    correta só sob um argumento de arredondamento — um que teria de ser
    reestabelecido a cada mudança de numerador, denominador ou faixa. E ele
    tem fim: em `n = 9_999_999_999_999_997` o float dá `5999999999999997` e o
    valor exato é `5999999999999999`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, final

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.retrieval.coverage import RationalFloor
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import DataQualityError, ValidationError

TRAJECTORY_COVERAGE_FINGERPRINT_ALGORITHM: Final[str] = "trajectory-coverage-policy-sha256-v1"

#: A política de cobertura temporal da V1.
MULTI_HORIZON_MINIMUM_EVIDENCE_COVERAGE_V1: Final[str] = (
    "MULTI_HORIZON_MINIMUM_EVIDENCE_COVERAGE_V1"
)

#: Os motivos tipados.
QUERY_INSUFFICIENT_TRAJECTORY_EVIDENCE: Final[str] = "QUERY_INSUFFICIENT_TRAJECTORY_EVIDENCE"
INSUFFICIENT_SHARED_TRAJECTORY_EVIDENCE: Final[str] = "INSUFFICIENT_SHARED_TRAJECTORY_EVIDENCE"

#: E os TRÊS motivos separados de recusa de um par.
#:
#: UM MOTIVO SÓ ESCONDERIA A DIFERENÇA. «Poucas células» e «só um horizonte»
#: são fenômenos distintos: o primeiro é atrição de feature, o segundo é o
#: começo do período. Contá-los juntos tornaria a atrição ilegível.
INSUFFICIENT_SHARED_TRAJECTORY_CELLS: Final[str] = "INSUFFICIENT_SHARED_TRAJECTORY_CELLS"
INSUFFICIENT_SHARED_HORIZONS: Final[str] = "INSUFFICIENT_SHARED_HORIZONS"
INSUFFICIENT_PER_HORIZON_COVERAGE: Final[str] = "INSUFFICIENT_PER_HORIZON_COVERAGE"
TRAJECTORY_PROFILE_INSUFFICIENT_AXES: Final[str] = "TRAJECTORY_PROFILE_INSUFFICIENT_AXES"

#: A versão do ALGORITMO que deriva os pisos efetivos.
#:
#: ELA ENTRA NA IMPRESSÃO DA POLÍTICA. Os pisos efetivos são função dos campos
#: que já existem, mas a FÓRMULA que os deriva também é parte do contrato: uma
#: política com os mesmos números e outra regra de derivação — teto para baixo,
#: denominador na interseção — produziria decisões diferentes sob a mesma
#: impressão.
EFFECTIVE_FLOOR_ALGORITHM_V1: Final[str] = "MAX_ABSOLUTE_CEIL_RATIONAL_V1"

#: O piso de tres quintos, nomeado UMA vez.
#:
#: ELE E UMA CONSTANTE E NAO TRES LITERAIS porque os tres pisos desta politica
#: sao o MESMO numero por decisao — o mesmo do PR-06.2 —, e escreve-lo tres
#: vezes e como um deles muda sozinho.
TRES_QUINTOS: Final[RationalFloor] = RationalFloor(3, 5)


@final
@dataclass(frozen=True, slots=True)
class TrajectoryFloors:
    """Os pisos EFETIVOS de um perfil de `m` eixos. Derivados, e explícitos.

    ELES NÃO SÃO CONFIGURAÇÃO. São função determinística da política e de `m`,
    e persisti-los criaria uma segunda fonte de verdade que poderia divergir da
    primeira. O que este contrato faz é torná-los LEGÍVEIS — para a evidência,
    para a CLI e para o relatório.

        «este candidato foi recusado»
        «este candidato precisava de onze células e tinha dez»

    A segunda frase só é dizível quando o piso é um NÚMERO.
    """

    profile_axis_count: int
    horizon_count: int
    absolute_query_cell_floor: int
    ratio_query_cell_floor: int
    absolute_shared_cell_floor: int
    ratio_shared_cell_floor: int
    absolute_horizon_axis_floor: int
    ratio_horizon_axis_floor: int
    algorithm: str = EFFECTIVE_FLOOR_ALGORITHM_V1

    @property
    def total_trajectory_cells(self) -> int:
        """`n = |H| . m` — o denominador FIXO, e a base dos pisos racionais."""
        return self.horizon_count * self.profile_axis_count

    @property
    def effective_query_cell_floor(self) -> int:
        return max(self.absolute_query_cell_floor, self.ratio_query_cell_floor)

    @property
    def effective_shared_cell_floor(self) -> int:
        """`E_s = max(absoluto, ceil(3n/5))`."""
        return max(self.absolute_shared_cell_floor, self.ratio_shared_cell_floor)

    @property
    def effective_horizon_axis_floor(self) -> int:
        """`E_h = max(absoluto, ceil(3m/5))`."""
        return max(self.absolute_horizon_axis_floor, self.ratio_horizon_axis_floor)

    @property
    def shared_floor_is_rational(self) -> bool:
        """Se é o piso RACIONAL que decide o piso compartilhado.

        ELA EXISTE PARA O RELATÓRIO. Sob a V1 ela é verdadeira para todo perfil
        admissível a partir de `m = 5`, e em `m = 4` os dois empatam — o mínimo
        absoluto de oito nunca é ESTRITAMENTE o que decide.
        """
        return self.ratio_shared_cell_floor >= self.absolute_shared_cell_floor

    def as_canonical(self) -> dict[str, object]:
        return {
            "algorithm": self.algorithm,
            "effective_horizon_axis_floor": self.effective_horizon_axis_floor,
            "effective_query_cell_floor": self.effective_query_cell_floor,
            "effective_shared_cell_floor": self.effective_shared_cell_floor,
            "profile_axis_count": self.profile_axis_count,
            "total_trajectory_cells": self.total_trajectory_cells,
        }

    def diagnostics(self) -> Mapping[str, object]:
        return {
            "absolute_horizon_axis_floor": self.absolute_horizon_axis_floor,
            "absolute_query_cell_floor": self.absolute_query_cell_floor,
            "absolute_shared_cell_floor": self.absolute_shared_cell_floor,
            "effective_horizon_axis_floor": self.effective_horizon_axis_floor,
            "effective_query_cell_floor": self.effective_query_cell_floor,
            "effective_shared_cell_floor": self.effective_shared_cell_floor,
            "profile_axis_count": self.profile_axis_count,
            "ratio_horizon_axis_floor": self.ratio_horizon_axis_floor,
            "ratio_query_cell_floor": self.ratio_query_cell_floor,
            "ratio_shared_cell_floor": self.ratio_shared_cell_floor,
            "shared_floor_is_rational": self.shared_floor_is_rational,
            "total_trajectory_cells": self.total_trajectory_cells,
        }

    def __str__(self) -> str:
        return (
            f"m={self.profile_axis_count} n={self.total_trajectory_cells} "
            f"E_s={self.effective_shared_cell_floor} "
            f"(abs {self.absolute_shared_cell_floor} / rac "
            f"{self.ratio_shared_cell_floor}) "
            f"E_h={self.effective_horizon_axis_floor}"
        )


@final
@dataclass(frozen=True, slots=True)
class TrajectoryCoveragePolicy:
    """O piso de evidência temporal. Imutável e impressa."""

    name: str = MULTI_HORIZON_MINIMUM_EVIDENCE_COVERAGE_V1
    version: int = 1
    #: O perfil base precisa de eixos bastantes — o mesmo mínimo do PR-06.2.
    minimum_profile_axes: int = 4
    #: Quantos horizontes EVIDENCIAIS a query precisa ter.
    minimum_usable_horizons: int = 2
    #: Quantos horizontes evidenciais o PAR precisa compartilhar.
    minimum_shared_horizons: int = 2
    #: `4 eixos x 2 horizontes`. ELE É UM MÍNIMO ABSOLUTO, E NÃO O PISO — o
    #: piso que decide é `max(este, ceil(3n/5))`, e para todo perfil admissível
    #: é o segundo termo que manda. Ver `floors()` e o cabeçalho.
    minimum_query_trajectory_cells: int = 8
    minimum_shared_trajectory_cells: int = 8
    #: `|Q_T| / n ≥ 3/5`.
    query_trajectory_coverage_floor: RationalFloor = TRES_QUINTOS
    #: `|S_T| / n ≥ 3/5`.
    shared_trajectory_coverage_floor: RationalFloor = TRES_QUINTOS
    #: O que faz um horizonte CONTAR como horizonte — ver o cabeçalho.
    per_horizon_axis_coverage_floor: RationalFloor = TRES_QUINTOS
    minimum_axes_per_evidential_horizon: int = 4

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("política de cobertura temporal sem nome")
        if self.version < 1:
            raise ValidationError(f"versão de política inválida: {self.version}")
        for rotulo, minimo in (
            ("minimum_profile_axes", self.minimum_profile_axes),
            ("minimum_usable_horizons", self.minimum_usable_horizons),
            ("minimum_shared_horizons", self.minimum_shared_horizons),
            ("minimum_query_trajectory_cells", self.minimum_query_trajectory_cells),
            ("minimum_shared_trajectory_cells", self.minimum_shared_trajectory_cells),
            ("minimum_axes_per_evidential_horizon", self.minimum_axes_per_evidential_horizon),
        ):
            if minimo < 1:
                raise ValidationError(
                    f"{rotulo} = {minimo}: um piso de zero admitiria um par sem "
                    "evidência temporal nenhuma, e a distância dele seria penalidade "
                    "pura"
                )
        if self.minimum_usable_horizons < 2:
            raise ValidationError(
                f"mínimo de {self.minimum_usable_horizons} horizonte(s): com um só, "
                "«movimento parecido» seria uma afirmação sobre um minuto de história "
                "— e a representação de múltiplos horizontes não teria função"
            )
        if self.minimum_shared_horizons > self.minimum_usable_horizons:
            raise ValidationError(
                "o par exige mais horizontes compartilhados do que a query precisa ter: "
                "nenhum candidato seria elegível, e a recusa seria silenciosa"
            )
        if (
            self.minimum_shared_trajectory_cells
            < self.minimum_shared_horizons * self.minimum_axes_per_evidential_horizon
        ):
            raise ValidationError(
                f"o mínimo de {self.minimum_shared_trajectory_cells} células é menor "
                f"que {self.minimum_shared_horizons} horizontes x "
                f"{self.minimum_axes_per_evidential_horizon} eixos: os dois pisos "
                "diriam coisas incompatíveis, e o mais frouxo nunca teria efeito"
            )

    # ------------------------------------------------------------ leitura --

    @property
    def identity(self) -> str:
        return f"{self.name}@{self.version}"

    # -------------------------------------------------------- as decisões --

    def floors(self, profile_axis_count: int, *, horizon_count: int = 3) -> TrajectoryFloors:
        """Os pisos efetivos daquele perfil — a ÚNICA derivação que existe.

        TODA DECISÃO PASSA POR AQUI. `admits_query`, `admits_pair` e
        `is_evidential_horizon` chamam este método em vez de recalcular a
        aritmética: duas formas da mesma regra é como uma delas passa a decidir
        sozinha.
        """
        if profile_axis_count < 0 or horizon_count < 1:
            raise ValidationError(
                f"pisos sobre {profile_axis_count} eixos e {horizon_count} horizontes"
            )
        celulas = horizon_count * profile_axis_count
        return TrajectoryFloors(
            profile_axis_count=profile_axis_count,
            horizon_count=horizon_count,
            absolute_query_cell_floor=self.minimum_query_trajectory_cells,
            ratio_query_cell_floor=self.query_trajectory_coverage_floor.minimum_part(celulas),
            absolute_shared_cell_floor=self.minimum_shared_trajectory_cells,
            ratio_shared_cell_floor=self.shared_trajectory_coverage_floor.minimum_part(celulas),
            absolute_horizon_axis_floor=self.minimum_axes_per_evidential_horizon,
            ratio_horizon_axis_floor=self.per_horizon_axis_coverage_floor.minimum_part(
                profile_axis_count
            ),
        )

    def cell_floors(self, cell_count: int) -> TrajectoryFloors:
        """Os pisos a partir do número de CÉLULAS, e não de eixos.

        `admits_query` e `admits_pair` recebem `n`, e não `m`. Como
        `n = |H| . m`, os pisos de CÉLULA dependem só de `n`; o de eixo por
        horizonte não é consultado por eles. Fixar `horizon_count = 1` faz a
        fábrica tratar `cell_count` como o espaço inteiro, que é o que os dois
        precisam.
        """
        return self.floors(cell_count, horizon_count=1)

    def admits_profile(self, axis_count: int) -> bool:
        return axis_count >= self.minimum_profile_axes

    def is_evidential_horizon(self, *, usable_axes: int, axis_count: int) -> bool:
        """Se ESTE horizonte sozinho descreve movimento.

        O CRITÉRIO É O PISO DO PR-06.2 aplicado ao horizonte. Um horizonte com
        um eixo de vinte existe estruturalmente e não descreve nada; contá-lo
        faria o piso de dois horizontes virar formalidade.
        """
        if axis_count < 1:
            return False
        return usable_axes >= self.floors(axis_count).effective_horizon_axis_floor

    def admits_query(self, *, usable_cells: int, cell_count: int, horizons: int) -> bool:
        if cell_count < 1:
            return False
        return (
            horizons >= self.minimum_usable_horizons
            and usable_cells >= self.cell_floors(cell_count).effective_query_cell_floor
        )

    def admits_pair(self, *, shared_cells: int, cell_count: int, shared_horizons: int) -> bool:
        if cell_count < 1:
            return False
        return (
            shared_horizons >= self.minimum_shared_horizons
            and shared_cells >= self.cell_floors(cell_count).effective_shared_cell_floor
        )

    def assert_profile_admissible(self, *, axis_count: int, competition: str) -> None:
        if self.admits_profile(axis_count):
            return
        raise TrajectoryProfileInsufficientAxesError(
            competition=competition,
            axis_count=axis_count,
            minimum=self.minimum_profile_axes,
            policy_identity=self.identity,
        )

    # -------------------------------------------------------------- forma --

    def as_canonical(self) -> dict[str, object]:
        return {
            "algorithm": TRAJECTORY_COVERAGE_FINGERPRINT_ALGORITHM,
            # A FÓRMULA DOS PISOS EFETIVOS É PARTE DO CONTRATO, e não só os
            # números que ela consome: a mesma política com teto para baixo, ou
            # com o denominador na interseção, decidiria diferente sob a mesma
            # impressão. Ela entra por VERSÃO, e não pelos pisos derivados —
            # esses dependem de `m`, e a política não conhece perfil nenhum.
            "effective_floor_algorithm": EFFECTIVE_FLOOR_ALGORITHM_V1,
            "minimum_axes_per_evidential_horizon": self.minimum_axes_per_evidential_horizon,
            "minimum_profile_axes": self.minimum_profile_axes,
            "minimum_query_trajectory_cells": self.minimum_query_trajectory_cells,
            "minimum_shared_horizons": self.minimum_shared_horizons,
            "minimum_shared_trajectory_cells": self.minimum_shared_trajectory_cells,
            "minimum_usable_horizons": self.minimum_usable_horizons,
            "name": self.name,
            "per_horizon_axis_coverage_floor": (
                self.per_horizon_axis_coverage_floor.as_canonical()
            ),
            "query_trajectory_coverage_floor": (
                self.query_trajectory_coverage_floor.as_canonical()
            ),
            "shared_trajectory_coverage_floor": (
                self.shared_trajectory_coverage_floor.as_canonical()
            ),
            "version": self.version,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def __str__(self) -> str:
        return (
            f"{self.identity} · >={self.minimum_shared_trajectory_cells} células, "
            f">={self.minimum_shared_horizons} horizontes, "
            f">={self.shared_trajectory_coverage_floor.text} "
            f"[{self.fingerprint[:12]}]"
        )


#: A política de produção da V1.
DEFAULT_TRAJECTORY_COVERAGE: Final[TrajectoryCoveragePolicy] = TrajectoryCoveragePolicy()


@final
@dataclass(frozen=True, slots=True)
class HorizonCoverage:
    """A cobertura de UM horizonte — quantos eixos ele tem dos dois lados."""

    horizon_minutes: int
    axis_count: int
    query_usable_axes: int
    candidate_usable_axes: int
    shared_axes: int
    policy: TrajectoryCoveragePolicy = DEFAULT_TRAJECTORY_COVERAGE

    def __post_init__(self) -> None:
        if self.shared_axes > min(self.query_usable_axes, self.candidate_usable_axes):
            raise ValidationError(
                f"horizonte de {self.horizon_minutes} min com {self.shared_axes} eixos "
                "compartilhados acima do menor dos dois lados"
            )

    @property
    def is_query_evidential(self) -> bool:
        return self.policy.is_evidential_horizon(
            usable_axes=self.query_usable_axes, axis_count=self.axis_count
        )

    @property
    def is_candidate_evidential(self) -> bool:
        return self.policy.is_evidential_horizon(
            usable_axes=self.candidate_usable_axes, axis_count=self.axis_count
        )

    @property
    def is_shared_evidential(self) -> bool:
        """O horizonte conta para o par quando a INTERSEÇÃO dele descreve movimento."""
        return self.policy.is_evidential_horizon(
            usable_axes=self.shared_axes, axis_count=self.axis_count
        )

    @property
    def shared_coverage(self) -> float:
        return self.shared_axes / self.axis_count

    def as_canonical(self) -> dict[str, object]:
        return {
            "candidate_usable_axes": self.candidate_usable_axes,
            "horizon_minutes": self.horizon_minutes,
            "query_usable_axes": self.query_usable_axes,
            "shared_axes": self.shared_axes,
        }

    def __str__(self) -> str:
        return (
            f"{self.horizon_minutes}m: {self.shared_axes}/{self.axis_count} "
            f"({'evidencial' if self.is_shared_evidential else 'insuficiente'})"
        )


@final
@dataclass(frozen=True, slots=True)
class TrajectoryCoverageAssessment:
    """Quanta evidência temporal ESTE par tem. Contagens primeiro."""

    cell_count: int
    axis_count: int
    query_usable_cells: int
    candidate_usable_cells: int
    shared_cells: int
    horizons: tuple[HorizonCoverage, ...] = ()
    policy: TrajectoryCoveragePolicy = DEFAULT_TRAJECTORY_COVERAGE

    def __post_init__(self) -> None:
        if self.cell_count < 1:
            raise ValidationError("cobertura temporal sobre um espaço sem células")
        for rotulo, contagem in (
            ("query_usable_cells", self.query_usable_cells),
            ("candidate_usable_cells", self.candidate_usable_cells),
            ("shared_cells", self.shared_cells),
        ):
            if contagem < 0 or contagem > self.cell_count:
                raise ValidationError(
                    f"{rotulo} = {contagem} sobre {self.cell_count} células: a máscara "
                    "é de outro espaço"
                )
        if self.shared_cells > min(self.query_usable_cells, self.candidate_usable_cells):
            raise ValidationError(
                f"{self.shared_cells} células compartilhadas entre uma query com "
                f"{self.query_usable_cells} e um candidato com "
                f"{self.candidate_usable_cells}: a interseção não pode ser maior que "
                "o menor dos dois lados"
            )

    # ---------------------------------------------------------- contagens --

    @property
    def unshared_cells(self) -> int:
        """`u_T = n - s`. As células do espaço FIXO que o par não usou."""
        return self.cell_count - self.shared_cells

    @property
    def query_usable_horizons(self) -> int:
        return sum(1 for h in self.horizons if h.is_query_evidential)

    @property
    def candidate_usable_horizons(self) -> int:
        return sum(1 for h in self.horizons if h.is_candidate_evidential)

    @property
    def shared_horizons(self) -> int:
        return sum(1 for h in self.horizons if h.is_shared_evidential)

    # ------------------------------------------------------------ frações --

    @property
    def query_coverage(self) -> float:
        return self.query_usable_cells / self.cell_count

    @property
    def candidate_coverage(self) -> float:
        return self.candidate_usable_cells / self.cell_count

    @property
    def shared_coverage(self) -> float:
        """`|S_T| / n`. A AUTORIDADE, com denominador fixo."""
        return self.shared_cells / self.cell_count

    @property
    def shared_query_coverage(self) -> float | None:
        if self.query_usable_cells < 1:
            return None
        return self.shared_cells / self.query_usable_cells

    # --------------------------------------------------------- os limiares --

    @property
    def floors(self) -> TrajectoryFloors:
        """Os pisos EFETIVOS deste espaço. Derivados da política, e legíveis.

        A AVALIAÇÃO NÃO OS GUARDA. Ela os deriva da mesma fábrica que decide,
        para que não exista número exibido que difira do número aplicado.
        """
        return self.policy.cell_floors(self.cell_count)

    @property
    def axis_floors(self) -> TrajectoryFloors:
        """Os pisos por EIXO — a base do piso de eixos por horizonte."""
        return self.policy.floors(self.axis_count)

    @property
    def total_trajectory_cells(self) -> int:
        """`n`. O mesmo que `cell_count`, com o nome do adendo."""
        return self.cell_count

    @property
    def effective_query_cell_floor(self) -> int:
        return self.floors.effective_query_cell_floor

    @property
    def effective_shared_cell_floor(self) -> int:
        """`E_s = max(8, ceil(3n/5))`. QUANTAS células este par precisava ter."""
        return self.floors.effective_shared_cell_floor

    @property
    def effective_horizon_axis_floor(self) -> int:
        """`E_h = max(4, ceil(3m/5))`."""
        return self.axis_floors.effective_horizon_axis_floor

    @property
    def meets_query_cell_floor(self) -> bool:
        return self.query_usable_cells >= self.effective_query_cell_floor

    @property
    def meets_shared_cell_floor(self) -> bool:
        """SÓ o piso de células. Ele não autoriza nada sozinho."""
        return self.shared_cells >= self.effective_shared_cell_floor

    @property
    def meets_horizon_count_floor(self) -> bool:
        """SÓ o piso de horizontes EVIDENCIAIS compartilhados."""
        return self.shared_horizons >= self.policy.minimum_shared_horizons

    @property
    def horizons_with_shared_axes(self) -> int:
        """Horizontes com QUALQUER eixo em comum — evidenciais ou não.

        ELE SEPARA DOIS DIAGNÓSTICOS. «Só um horizonte alcançável» é o começo
        do período; «três horizontes alcançáveis, e nenhum com eixos bastante»
        é atrição de feature. O primeiro número não distingue os dois.
        """
        return sum(1 for h in self.horizons if h.shared_axes > 0)

    @property
    def meets_query_floor(self) -> bool:
        return self.policy.admits_query(
            usable_cells=self.query_usable_cells,
            cell_count=self.cell_count,
            horizons=self.query_usable_horizons,
        )

    @property
    def meets_shared_floor(self) -> bool:
        return self.policy.admits_pair(
            shared_cells=self.shared_cells,
            cell_count=self.cell_count,
            shared_horizons=self.shared_horizons,
        )

    @property
    def refusal_reason(self) -> str | None:
        """QUAL dos três pisos recusou o par, na ordem do diagnóstico.

        A ORDEM VAI DO ESTRUTURAL AO DE DADO, e ela importa: um par que não
        alcança dois horizontes também não alcançará células bastante, e
        reportá-lo como «poucas células» apontaria para a feature quando a
        causa é o relógio.

            1. horizontes ALCANÇADOS de menos    o período começou agora
            2. horizontes evidenciais de menos   os eixos não bastam neles
            3. células compartilhadas de menos   o piso racional de `n`
        """
        if self.meets_shared_floor:
            return None
        if self.horizons_with_shared_axes < self.policy.minimum_shared_horizons:
            return INSUFFICIENT_SHARED_HORIZONS
        if not self.meets_horizon_count_floor:
            return INSUFFICIENT_PER_HORIZON_COVERAGE
        return INSUFFICIENT_SHARED_TRAJECTORY_CELLS

    @property
    def is_complete(self) -> bool:
        return self.shared_cells == self.cell_count

    @property
    def is_at_shared_floor(self) -> bool:
        """Se o par está EXATAMENTE na fronteira — em qualquer dos três pisos."""
        if not self.meets_shared_floor:
            return False
        return (
            self.shared_cells == self.effective_shared_cell_floor
            or self.shared_horizons == self.policy.minimum_shared_horizons
        )

    # -------------------------------------------------------------- forma --

    def as_canonical(self) -> dict[str, object]:
        """Só contagens — as frações são derivadas exatas delas."""
        return {
            "candidate_usable_cells": self.candidate_usable_cells,
            "cell_count": self.cell_count,
            "horizons": [h.as_canonical() for h in self.horizons],
            "query_usable_cells": self.query_usable_cells,
            "shared_cells": self.shared_cells,
        }

    def diagnostics(self) -> Mapping[str, object]:
        return {
            "candidate_coverage": self.candidate_coverage,
            "candidate_usable_cells": self.candidate_usable_cells,
            "candidate_usable_horizons": self.candidate_usable_horizons,
            "cell_count": self.cell_count,
            "effective_horizon_axis_floor": self.effective_horizon_axis_floor,
            "effective_query_cell_floor": self.effective_query_cell_floor,
            "effective_shared_cell_floor": self.effective_shared_cell_floor,
            "horizons_with_shared_axes": self.horizons_with_shared_axes,
            "meets_horizon_count_floor": self.meets_horizon_count_floor,
            "meets_query_cell_floor": self.meets_query_cell_floor,
            "meets_query_floor": self.meets_query_floor,
            "meets_shared_cell_floor": self.meets_shared_cell_floor,
            "meets_shared_floor": self.meets_shared_floor,
            "refusal_reason": self.refusal_reason,
            "query_coverage": self.query_coverage,
            "query_usable_cells": self.query_usable_cells,
            "query_usable_horizons": self.query_usable_horizons,
            "shared_cells": self.shared_cells,
            "shared_coverage": self.shared_coverage,
            "shared_horizons": self.shared_horizons,
            "unshared_cells": self.unshared_cells,
        }

    def __str__(self) -> str:
        return (
            f"s={self.shared_cells}/{self.cell_count} ({self.shared_coverage:.1%}) "
            f"em {self.shared_horizons} horizonte(s), piso efetivo "
            f"{self.effective_shared_cell_floor}"
        )


# ============================================================= os erros ==


@final
class TrajectoryProfileInsufficientAxesError(DataQualityError):
    """O perfil base da competição é pequeno demais para trajetória alguma."""

    def __init__(
        self, *, competition: str, axis_count: int, minimum: int, policy_identity: str
    ) -> None:
        super().__init__(
            f"{TRAJECTORY_PROFILE_INSUFFICIENT_AXES}: o perfil resolvido de "
            f"{competition} tem {axis_count} eixo(s), e a política {policy_identity} "
            f"exige {minimum}. A trajetória multiplica os eixos por horizonte, e "
            "multiplicar poucos eixos não cria evidência",
            context={
                "axis_count": axis_count,
                "competition": competition,
                "minimum_profile_axes": minimum,
                "policy": policy_identity,
                "reason": TRAJECTORY_PROFILE_INSUFFICIENT_AXES,
            },
        )
        self.competition = competition
        self.axis_count = axis_count
        self.minimum = minimum

    @property
    def reason(self) -> str:
        return TRAJECTORY_PROFILE_INSUFFICIENT_AXES


@final
class QueryInsufficientTrajectoryEvidenceError(DataQualityError):
    """A query não tem história recente bastante para perguntar.

    O CASO MAIS COMUM É O COMEÇO DO PERÍODO. No minuto 47 do segundo tempo, só
    o horizonte de um minuto está dentro do período: `t-3` cairia no 44, que é
    primeiro tempo. Um horizonte não descreve movimento, e a query é recusada —
    sem varrer candidato nenhum.

    ISSO NÃO É DEFEITO DE DADO. É o começo do período não ter passado dentro
    dele, e a recusa é a resposta certa: a alternativa seria atravessar o
    intervalo, que é o blocker do §247.
    """

    def __init__(
        self,
        *,
        key: HistoricalFeatureSnapshotKey,
        anchor: str,
        assessment: TrajectoryCoverageAssessment,
        policy: TrajectoryCoveragePolicy,
    ) -> None:
        super().__init__(
            f"{QUERY_INSUFFICIENT_TRAJECTORY_EVIDENCE}: a query {key.text} em {anchor} "
            f"tem {assessment.query_usable_cells} de {assessment.cell_count} células "
            f"de trajetória em {assessment.query_usable_horizons} horizonte(s) "
            f"evidencial(is), e a política {policy.identity} exige "
            f"{policy.minimum_query_trajectory_cells} células, "
            f"{policy.minimum_usable_horizons} horizontes e "
            f"{policy.query_trajectory_coverage_floor.text} do espaço",
            context={
                "anchor": anchor,
                "cell_count": assessment.cell_count,
                "key": key.text,
                "minimum_cells": policy.minimum_query_trajectory_cells,
                "minimum_horizons": policy.minimum_usable_horizons,
                "policy": policy.identity,
                "reason": QUERY_INSUFFICIENT_TRAJECTORY_EVIDENCE,
                "usable_cells": assessment.query_usable_cells,
                "usable_horizons": assessment.query_usable_horizons,
            },
        )
        self.key = key
        self.anchor = anchor
        self.assessment = assessment

    @property
    def reason(self) -> str:
        return QUERY_INSUFFICIENT_TRAJECTORY_EVIDENCE


def trajectory_coverage_summary(
    assessment: TrajectoryCoverageAssessment,
) -> Sequence[str]:
    """As linhas do resumo legível — para a CLI e para o relatório."""
    linhas = [
        f"células          {assessment.cell_count}",
        f"query            {assessment.query_usable_cells} "
        f"({assessment.query_coverage:.1%}) em {assessment.query_usable_horizons} horiz.",
        f"candidato        {assessment.candidate_usable_cells} "
        f"({assessment.candidate_coverage:.1%}) em "
        f"{assessment.candidate_usable_horizons} horiz.",
        f"compartilhadas   {assessment.shared_cells} "
        f"({assessment.shared_coverage:.1%}) em {assessment.shared_horizons} horiz.",
        f"ausentes         {assessment.unshared_cells}",
    ]
    linhas.extend(f"  {h}" for h in assessment.horizons)
    return linhas
