"""A trajetória — o que ela é, e por que ela NÃO é a concatenação dos estados.

A REPRESENTAÇÃO ÓBVIA SERIA ESTA, e ela é a errada:

    [ x(t-5), x(t-3), x(t-1), x(t) ]

Quatro cópias quase iguais do mesmo nível. Três quartos do vetor repetem o que
o estado já mede, e a distância resultante seria dominada pelo NÍVEL — o
PR-06.2 outra vez, com quatro vezes o custo.

A REPRESENTAÇÃO DESTE PR É O DESLOCAMENTO:

    Δ_{h,i}(x) = x_i(t) - x_i(t-h)

«quanto aquela dimensão se moveu nos últimos `h` minutos». O nível atual já
pertence à recuperação de estado; o que sobra aqui é o MOVIMENTO.

    A ORTOGONALIDADE É POR CONSTRUÇÃO, e é o ponto do PR:

        A:  10 → 12       B:  20 → 22
        níveis diferentes · movimento IDÊNTICO (Δ = +2)

    O estado separa os dois. A trajetória os reconhece como a mesma forma. As
    duas coisas estão certas, e medem perguntas diferentes.

E O INVERSO TAMBÉM:

        query:      -2 → 0      Δ = +2
        candidato A: -2 → 0      Δ = +2      mesma direção
        candidato B: +2 → 0      Δ = -2      direção OPOSTA

    O estado empata A e B — os dois estão em zero agora. A trajetória os
    separa, e é exatamente para isso que este PR existe.

SEM VELOCIDADE, E A DECISÃO É DELIBERADA. Não dividimos por `h`. O deslocamento
preserva a unidade do espaço — desvios em unidades de IQR da competição —, e é
isso que mantém a penalidade `p = 1` do PR-06.2 semanticamente interpretável:
uma célula ausente custa «um IQR de incerteza», e `Δ/h` custaria «um IQR por
minuto», que é outra grandeza. `Δ/h` é uma derivação futura possível; ela não
decide ranking aqui.

DOIS NÍVEIS DE DISPONIBILIDADE, e confundi-los é o defeito mais fácil deste PR:

    SlotStatus                   o INSTANTE existe? (fora do período?)
    NormalizationAvailability    o EIXO tem número naquela linha?

A célula `(horizonte, eixo)` só é utilizável quando o slot existe E os dois
extremos têm número finito. Um extremo só não produz meio deslocamento.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, final

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.retrieval.availability import (
    availability_mask,
    mask_text,
)
from sports_intelligence.domain.retrieval.distance import distance_text
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from sports_intelligence.domain.retrieval.trajectory_window import (
    ResolvedSlot,
    SlotStatus,
    TrajectorySourceRowMissingError,
    TrajectoryWindowPolicy,
)
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError

TRAJECTORY_FINGERPRINT_ALGORITHM: Final[str] = "historical-trajectory-sha256-v1"
REPRESENTATION_FINGERPRINT_ALGORITHM: Final[str] = "trajectory-representation-sha256-v1"

#: Como o deslocamento é calculado. Ele entra na impressão do perfil porque uma
#: representação diferente — velocidade, aceleração, razão — produziria números
#: com a mesma cara e outra grandeza.
DISPLACEMENT_REPRESENTATION_V1: Final[str] = "ABSOLUTE_DISPLACEMENT_ANCHOR_MINUS_LOOKBACK_V1"


@final
@dataclass(frozen=True, slots=True)
class TrajectoryRow:
    """Uma linha de lookback, como o leitor a entrega.

    ELA CARREGA MENOS QUE UM `CandidateRow`: não há metade, competição nem
    representação, porque essas já foram conferidas na âncora — a linha de
    lookback é da MESMA partida, e uma linha de outra partida chegando aqui é
    defeito de montagem, não de política.
    """

    key: HistoricalFeatureSnapshotKey
    position: GridTimePoint
    row_digest: str
    values: Mapping[str, float | None]
    availabilities: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.row_digest.strip():
            raise ValidationError(
                f"linha de lookback {self.key} sem digesto: ele é o que amarra a "
                "trajetória ao conteúdo exato que a produziu"
            )


@final
@dataclass(frozen=True, slots=True)
class TrajectorySlot:
    """Um horizonte resolvido, com a linha que o preencheu — ou sem ela."""

    horizon_minutes: int
    target: GridTimePoint | None
    status: SlotStatus
    source_key: HistoricalFeatureSnapshotKey | None = None
    source_row_digest: str | None = None

    def __post_init__(self) -> None:
        if self.status.is_available and (self.source_key is None or self.source_row_digest is None):
            raise ValidationError(
                f"slot de {self.horizon_minutes} min disponível e sem linha de origem: "
                "quem construísse o deslocamento não teria de onde tirar o extremo"
            )
        if not self.status.is_available and self.source_key is not None:
            raise ValidationError(
                f"slot de {self.horizon_minutes} min com status {self.status.value} e "
                "linha de origem: um slot estruturalmente ausente com linha é o convite "
                "para alguém usá-la assim mesmo"
            )

    @property
    def is_available(self) -> bool:
        return self.status.is_available

    def as_canonical(self) -> dict[str, object]:
        return {
            "horizon_minutes": self.horizon_minutes,
            "source_row_digest": self.source_row_digest,
            "status": self.status.value,
            "target": None if self.target is None else self.target.as_canonical(),
        }

    def __str__(self) -> str:
        alvo = "-" if self.target is None else self.target.text
        return f"{self.horizon_minutes}m -> {alvo} [{self.status.value}]"


@final
@dataclass(frozen=True, slots=True)
class HistoricalTrajectory:
    """A âncora, os slots e a linhagem — ANTES de qualquer deslocamento.

    ELA É SEPARADA DA REPRESENTAÇÃO de propósito. Esta é a resposta a «quais
    instantes esta trajetória alcança?», e ela não depende do perfil de
    features: dois perfis diferentes sobre a mesma âncora alcançam os MESMOS
    instantes, e só depois divergem em quais eixos usam.
    """

    anchor_key: HistoricalFeatureSnapshotKey
    match_key: str
    competition: str
    anchor_position: GridTimePoint
    anchor_row_digest: str
    policy_fingerprint: str
    policy_identity: str
    slots: tuple[TrajectorySlot, ...] = ()

    def __post_init__(self) -> None:
        horizontes = [slot.horizon_minutes for slot in self.slots]
        if horizontes != sorted(set(horizontes)):
            raise ValidationError(
                f"slots {horizontes} fora de ordem ou repetidos: a ordem dos "
                "horizontes é canônica e entra na impressão"
            )
        for slot in self.slots:
            if slot.target is not None and slot.target.period is not self.anchor_position.period:
                raise ValidationError(
                    f"slot de {slot.horizon_minutes} min apontando para "
                    f"{slot.target.text}, fora do período da âncora "
                    f"{self.anchor_position.text}: o intervalo não tem duração "
                    "esportiva equivalente a um minuto de jogo",
                    context={"anchor": self.anchor_position.text, "target": slot.target.text},
                )
            if slot.target is not None and slot.target >= self.anchor_position:
                raise ValidationError(
                    f"slot de {slot.horizon_minutes} min apontando para "
                    f"{slot.target.text}, que NÃO é anterior à âncora "
                    f"{self.anchor_position.text}: nenhuma informação posterior a t "
                    "pode participar da trajetória",
                    context={"anchor": self.anchor_position.text, "target": slot.target.text},
                )

    # ------------------------------------------------------------ leitura --

    @property
    def horizons(self) -> tuple[int, ...]:
        return tuple(slot.horizon_minutes for slot in self.slots)

    @property
    def available_slots(self) -> tuple[TrajectorySlot, ...]:
        return tuple(slot for slot in self.slots if slot.is_available)

    @property
    def available_horizon_count(self) -> int:
        """Quantos horizontes existem ESTRUTURALMENTE. Antes das features."""
        return len(self.available_slots)

    @property
    def is_applicable(self) -> bool:
        return any(slot.status is not SlotStatus.NOT_APPLICABLE for slot in self.slots)

    def slot_of(self, horizon: int) -> TrajectorySlot | None:
        for slot in self.slots:
            if slot.horizon_minutes == horizon:
                return slot
        return None

    def as_canonical(self) -> dict[str, object]:
        """A identidade da trajetória — âncora, política e slots em ordem.

        O DIGESTO DA ÂNCORA ENTRA, e o da partida não: a trajetória é daquela
        LINHA, e duas versões do dataset com a mesma chave e conteúdos
        diferentes não são a mesma trajetória.

        CHAVE DE OBJETO, GRUPO DE LINHAS E ORDEM DE LEITURA FICAM DE FORA
        (§62): duas gravações do mesmo conteúdo são a mesma trajetória.
        """
        return {
            "algorithm": TRAJECTORY_FINGERPRINT_ALGORITHM,
            "anchor_key": self.anchor_key.text,
            "anchor_position": self.anchor_position.as_canonical(),
            "anchor_row_digest": self.anchor_row_digest,
            "competition": self.competition,
            "policy_fingerprint": self.policy_fingerprint,
            "slots": [slot.as_canonical() for slot in self.slots],
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def diagnostics(self) -> Mapping[str, object]:
        from sports_intelligence.domain.retrieval.trajectory_window import slot_counts

        return {
            "anchor": self.anchor_position.text,
            "available_horizons": self.available_horizon_count,
            "horizons": list(self.horizons),
            **slot_counts(self.slots),
        }

    def __str__(self) -> str:
        return (
            f"trajetória {self.anchor_key.text}@{self.anchor_position.text}: "
            f"{self.available_horizon_count}/{len(self.slots)} horizontes "
            f"[{self.fingerprint[:12]}]"
        )


def assemble_trajectory(
    *,
    policy: TrajectoryWindowPolicy,
    resolved: Sequence[ResolvedSlot],
    anchor_key: HistoricalFeatureSnapshotKey,
    match_key: str,
    competition: str,
    anchor_position: GridTimePoint,
    anchor_row_digest: str,
    rows: Mapping[GridTimePoint, TrajectoryRow],
) -> HistoricalTrajectory:
    """Monta a trajetória a partir dos slots resolvidos e das linhas lidas.

    A LINHA AUSENTE PARA A MONTAGEM. Se o slot é estruturalmente disponível — a
    grade declara aquele instante, dentro do mesmo período — e a linha não veio,
    isso é quebra de integridade e não ausência de feature (§30, §157).

    A ORDEM DAS LINHAS NÃO IMPORTA. Elas chegam indexadas por instante, e o
    instante é a identidade canônica: duas leituras que entreguem as mesmas
    linhas em ordens físicas diferentes montam a MESMA trajetória (§171).
    """
    slots: list[TrajectorySlot] = []
    for resolvido in resolved:
        if resolvido.target is None:
            slots.append(
                TrajectorySlot(
                    horizon_minutes=resolvido.horizon_minutes,
                    target=None,
                    status=resolvido.status,
                )
            )
            continue
        linha = rows.get(resolvido.target)
        if linha is None:
            raise TrajectorySourceRowMissingError(
                match_key=match_key,
                target=resolvido.target.text,
                anchor=f"{anchor_key.text}@{anchor_position.text}",
            )
        if linha.key.match_key != match_key:
            raise ValidationError(
                f"a linha de lookback {linha.key.text} é da partida "
                f"{linha.key.match_key} e a âncora é de {match_key}: a trajetória é o "
                "movimento DAQUELA partida, e cruzar partidas mediria outra coisa",
                context={"anchor_match": match_key, "row_match": linha.key.match_key},
            )
        slots.append(
            TrajectorySlot(
                horizon_minutes=resolvido.horizon_minutes,
                target=resolvido.target,
                status=SlotStatus.AVAILABLE,
                source_key=linha.key,
                source_row_digest=linha.row_digest,
            )
        )
    return HistoricalTrajectory(
        anchor_key=anchor_key,
        match_key=match_key,
        competition=competition,
        anchor_position=anchor_position,
        anchor_row_digest=anchor_row_digest,
        policy_fingerprint=policy.fingerprint,
        policy_identity=policy.identity,
        slots=tuple(slots),
    )


# ============================================== a representação ==


@final
@dataclass(frozen=True, slots=True)
class TrajectoryRepresentation:
    """Os deslocamentos, em ordem canônica de `(horizonte, eixo)`.

    A CÉLULA É `(horizonte, eixo)`, e a ordem é `horizonte` primeiro. Ela é a
    mesma na impressão, na máscara, na evidência e na serialização — e o
    tamanho é `n = |H| · m`, FIXO, mesmo quando um horizonte inteiro está fora
    do período.

    O DENOMINADOR NÃO ENCOLHE (§75, §76). Se o horizonte de cinco minutos sair
    do período, as `m` células dele ficam indisponíveis e CONTINUAM no
    denominador. Removê-las faria uma trajetória com um minuto de história
    parecer tão evidenciada quanto uma com cinco.
    """

    trajectory: HistoricalTrajectory
    feature_keys: tuple[str, ...]
    horizons: tuple[int, ...]
    profile_fingerprint: str
    #: `n` valores, em ordem `(horizonte, eixo)`. `None` onde a célula não é
    #: utilizável — e nunca zero, que seria um deslocamento inventado.
    displacements: tuple[float | None, ...] = ()
    mask: tuple[bool, ...] = ()

    def __post_init__(self) -> None:
        esperado = len(self.horizons) * len(self.feature_keys)
        if len(self.displacements) != esperado or len(self.mask) != esperado:
            raise ValidationError(
                f"representação com {len(self.displacements)} deslocamentos e "
                f"{len(self.mask)} posições de máscara contra {esperado} células "
                f"({len(self.horizons)} horizontes x {len(self.feature_keys)} eixos): "
                "ela descreveria outro espaço"
            )
        for indice, (valor, marcado) in enumerate(zip(self.displacements, self.mask, strict=True)):
            if marcado and (valor is None or not math.isfinite(valor)):
                raise ValidationError(
                    f"célula {indice} marcada como utilizável e sem deslocamento finito: {valor!r}"
                )
            if not marcado and valor is not None:
                raise ValidationError(
                    f"célula {indice} marcada como ausente e com deslocamento "
                    f"{valor!r}: um valor numa célula não utilizável é o convite para "
                    "alguém somá-lo assim mesmo"
                )

    # ------------------------------------------------------------ leitura --

    @property
    def cell_count(self) -> int:
        """`n = |H| · m`. FIXO — ver o cabeçalho da classe."""
        return len(self.mask)

    @property
    def usable_count(self) -> int:
        return sum(1 for bit in self.mask if bit)

    @property
    def axis_count(self) -> int:
        return len(self.feature_keys)

    @property
    def mask_text(self) -> str:
        return mask_text(self.mask)

    def index_of(self, horizon: int, axis: int) -> int:
        """A posição canônica da célula. HORIZONTE primeiro, eixo depois."""
        return self.horizons.index(horizon) * len(self.feature_keys) + axis

    def horizon_slice(self, horizon: int) -> slice:
        """As `m` posições daquele horizonte, para a evidência por horizonte."""
        inicio = self.horizons.index(horizon) * len(self.feature_keys)
        return slice(inicio, inicio + len(self.feature_keys))

    def usable_in(self, horizon: int) -> int:
        return sum(1 for bit in self.mask[self.horizon_slice(horizon)] if bit)

    def as_canonical(self) -> dict[str, object]:
        """A identidade da representação.

        ELA COBRE A TRAJETÓRIA INTEIRA por impressão — âncora, política e
        slots com os digestos das linhas de origem — e depois as células em
        ordem, cada uma com a disponibilidade e o deslocamento canônico.
        """
        return {
            "algorithm": REPRESENTATION_FINGERPRINT_ALGORITHM,
            "cells": [
                {
                    "available": marcado,
                    "displacement": None if valor is None else distance_text(valor),
                }
                for valor, marcado in zip(self.displacements, self.mask, strict=True)
            ],
            "feature_order": list(self.feature_keys),
            "horizon_order": list(self.horizons),
            "profile_fingerprint": self.profile_fingerprint,
            "representation": DISPLACEMENT_REPRESENTATION_V1,
            "trajectory": self.trajectory.as_canonical(),
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def diagnostics(self) -> Mapping[str, object]:
        return {
            "axis_count": self.axis_count,
            "cell_count": self.cell_count,
            "usable_count": self.usable_count,
            **{f"usable_{h}m": self.usable_in(h) for h in self.horizons},
        }

    def __str__(self) -> str:
        return (
            f"{self.trajectory.anchor_key.text}: {self.usable_count}/{self.cell_count} "
            f"células [{self.fingerprint[:12]}]"
        )


def build_representation(
    *,
    trajectory: HistoricalTrajectory,
    feature_keys: Sequence[str],
    horizons: Sequence[int],
    profile_fingerprint: str,
    anchor_values: Mapping[str, float | None],
    anchor_availabilities: Mapping[str, str],
    rows: Mapping[GridTimePoint, TrajectoryRow],
) -> TrajectoryRepresentation:
    """Os deslocamentos de todas as `|H| · m` células.

    OS DOIS EXTREMOS SÃO EXIGIDOS (§159). `Δ_{h,i}` existe quando o eixo `i`
    tem número finito NA ÂNCORA e em `t-h`. Um extremo só não produz meio
    deslocamento — e usar o valor da âncora no lugar do que falta fabricaria
    `Δ = 0`, que é estabilidade inventada e o blocker do §102.

    A MÁSCARA DA ÂNCORA É CALCULADA UMA VEZ, e não por horizonte: ela é a mesma
    para os três, e recalculá-la seria três oportunidades de divergir.
    """
    chaves = tuple(feature_keys)
    mascara_da_ancora = availability_mask(
        feature_keys=chaves,
        values=anchor_values,
        availabilities=anchor_availabilities,
        owner=f"a âncora {trajectory.anchor_key.text}",
    )
    deslocamentos: list[float | None] = []
    mascara: list[bool] = []
    for horizonte in horizons:
        slot = trajectory.slot_of(horizonte)
        linha = None
        if slot is not None and slot.is_available and slot.target is not None:
            linha = rows.get(slot.target)
        if linha is None:
            # O HORIZONTE INTEIRO SAI, e as `m` células dele continuam no
            # denominador — ver o cabeçalho de `TrajectoryRepresentation`.
            deslocamentos.extend([None] * len(chaves))
            mascara.extend([False] * len(chaves))
            continue
        mascara_do_slot = availability_mask(
            feature_keys=chaves,
            values=linha.values,
            availabilities=linha.availabilities,
            owner=f"a linha {linha.key.text}",
        )
        for indice, chave in enumerate(chaves):
            if not (mascara_da_ancora[indice] and mascara_do_slot[indice]):
                deslocamentos.append(None)
                mascara.append(False)
                continue
            atual = anchor_values[chave]
            passado = linha.values[chave]
            if atual is None or passado is None:  # pragma: no cover — a máscara garantiu
                raise ValidationError(f"eixo {chave!r} marcado e sem valor nos dois extremos")
            deslocamentos.append(atual - passado)
            mascara.append(True)
    return TrajectoryRepresentation(
        trajectory=trajectory,
        feature_keys=chaves,
        horizons=tuple(horizons),
        profile_fingerprint=profile_fingerprint,
        displacements=tuple(deslocamentos),
        mask=tuple(mascara),
    )
