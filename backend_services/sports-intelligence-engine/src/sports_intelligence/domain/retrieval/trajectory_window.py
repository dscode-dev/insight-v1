"""Quais instantes passados a trajetória olha — e quais ela recusa a olhar.

    T_t = [ X_{t-5}, X_{t-3}, X_{t-1}, X_t ]        H = {1, 3, 5}

TRÊS ESCALAS, E NÃO UMA JANELA DESLIZANTE. Carregar `t-1, t-2, t-3, t-4, t-5`
traria cinco instantes fortemente correlacionados entre si e multiplicaria o
custo por cinco para acrescentar quase nada:

    1 min    o movimento MUITO recente
    3 min    o movimento curto
    5 min    a tendência local

O CONJUNTO É FIXO. Ele não é derivado do que a query tem — ver
`TrajectoryCoveragePolicy` — nem otimizado neste PR: escolher horizontes por
otimização exigiria uma medida de acerto, e não há rótulo de verdade com que
construí-la antes do PR-06.5.

**O LOOKBACK NÃO ATRAVESSA O PERÍODO.** Esta é a decisão que o módulo existe
para impor. A grade conta os minutos do segundo tempo CONTINUANDO os do
primeiro — o minuto 49 é do segundo tempo, e o 44 é do primeiro:

    âncora SECOND_HALF 49
        t-1  →  48   dentro do segundo tempo
        t-3  →  46   dentro do segundo tempo
        t-5  →  44   PRIMEIRO TEMPO  →  OUTSIDE_PERIOD_LOOKBACK

O intervalo não tem duração esportiva equivalente a um minuto de jogo. Tratar
`45 → 46` como minutos adjacentes de dinâmica diria que a pressão caiu ou subiu
durante quinze minutos de vestiário — e a trajetória mediria o intervalo.

    NÃO HÁ RELÓGIO DE PAREDE AQUI. Nada de `kickoff + minuto`, nada de inferir
    a duração do intervalo. O tempo é o da GRADE ESPORTIVA, e ele é
    period-local — a mesma filosofia do PR-05.3.

OS LIMITES DE CADA PERÍODO VÊM DA GRADE, e não de constantes locais. A
`SnapshotGridPolicy` é quem sabe que o primeiro tempo termina no 45 e o segundo
começa no 46; uma segunda tabela aqui divergiria dela no dia em que alguém
mudasse os limites, e a trajetória passaria a atravessar o intervalo sem que
nada denunciasse.

O QUE ESTA POLÍTICA RECUSA:

    futuro              todo horizonte é POSITIVO e vira lookback. Não existe
                        `t + h` no catálogo, e não há como pedir um
    tolerância          nada de ±1 minuto, vizinho mais próximo, DTW,
                        interpolação ou deformação temporal
    fabricação          um corte que a grade não produz não é inventado. Se a
                        grade não declara o slot, a resposta é
                        UNSUPPORTED_TRAJECTORY_GRID
    preenchimento       um slot fora do período é AUSÊNCIA ESTRUTURAL, e não
                        um convite a usar o minuto vizinho
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol, final

from sports_intelligence.domain.features.dataset.grid import (
    LIVE_COMPARABLE_MINUTE_GRID_V1,
    SnapshotGridPolicy,
)
from sports_intelligence.domain.retrieval.timepoint import (
    GRID_STOPPAGE,
    GridTimePoint,
)
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import DataQualityError, ValidationError
from sports_intelligence.domain.shared.temporal import Period

TRAJECTORY_WINDOW_FINGERPRINT_ALGORITHM: Final[str] = "trajectory-window-policy-sha256-v1"

#: A política de janela da V1. O nome carrega as duas decisões — mesmo período,
#: horizontes fixos — porque as duas são contestáveis e nenhuma é óbvia.
SAME_PERIOD_FIXED_HORIZON_1_3_5_V1: Final[str] = "SAME_PERIOD_FIXED_HORIZON_1_3_5_V1"

#: A ordem canônica dos horizontes. Ela é a MESMA em impressão, máscara,
#: evidência e serialização — três ordens diferentes para a mesma tupla é como
#: uma máscara passa a descrever outro espaço sem que ninguém perceba.
HORIZONS: Final[tuple[int, ...]] = (1, 3, 5)

#: As grades cujos deslocamentos de um, três e cinco minutos EXISTEM.
#:
#: A LISTA É EXPLÍCITA, e não uma checagem de «tem minuto». Uma grade de cinco
#: cortes por partida também tem minuto, e `t-3` nela não é três minutos de
#: jogo — é três cortes, que podem ser vinte minutos. Compatibilidade aqui
#: significa «o índice da grade anda de minuto em minuto».
SUPPORTED_GRIDS: Final[frozenset[str]] = frozenset({LIVE_COMPARABLE_MINUTE_GRID_V1})

#: Os motivos tipados, para quem trata o erro sem ler texto.
TRAJECTORY_NOT_APPLICABLE: Final[str] = "TRAJECTORY_NOT_APPLICABLE"
UNSUPPORTED_TRAJECTORY_GRID: Final[str] = "UNSUPPORTED_TRAJECTORY_GRID"
UNSUPPORTED_TRAJECTORY_TIMEPOINT: Final[str] = "UNSUPPORTED_TRAJECTORY_TIMEPOINT"
TRAJECTORY_SOURCE_ROW_MISSING: Final[str] = "TRAJECTORY_SOURCE_ROW_MISSING"


@final
class SlotStatus(StrEnum):
    """O que aconteceu com UM slot de lookback. Catálogo FECHADO.

    ELE É SOBRE O SLOT, E NÃO SOBRE AS FEATURES DENTRO DELE (§44). São dois
    níveis de disponibilidade, e confundi-los apagaria a diferença entre «não
    havia minuto 44 no segundo tempo» e «havia a linha e o eixo estava vazio».

        SlotStatus                 o instante existe na trajetória?
        NormalizationAvailability  o eixo tem número naquela linha?

    OS ERROS ESTRUTURAIS NÃO ESTÃO AQUI. `TRAJECTORY_SOURCE_ROW_MISSING` e
    `UNSUPPORTED_TRAJECTORY_GRID` são exceções, e não estados: uma linha que
    deveria existir e não existe é quebra de integridade, e registrá-la como um
    status a transformaria em ausência normal.
    """

    #: O instante existe na grade, dentro do mesmo período, e a linha veio.
    AVAILABLE = "AVAILABLE"
    #: `t - h` cai antes do começo do período da âncora. ESPERADO.
    OUTSIDE_PERIOD_LOOKBACK = "OUTSIDE_PERIOD_LOOKBACK"
    #: A âncora não tem trajetória — `PRE_MATCH`, intervalo, fim de jogo.
    NOT_APPLICABLE = "NOT_APPLICABLE"

    @property
    def is_available(self) -> bool:
        return self is SlotStatus.AVAILABLE


@final
class PeriodCrossingPolicy(StrEnum):
    """O que fazer quando o lookback sai do período. Catálogo FECHADO.

    `ALLOW` NÃO EXISTE, e a ausência é o ponto: nomeá-lo seria admitir que
    atravessar o intervalo é configurável. Ver o cabeçalho do módulo.
    """

    #: O slot vira `OUTSIDE_PERIOD_LOOKBACK`, e nenhuma linha é lida.
    STOP_AT_PERIOD_START = "STOP_AT_PERIOD_START"


@final
class TrajectoryDirection(StrEnum):
    """Para onde a janela olha. Catálogo FECHADO, com UM membro.

    `FORWARD` NÃO EXISTE. O catálogo tem um membro só para que «a trajetória
    olha para trás» seja um campo conferível e impresso, e não um comentário —
    e para que não haja como pedir `t + h` nem por engano (§213, §254).
    """

    BACKWARD = "BACKWARD"


@final
@dataclass(frozen=True, slots=True)
class TrajectoryWindowPolicy:
    """Quais instantes passados a trajetória consulta. Imutável e impressa."""

    name: str = SAME_PERIOD_FIXED_HORIZON_1_3_5_V1
    version: int = 1
    horizons: tuple[int, ...] = HORIZONS
    direction: TrajectoryDirection = TrajectoryDirection.BACKWARD
    period_crossing: PeriodCrossingPolicy = PeriodCrossingPolicy.STOP_AT_PERIOD_START
    supported_grids: frozenset[str] = SUPPORTED_GRIDS

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("política de janela sem nome")
        if self.version < 1:
            raise ValidationError(f"versão de política inválida: {self.version}")
        if not self.horizons:
            raise ValidationError(
                "política de janela sem horizonte: ela não olharia para instante "
                "nenhum, e toda trajetória seria vazia"
            )
        if any(h <= 0 for h in self.horizons):
            raise ValidationError(
                f"horizonte não positivo em {self.horizons}: um horizonte de zero é a "
                "própria âncora, e um negativo é o FUTURO — e nenhuma informação "
                "posterior a t pode participar da trajetória",
                context={"horizons": str(self.horizons)},
            )
        if list(self.horizons) != sorted(set(self.horizons)):
            raise ValidationError(
                f"horizontes {self.horizons} fora de ordem ou repetidos: a ordem é "
                "canônica e entra na impressão, na máscara e na evidência — três "
                "ordens diferentes para a mesma tupla é como uma máscara passa a "
                "descrever outro espaço"
            )
        if not self.supported_grids:
            raise ValidationError(
                "política sem grade suportada: ela recusaria todo dataset, e a recusa "
                "pareceria um defeito de dado"
            )

    # ------------------------------------------------------------ leitura --

    @property
    def identity(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def horizon_count(self) -> int:
        return len(self.horizons)

    @property
    def deepest_horizon(self) -> int:
        return max(self.horizons)

    def supports(self, grid: SnapshotGridPolicy) -> bool:
        """Se os deslocamentos desta política EXISTEM naquela grade."""
        return grid.name in self.supported_grids

    def assert_supports(self, grid: SnapshotGridPolicy) -> None:
        if self.supports(grid):
            return
        raise UnsupportedTrajectoryGridError(
            grid_name=grid.name,
            supported=tuple(sorted(self.supported_grids)),
            policy_identity=self.identity,
        )

    # ------------------------------------------------------- a resolução --

    def resolve(
        self, anchor: GridTimePoint, *, grid: SnapshotGridPolicy
    ) -> tuple[ResolvedSlot, ...]:
        """Os instantes-alvo de cada horizonte, na ORDEM canônica.

        ELA NÃO LÊ NADA. O que ela devolve é «qual instante procurar, e se
        procurá-lo faz sentido» — a leitura é do adaptador, e separá-las é o
        que torna o contrato temporal testável sem Parquet.

        A ÂNCORA É CONFERIDA CONTRA A GRADE antes de qualquer aritmética: um
        acréscimo diferente de zero ou uma fase sem trajetória param aqui, e
        não viram um lookback inventado.
        """
        self.assert_supports(grid)
        if not _tem_trajetoria(anchor.period):
            return tuple(
                ResolvedSlot(horizon_minutes=h, target=None, status=SlotStatus.NOT_APPLICABLE)
                for h in self.horizons
            )
        inicio = _primeiro_minuto(anchor.period, grid)
        if anchor.minute < inicio:
            raise UnsupportedTrajectoryTimePointError(
                anchor=anchor.text,
                detail=(
                    f"o minuto {anchor.minute} está antes do começo de "
                    f"{anchor.period.value} nesta grade, que é {inicio}"
                ),
            )
        resolvidos: list[ResolvedSlot] = []
        for horizonte in self.horizons:
            alvo = anchor.minute - horizonte
            if alvo < inicio:
                # ESTRUTURALMENTE FORA, e não «faltando»: o instante não
                # pertence a este período, e o anterior não é adjacente.
                resolvidos.append(
                    ResolvedSlot(
                        horizon_minutes=horizonte,
                        target=None,
                        status=SlotStatus.OUTSIDE_PERIOD_LOOKBACK,
                    )
                )
                continue
            resolvidos.append(
                ResolvedSlot(
                    horizon_minutes=horizonte,
                    target=GridTimePoint.of(anchor.period, alvo),
                    status=SlotStatus.AVAILABLE,
                )
            )
        return tuple(resolvidos)

    def is_applicable(self, anchor: GridTimePoint) -> bool:
        """Se a âncora tem trajetória em princípio — antes de olhar dados."""
        return _tem_trajetoria(anchor.period)

    def assert_applicable(self, anchor: GridTimePoint) -> None:
        if self.is_applicable(anchor):
            return
        raise TrajectoryNotApplicableError(anchor=anchor.text, period=anchor.period.value)

    # -------------------------------------------------------------- forma --

    def as_canonical(self) -> dict[str, object]:
        return {
            "algorithm": TRAJECTORY_WINDOW_FINGERPRINT_ALGORITHM,
            "direction": self.direction.value,
            "grid_stoppage": GRID_STOPPAGE,
            "horizons": list(self.horizons),
            "name": self.name,
            "period_crossing": self.period_crossing.value,
            "supported_grids": sorted(self.supported_grids),
            "version": self.version,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def __str__(self) -> str:
        horizontes = "/".join(str(h) for h in self.horizons)
        return f"{self.identity} · {horizontes} min [{self.fingerprint[:12]}]"


@final
@dataclass(frozen=True, slots=True)
class ResolvedSlot:
    """Qual instante procurar para UM horizonte — e se procurá-lo faz sentido.

    ELE É O RESULTADO DA ARITMÉTICA, e não da leitura. `target is None` quando
    o slot não existe estruturalmente; quem lê recebe a lista e sabe
    exatamente quais instantes pedir ao adaptador — e quais não pedir.
    """

    horizon_minutes: int
    target: GridTimePoint | None
    status: SlotStatus

    def __post_init__(self) -> None:
        if self.status.is_available and self.target is None:
            raise ValidationError(
                f"slot de {self.horizon_minutes} min disponível e sem instante-alvo: "
                "quem lesse isto não teria o que procurar"
            )
        if not self.status.is_available and self.target is not None:
            raise ValidationError(
                f"slot de {self.horizon_minutes} min com status {self.status.value} e "
                f"instante-alvo {self.target.text}: um slot indisponível com alvo é o "
                "convite para alguém lê-lo assim mesmo"
            )

    def as_canonical(self) -> dict[str, object]:
        return {
            "horizon_minutes": self.horizon_minutes,
            "status": self.status.value,
            "target": None if self.target is None else self.target.as_canonical(),
        }

    def __str__(self) -> str:
        alvo = "-" if self.target is None else self.target.text
        return f"{self.horizon_minutes}m -> {alvo} [{self.status.value}]"


#: A política de produção da V1.
DEFAULT_TRAJECTORY_WINDOW: Final[TrajectoryWindowPolicy] = TrajectoryWindowPolicy()


# ============================================================= os erros ==


@final
class TrajectoryNotApplicableError(DataQualityError):
    """A âncora não é um instante com trajetória.

    `PRE_MATCH` NÃO TEM MOVIMENTO RECENTE, e o intervalo e o fim de jogo também
    não: não há minuto anterior DENTRO daquela fase. Isso não é dado faltando —
    é a fase não ter história interna —, e o tipo separado existe para que
    quem consome saiba que tentar de novo não muda nada.
    """

    def __init__(self, *, anchor: str, period: str) -> None:
        super().__init__(
            f"{TRAJECTORY_NOT_APPLICABLE}: a âncora {anchor} está em {period}, e essa "
            "fase não tem minuto anterior dentro dela. Trajetória é movimento DENTRO "
            "de um período, e inventar um lookback aqui mediria o intervalo",
            context={"anchor": anchor, "period": period, "reason": TRAJECTORY_NOT_APPLICABLE},
        )
        self.anchor = anchor
        self.period = period

    @property
    def reason(self) -> str:
        return TRAJECTORY_NOT_APPLICABLE


@final
class UnsupportedTrajectoryGridError(DataQualityError):
    """A grade do dataset não produz os deslocamentos desta política.

    UMA GRADE DE CINCO CORTES TAMBÉM TEM MINUTO, e `t-3` nela não são três
    minutos de jogo — são três cortes, que podem ser vinte minutos. Aceitar
    qualquer grade que tenha a coluna `minute` produziria trajetórias cujos
    horizontes não significam o que o nome diz.
    """

    def __init__(self, *, grid_name: str, supported: Sequence[str], policy_identity: str) -> None:
        super().__init__(
            f"{UNSUPPORTED_TRAJECTORY_GRID}: o dataset foi construído sob a grade "
            f"{grid_name!r}, e a política {policy_identity} só sabe deslocar minuto a "
            f"minuto em {list(supported)}. Fabricar os slots faria os horizontes de "
            "1/3/5 minutos significarem outra coisa",
            context={
                "grid": grid_name,
                "policy": policy_identity,
                "reason": UNSUPPORTED_TRAJECTORY_GRID,
                "supported": list(supported),
            },
        )
        self.grid_name = grid_name

    @property
    def reason(self) -> str:
        return UNSUPPORTED_TRAJECTORY_GRID


@final
class UnsupportedTrajectoryTimePointError(DataQualityError):
    """A âncora não é um instante que esta grade produz."""

    def __init__(self, *, anchor: str, detail: str) -> None:
        super().__init__(
            f"{UNSUPPORTED_TRAJECTORY_TIMEPOINT}: {detail} (âncora {anchor})",
            context={
                "anchor": anchor,
                "detail": detail,
                "reason": UNSUPPORTED_TRAJECTORY_TIMEPOINT,
            },
        )
        self.anchor = anchor

    @property
    def reason(self) -> str:
        return UNSUPPORTED_TRAJECTORY_TIMEPOINT


@final
class TrajectorySourceRowMissingError(DataQualityError):
    """O slot existe na grade, e a linha não veio.

    ISTO É QUEBRA DE INTEGRIDADE, e não ausência de feature (§30). A grade
    produz noventa e uma linhas por partida, e o dataset normalizado tem
    contrato 1:1 com o cru: um instante que a grade declara e o Parquet não
    entrega significa dataset incompleto ou leitura errada.

    TRATÁ-LO COMO AUSÊNCIA NORMAL seria a pior saída possível: a célula viraria
    penalidade, o candidato cairia algumas posições, e a corrupção sairia como
    um número plausível.
    """

    def __init__(self, *, match_key: str, target: str, anchor: str) -> None:
        super().__init__(
            f"{TRAJECTORY_SOURCE_ROW_MISSING}: a trajetória de {anchor} precisa da "
            f"linha {match_key} em {target}, a grade a declara, e ela não veio. Isto é "
            "dataset incompleto — tratá-lo como eixo ausente faria a corrupção sair "
            "como uma penalidade plausível",
            context={
                "anchor": anchor,
                "match_key": match_key,
                "reason": TRAJECTORY_SOURCE_ROW_MISSING,
                "target": target,
            },
        )
        self.match_key = match_key
        self.target = target

    @property
    def reason(self) -> str:
        return TRAJECTORY_SOURCE_ROW_MISSING


# ======================================================= a aritmética ==

#: As fases em que existe movimento DENTRO da fase. O intervalo, o fim de jogo
#: e a disputa de pênaltis não têm minuto anterior interno.
_FASES_COM_TRAJETORIA: Final[frozenset[Period]] = frozenset(
    {
        Period.FIRST_HALF,
        Period.SECOND_HALF,
        Period.EXTRA_TIME_FIRST,
        Period.EXTRA_TIME_SECOND,
    }
)


def _tem_trajetoria(period: Period) -> bool:
    return period in _FASES_COM_TRAJETORIA


def _primeiro_minuto(period: Period, grid: SnapshotGridPolicy) -> int:
    """O primeiro minuto daquele período NAQUELA grade.

    OS LIMITES VÊM DA GRADE, e não de constantes locais. A grade conta os
    minutos do segundo tempo continuando os do primeiro — o segundo começa em
    `first_half_last_minute + 1` —, e uma segunda tabela aqui divergiria dela
    no dia em que alguém mudasse os limites. A trajetória passaria a atravessar
    o intervalo, e nada denunciaria.
    """
    from sports_intelligence.domain.features.dataset.grid import (
        EXTRA_TIME_FIRST_LAST_MINUTE,
    )

    if period is Period.FIRST_HALF:
        return 1
    if period is Period.SECOND_HALF:
        return grid.first_half_last_minute + 1
    if period is Period.EXTRA_TIME_FIRST:
        return grid.second_half_last_minute + 1
    if period is Period.EXTRA_TIME_SECOND:
        return EXTRA_TIME_FIRST_LAST_MINUTE + 1
    raise ValidationError(  # pragma: no cover — `_tem_trajetoria` já filtrou
        f"fase {period.value} não tem minutos de jogo próprios"
    )


def period_first_minute(period: Period, grid: SnapshotGridPolicy) -> int:
    """O primeiro minuto do período — público, para diagnóstico e teste."""
    return _primeiro_minuto(period, grid)


def window_summary(policy: TrajectoryWindowPolicy, slots: Sequence[ResolvedSlot]) -> Sequence[str]:
    """As linhas do resumo legível — para a CLI e para o relatório."""
    linhas = [f"política  {policy.identity}", f"horizontes {list(policy.horizons)}"]
    linhas.extend(f"  {slot}" for slot in slots)
    return linhas


class _ComStatus(Protocol):
    """Qualquer coisa que tenha um `SlotStatus` — resolvida ou montada."""

    @property
    def status(self) -> SlotStatus: ...


def slot_counts(slots: Sequence[_ComStatus]) -> Mapping[str, int]:
    """Quantos slots caíram em cada status — para o relatório.

    ELE ACEITA OS DOIS TIPOS DE SLOT. `ResolvedSlot` é o que a aritmética
    produz e `TrajectorySlot` é o que a montagem produz; os dois carregam o
    mesmo catálogo de status, e contá-los é a mesma conta.
    """
    contagem = {status.value: 0 for status in SlotStatus}
    for slot in slots:
        contagem[slot.status.value] += 1
    return contagem
