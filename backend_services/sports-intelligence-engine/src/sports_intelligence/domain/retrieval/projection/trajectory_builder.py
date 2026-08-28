"""A projeção de uma trajetória do PR-06.3 em linha indexada.

ELE NÃO RECONSTRÓI TRAJETÓRIA NENHUMA (§17). A janela, os slots, o mesmo
período e os deslocamentos saem de `assemble_trajectory` e `build_representation`
— as funções que o PR-06.3 fechou. Este módulo só TRADUZ o resultado delas para
o formato do índice.

    reimplementar `t-1`, `t-3`, `t-5` em SQL seria criar uma segunda
    definição de causalidade, e a segunda seria a que ninguém testou

O DETALHE QUE DECIDE O ESQUEMA: a representação do PR-06.3 é construída sobre o
perfil RESOLVIDO da competição — quinze eixos na Premier League do corpus. O
índice, porém, tem uma coluna `vector(174)` fixa, que é `2 . 3 . 29` sobre os
eixos CANÔNICOS do plano.

A saída não é escolher um dos dois: é construir a representação indexada sobre
os vinte e nove canônicos e deixar a máscara dizer quais existem naquela
competição. Um eixo sem artefato ajustado chega com disponibilidade diferente de
`AVAILABLE`, vira máscara zero, e é exatamente isso que ele é ali.

E O RERANK CONTINUA USANDO O PERFIL RESOLVIDO. Ao ler o payload, o domínio
seleciona o subconjunto de células que o perfil daquela competição declara — e
mede a distância sobre elas, como o PR-06.3 sempre fez. O índice guarda o espaço
inteiro; a pergunta continua sendo feita sobre a parte que a competição tem.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import final

from sports_intelligence.domain.retrieval.projection.builder import IndexRowRejection
from sports_intelligence.domain.retrieval.projection.payload import ExactTrajectoryPayload
from sports_intelligence.domain.retrieval.projection.spec import ProjectionAxisSpec
from sports_intelligence.domain.retrieval.timepoint import (
    GRID_SEQUENCE,
    GRID_STOPPAGE,
    GridTimePoint,
)
from sports_intelligence.domain.retrieval.trajectory import TrajectoryRepresentation
from sports_intelligence.domain.shared.errors import ValidationError


@final
@dataclass(frozen=True, slots=True)
class TrajectoryIndexRow:
    """Uma linha pronta para o índice de trajetória."""

    semantic_key: str
    anchor_key: str
    match_id: str
    competition: str
    season: str
    period: str
    minute: int
    stoppage: int
    tie_break: str
    payload: ExactTrajectoryPayload
    usable_horizons: int
    #: A linhagem dos slots — o que prova DE ONDE cada deslocamento veio.
    slot_lineage: tuple[dict[str, object], ...] = ()

    @property
    def usable_cells(self) -> int:
        return self.payload.usable_count

    def content_entry(self) -> tuple[str, str]:
        return (self.semantic_key, self.payload.digest)


def trajectory_semantic_key(*, anchor_key: str, trajectory_fingerprint: str) -> str:
    """Âncora MAIS identidade da representação (§53 do gate anterior).

    A ÂNCORA SOZINHA NÃO BASTA. Duas trajetórias sobre o mesmo instante com
    janelas diferentes alcançam instantes diferentes e medem outros intervalos;
    se as duas dividissem a chave, a segunda sobrescreveria a primeira e o
    índice guardaria movimento de uma política sob o nome de outra.

    O RECORTE DA IMPRESSÃO É DELIBERADO. Dezesseis dígitos hexadecimais são
    sessenta e quatro bits: o bastante para que uma colisão entre duas
    trajetórias da MESMA âncora seja irrelevante na prática, e curto o bastante
    para a chave continuar legível num relatório.
    """
    return f"{anchor_key}#{trajectory_fingerprint[:16]}"


def _horizontes_utilizaveis(
    representation: TrajectoryRepresentation,
) -> int:
    """Quantos horizontes têm PELO MENOS um eixo utilizável.

    ELE É O SEGUNDO PREFILTRO SEGURO (§87 do gate anterior), e por isso conta
    horizontes ALCANÇADOS e não horizontes evidenciais: o piso de evidência
    depende do perfil resolvido da query, que o índice não conhece. Contar
    «alcançou» é a condição necessária que vale para qualquer query — quem não
    alcança dois não compartilha dois com ninguém.
    """
    eixos = len(representation.feature_keys)
    alcancados = 0
    for bloco in range(len(representation.horizons)):
        inicio = bloco * eixos
        if any(representation.mask[inicio : inicio + eixos]):
            alcancados += 1
    return alcancados


def build_trajectory_row(
    representation: TrajectoryRepresentation,
    *,
    spec: ProjectionAxisSpec,
    match_id: str,
    competition: str,
    season: str,
    anchor_position: GridTimePoint,
) -> TrajectoryIndexRow | IndexRowRejection:
    """A representação do PR-06.3 vira linha indexada — ou motivo de recusa.

    A REPRESENTAÇÃO PRECISA ESTAR SOBRE OS EIXOS CANÔNICOS. Se ela vier sobre o
    perfil resolvido, as posições do vetor significariam eixos diferentes por
    competição — e o mesmo `vector(174)` guardaria espaços distintos sob a mesma
    coluna. A conferência é explícita porque o erro seria silencioso.
    """
    if tuple(representation.feature_keys) != spec.axis_keys:
        raise ValidationError(
            f"a representação tem {len(representation.feature_keys)} eixos e a projeção "
            f"tem {spec.axis_count} canônicos. O índice guarda o espaço INTEIRO do "
            "plano e deixa a máscara dizer o que a competição tem; uma representação "
            "sobre outro conjunto de eixos poria significados diferentes nas mesmas "
            "posições do vetor"
        )
    if tuple(representation.horizons) != spec.horizons:
        raise ValidationError(
            f"horizontes {representation.horizons} contra {spec.horizons} da projeção"
        )

    if not any(representation.mask):
        return IndexRowRejection.NO_USABLE_AXIS

    deslocamentos: dict[tuple[int, str], float | None] = {}
    usaveis: dict[tuple[int, str], bool] = {}
    ordem: list[tuple[int, str]] = []
    posicao = 0
    for horizonte in spec.horizons:
        for chave in spec.axis_keys:
            celula = (horizonte, chave)
            ordem.append(celula)
            marcado = representation.mask[posicao]
            usaveis[celula] = marcado
            deslocamentos[celula] = representation.displacements[posicao] if marcado else None
            posicao += 1

    celulas = [deslocamentos[c] for c in ordem]
    mascara = [usaveis[c] for c in ordem]
    payload = ExactTrajectoryPayload(
        axis_keys=spec.axis_keys,
        horizons=spec.horizons,
        displacements=tuple(0.0 if v is None else v for v in celulas),
        mask=tuple(mascara),
        anchor_row_digest=representation.trajectory.anchor_row_digest,
        trajectory_fingerprint=representation.trajectory.fingerprint,
        representation_fingerprint=representation.fingerprint,
    )
    chave_da_ancora = representation.trajectory.anchor_key.text
    return TrajectoryIndexRow(
        semantic_key=trajectory_semantic_key(
            anchor_key=chave_da_ancora,
            trajectory_fingerprint=representation.trajectory.fingerprint,
        ),
        anchor_key=chave_da_ancora,
        match_id=match_id,
        competition=competition,
        season=season,
        period=anchor_position.period.value,
        minute=anchor_position.minute,
        stoppage=GRID_STOPPAGE,
        tie_break=str(GRID_SEQUENCE),
        payload=payload,
        usable_horizons=_horizontes_utilizaveis(representation),
        slot_lineage=tuple(
            {
                "horizon_minutes": slot.horizon_minutes,
                "status": slot.status.value,
                "target_period": None if slot.target is None else slot.target.period.value,
                "target_minute": None if slot.target is None else slot.target.minute,
                "source_key": None if slot.source_key is None else slot.source_key.text,
                "source_row_digest": slot.source_row_digest,
            }
            for slot in representation.trajectory.slots
        ),
    )


def trajectory_rows_to_records(
    rows: Sequence[TrajectoryIndexRow],
) -> list[dict[str, object]]:
    registros: list[dict[str, object]] = []
    for linha in rows:
        valores, mascara = linha.payload.encode()
        registros.append(
            {
                "semantic_key": linha.semantic_key,
                "anchor_key": linha.anchor_key,
                "competition": linha.competition,
                "season": linha.season,
                "match_id": linha.match_id,
                "period": linha.period,
                "minute": linha.minute,
                "stoppage": linha.stoppage,
                "tie_break": linha.tie_break,
                "usable_cells": linha.usable_cells,
                "usable_horizons": linha.usable_horizons,
                "exact_values": valores,
                "exact_mask": mascara,
                "exact_payload_digest": linha.payload.digest,
                "anchor_row_digest": linha.payload.anchor_row_digest,
                "trajectory_fingerprint": linha.payload.trajectory_fingerprint,
                "representation_fingerprint": linha.payload.representation_fingerprint,
                "slot_lineage": list(linha.slot_lineage),
            }
        )
    return registros


def restrict_to_profile(
    payload: ExactTrajectoryPayload,
    *,
    feature_keys: Sequence[str],
) -> tuple[tuple[float | None, ...], tuple[bool, ...]]:
    """As células do payload canônico RESTRITAS ao perfil resolvido da query.

    É AQUI QUE O ÍNDICE VOLTA A SER O PR-06.3. O payload guarda os vinte e nove
    eixos do plano; a distância é medida sobre os eixos que a competição
    resolveu — quinze, no corpus real. Selecionar o subconjunto na ORDEM do
    perfil é o que faz a representação reconstruída ser idêntica à que o oráculo
    montaria lendo o Parquet.

    UM EIXO DO PERFIL AUSENTE DO PAYLOAD É ERRO, e não ausência: o perfil sai do
    mesmo plano que define os eixos canônicos, logo pedir um eixo que o payload
    não tem significa que os dois vieram de planos diferentes.
    """
    por_celula = payload.displacements_by_cell()
    posicoes: list[float | None] = []
    mascara: list[bool] = []
    conhecidos = set(payload.axis_keys)
    for chave in feature_keys:
        if chave not in conhecidos:
            raise ValidationError(
                f"o perfil pede o eixo {chave} e o payload indexado não o tem: os "
                "dois vieram de planos de normalização diferentes"
            )
    for horizonte in payload.horizons:
        for chave in feature_keys:
            valor = por_celula[(horizonte, chave)]
            posicoes.append(valor)
            mascara.append(valor is not None)
    return tuple(posicoes), tuple(mascara)
