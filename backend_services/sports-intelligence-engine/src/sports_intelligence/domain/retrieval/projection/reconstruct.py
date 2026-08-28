"""Do payload indexado de volta ao objeto de domínio — sem inventar nada.

ESTE É O MÓDULO QUE FAZ O PR-06.4 NÃO PRECISAR DE UMA SEGUNDA MATEMÁTICA (§35).
Ele devolve `CandidateRow` e `TrajectoryCandidate` — exatamente os tipos que
`AvailabilityAwareHistoricalRetriever` e `ExactTrajectoryRetriever` já consomem
— e a partir daí o caminho indexado É o caminho exato, rodando as mesmas
funções sobre os mesmos `float64`.

    lista curta do ANN
        -> payloads exatos
        -> reconstrução (aqui)
        -> retriever EXATO já existente
        -> top-K

A ALTERNATIVA SERIA ESCREVER «a mesma» distância dentro do adapter, e ela é a
armadilha do PR: duas implementações da mesma fórmula concordam no dia em que
são escritas e divergem na primeira correção que só uma delas recebe.

A MÁSCARA VOLTA A SER DISPONIBILIDADE. O payload guarda `bytes`, que não têm
buraco; o domínio fala em `AVAILABLE` e ausência. A tradução é a mesma nos dois
sentidos, e o motivo de indisponibilidade que ela devolve é declaradamente
sintético — o índice não guarda POR QUE um eixo faltou, e forjar uma causa
específica seria mentir sobre a origem.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.normalized.rows import NormalizationAvailability
from sports_intelligence.domain.retrieval.candidate import CandidateRow
from sports_intelligence.domain.retrieval.projection.payload import (
    ExactStatePayload,
    ExactTrajectoryPayload,
)
from sports_intelligence.domain.retrieval.projection.trajectory_builder import restrict_to_profile
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from sports_intelligence.domain.retrieval.trajectory import (
    HistoricalTrajectory,
    TrajectoryRepresentation,
)
from sports_intelligence.domain.retrieval.trajectory_exact import TrajectoryCandidate
from sports_intelligence.domain.shared.errors import ValidationError

#: O motivo que a reconstrução atribui a um eixo ausente.
#:
#: ELE É SINTÉTICO, E ISSO ESTÁ DITO. O índice guarda que o eixo não estava
#: disponível, e não qual dos quatro motivos do catálogo causou a ausência —
#: essa informação vive no dataset normalizado. Escolher um motivo específico
#: aqui faria o caminho indexado AFIRMAR uma causa que ele não conhece; o que a
#: recuperação precisa saber é apenas que o eixo não conta, e todos os quatro
#: motivos produzem a mesma máscara.
AUSENTE_NO_INDICE: Final[str] = NormalizationAvailability.SOURCE_VALUE_UNAVAILABLE.value


def _disponibilidades(axis_keys: Sequence[str], mask: Sequence[bool]) -> dict[str, str]:
    return {
        chave: (NormalizationAvailability.AVAILABLE.value if marcado else AUSENTE_NO_INDICE)
        for chave, marcado in zip(axis_keys, mask, strict=True)
    }


def candidate_row_from_payload(
    payload: ExactStatePayload,
    *,
    feature_keys: Sequence[str],
    match_id: str,
    competition: str,
    season: str,
    position: GridTimePoint,
    semantic_key: str,
) -> CandidateRow:
    """O payload vira o MESMO `CandidateRow` que o Parquet produziria.

    O RECORTE PARA O PERFIL ACONTECE AQUI. O payload guarda os vinte e nove
    eixos canônicos do plano; `feature_keys` é o perfil RESOLVIDO da competição,
    que costuma ser menor. Entregar ao retriever um candidato com eixos que o
    perfil não declara não mudaria a distância — ele lê pelo perfil —, mas
    tornaria a comparação com o oráculo uma comparação entre objetos diferentes,
    e o harness de concordância ficaria mais fraco sem necessidade.
    """
    valores_canonicos = payload.values_by_key()
    disponiveis = _disponibilidades(payload.axis_keys, payload.mask)
    faltando = [c for c in feature_keys if c not in valores_canonicos]
    if faltando:
        raise ValidationError(
            f"o perfil pede os eixos {faltando} e o payload indexado não os tem: os "
            "dois vieram de planos de normalização diferentes, e a distância sairia "
            "sobre dimensões que não se correspondem",
            context={"missing": faltando},
        )
    return CandidateRow(
        key=_chave_de(semantic_key),
        split=DatasetSplit.REFERENCE,
        match_id=match_id,
        competition=competition,
        season=season,
        position=position,
        row_digest=payload.row_digest,
        representation_fingerprint=payload.representation_fingerprint,
        values={chave: valores_canonicos[chave] for chave in feature_keys},
        availabilities={chave: disponiveis[chave] for chave in feature_keys},
    )


def _chave_de(semantic_key: str) -> HistoricalFeatureSnapshotKey:
    """A chave semântica de volta ao tipo do domínio.

    O FORMATO É `{match_key}#{grid_index:04d}` — o `text` da própria chave. Ele
    é reconstruído AQUI, e não por um `parse` acrescentado ao tipo do PR-06.1:
    aquele contrato está congelado, e um método novo nele, ainda que aditivo,
    é código que o PR-06.4 passaria a dever a um PR fechado.

    `rsplit` COM LIMITE UM, e não `split`. O `match_key` pode conter `#`; o
    índice da grade, não — ele são quatro dígitos no fim. Partir pela ÚLTIMA
    ocorrência é o que torna a leitura correta para os dois casos.
    """
    if "#" not in semantic_key:
        raise ValidationError(
            f"chave semântica {semantic_key!r} sem separador: ela não veio de "
            "`HistoricalFeatureSnapshotKey.text`"
        )
    match_key, _, indice = semantic_key.rpartition("#")
    if not indice.isdigit():
        raise ValidationError(f"chave semântica {semantic_key!r} com índice de grade não numérico")
    return HistoricalFeatureSnapshotKey(match_key=match_key, grid_index=int(indice))


def trajectory_representation_from_payload(
    payload: ExactTrajectoryPayload,
    *,
    trajectory: HistoricalTrajectory,
    feature_keys: Sequence[str],
    profile_fingerprint: str,
) -> TrajectoryRepresentation:
    """O payload vira a MESMA `TrajectoryRepresentation` do PR-06.3.

    A TRAJETÓRIA EM SI VEM DE FORA. Ela é a âncora e os slots — a linhagem que
    prova que o lookback não atravessou o intervalo —, e o índice guarda a
    IMPRESSÃO dela, não a estrutura. Quem reconstrói a estrutura é o caminho
    normal do PR-06.3; o que este módulo devolve são os DESLOCAMENTOS, que é o
    que o payload realmente carrega.
    """
    deslocamentos, mascara = restrict_to_profile(payload, feature_keys=feature_keys)
    return TrajectoryRepresentation(
        trajectory=trajectory,
        feature_keys=tuple(feature_keys),
        horizons=payload.horizons,
        profile_fingerprint=profile_fingerprint,
        displacements=deslocamentos,
        mask=mascara,
    )


def trajectory_candidate_from_payload(
    payload: ExactTrajectoryPayload,
    *,
    trajectory: HistoricalTrajectory,
    feature_keys: Sequence[str],
    profile_fingerprint: str,
    match_id: str,
    season: str,
    representation_fingerprint: str,
) -> TrajectoryCandidate:
    return TrajectoryCandidate(
        match_id=match_id,
        season=season,
        representation_fingerprint=representation_fingerprint,
        representation=trajectory_representation_from_payload(
            payload,
            trajectory=trajectory,
            feature_keys=feature_keys,
            profile_fingerprint=profile_fingerprint,
        ),
    )


def payload_matches_row(payload: ExactStatePayload, row: CandidateRow) -> bool:
    """Se o payload reconstrói AQUELA linha, bit a bit, nos eixos que ele cobre.

    ELA É O CORAÇÃO DO HARNESS DE CONCORDÂNCIA (§14, §21). A comparação é de
    igualdade EXATA de `float64` — sem tolerância — porque a promessa do PR é
    que o índice reproduz a origem, e não que ele chega perto. Uma tolerância
    aqui esconderia justamente o defeito que a asserção procura.
    """
    valores = payload.values_by_key()
    disponiveis = _disponibilidades(payload.axis_keys, payload.mask)
    for chave in payload.axis_keys:
        do_indice = valores[chave]
        da_origem = row.values.get(chave)
        disponivel_na_origem = (
            row.availabilities.get(chave) == NormalizationAvailability.AVAILABLE.value
        )
        if disponivel_na_origem != (disponiveis[chave] == "AVAILABLE"):
            return False
        if disponivel_na_origem:
            if do_indice is None or da_origem is None or do_indice != da_origem:
                return False
        elif do_indice is not None:
            return False
    return payload.row_digest == row.row_digest


def agreement_report(*, compared: int, disagreements: Sequence[str]) -> Mapping[str, object]:
    """O relatório do harness — e ele exige CEM POR CENTO.

    NÃO HÁ «QUASE» AQUI. Uma única discordância significa que existem duas
    verdades sobre o mesmo candidato, e o §21 classifica isso como blocker de
    implementação e não como aproximação de ANN — porque não é: o ANN escolhe
    QUEM medir, e este número é sobre COMO se mede.
    """
    return {
        "agreement_rate": 1.0 if not compared else (compared - len(disagreements)) / compared,
        "compared": compared,
        "disagreements": list(disagreements[:20]),
        "disagreement_count": len(disagreements),
        "passed": not disagreements,
    }


def trajectory_from_lineage(
    *,
    anchor_key: HistoricalFeatureSnapshotKey,
    match_key: str,
    competition: str,
    anchor_position: GridTimePoint,
    anchor_row_digest: str,
    policy_fingerprint: str,
    policy_identity: str,
    slot_lineage: Sequence[Any],
) -> HistoricalTrajectory:
    """A trajetória reconstruída da LINHAGEM guardada na projeção.

    ELA NÃO É REMONTADA A PARTIR DAS LINHAS. `assemble_trajectory` precisa das
    linhas de lookback, e a projeção não as guarda — ela guarda o que aquelas
    linhas PROVAVAM: qual instante cada slot alcançou, e com que digesto.

    E É ISSO QUE A IMPRESSÃO COBRE. A impressão da trajetória é feita sobre a
    âncora, a política e o digesto de cada slot; reconstruí-los é o bastante
    para que a impressão reconstruída seja IGUAL à do oráculo — que é o que o
    gate de concordância mede.
    """
    from sports_intelligence.domain.retrieval.trajectory import TrajectorySlot
    from sports_intelligence.domain.retrieval.trajectory_window import SlotStatus

    slots: list[TrajectorySlot] = []
    for bruto in slot_lineage:
        dados = dict(bruto)
        periodo = dados.get("target_period")
        minuto = dados.get("target_minute")
        alvo = (
            None
            if periodo is None or minuto is None
            else GridTimePoint.from_columns(period=str(periodo), minute=int(minuto))
        )
        chave = dados.get("source_key")
        slots.append(
            TrajectorySlot(
                horizon_minutes=int(dados["horizon_minutes"]),
                target=alvo,
                status=SlotStatus(dados["status"]),
                source_key=None if chave is None else _chave_de(str(chave)),
                source_row_digest=dados.get("source_row_digest"),
            )
        )
    return HistoricalTrajectory(
        anchor_key=anchor_key,
        match_key=match_key,
        competition=competition,
        anchor_position=anchor_position,
        anchor_row_digest=anchor_row_digest,
        policy_fingerprint=policy_fingerprint,
        policy_identity=policy_identity,
        slots=tuple(slots),
    )
