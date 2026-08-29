"""Os adaptadores de estado e trajetória — e a separação que eles preservam.

O NÚCLEO É COMPARTILHADO, e o que muda aqui é só o que tem de mudar:

    de onde sai a dissimilaridade
    que evidência acompanha o vizinho
    como essa evidência é resumida

A ARITMÉTICA NÃO SE DUPLICA. `normalized_weights` e `effective_sample_size` são
as mesmas funções nos dois caminhos; se houvesse uma cópia por tipo, a primeira
correção aplicada a só uma delas passaria despercebida.

## A regra que este módulo existe para não quebrar

    a DISTÂNCIA decide o peso
    a EVIDÊNCIA descreve o suporte

    e o resumo de evidência NUNCA volta ao peso

A distância exata do PR-06.2 já cobra `p = 1` por eixo ausente; a do PR-06.3
cobra por célula ausente. Multiplicar o peso pela cobertura cobraria a mesma
ausência uma segunda vez, e o vizinho incompleto seria punido em dobro — uma vez
dentro do número, outra fora dele.

Por isso os resumos abaixo são calculados COM os pesos (são médias ponderadas,
para descrever o conjunto que de fato influencia) e nunca entram no cálculo
deles. A direção é uma só: peso -> resumo.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sports_intelligence.domain.retrieval.aggregation.aggregate import (
    NeighborAggregation,
    aggregate,
)
from sports_intelligence.domain.retrieval.aggregation.kernel import weighted_mean
from sports_intelligence.domain.retrieval.aggregation.policy import (
    DistanceWeightingPolicy,
    RetrievalKind,
)


def _pesos_provisorios(
    distances: Sequence[float], policy: DistanceWeightingPolicy
) -> tuple[float, ...]:
    """Os pesos, calculados uma vez para servir aos resumos ponderados.

    ELES SÃO OS MESMOS do agregado final — a função é determinística sobre as
    mesmas distâncias e a mesma política. Recalculá-los aqui evita montar o
    agregado duas vezes só para ter os pesos antes do resumo.
    """
    from sports_intelligence.domain.retrieval.aggregation.kernel import (
        normalized_weights,
        uniform_weights,
    )

    if not distances:
        return ()
    if policy.is_uniform:
        return uniform_weights(len(distances))
    return normalized_weights(distances, lam=policy.lam)


def _media_renormalizada(valores: Sequence[float], pesos: Sequence[float]) -> float | None:
    """A média ponderada sobre um SUBCONJUNTO, com os pesos renormalizados.

    QUANDO SÓ PARTE DOS VIZINHOS TEM O VALOR, os pesos deles não somam um. Usar
    a soma parcial como denominador implícito daria uma média puxada para baixo
    por vizinhos que nem entraram na conta; renormalizar responde à pergunta
    certa — «entre os que têm parcela, qual é a média ponderada?».
    """
    import math

    if not valores:
        return None
    total = math.fsum(pesos)
    if total <= 0.0:
        return None
    return math.fsum(v * p for v, p in zip(valores, pesos, strict=True)) / total


def aggregate_state(
    result: Any,
    *,
    policy: DistanceWeightingPolicy,
    query_identity: str,
    requested_k: int,
) -> NeighborAggregation:
    """O agregado de ESTADO, a partir do resultado exato do PR-06.2.

    A ENTRADA É O RESULTADO JÁ VALIDADO, e nada é recalculado: as
    dissimilaridades vêm de `neighbor.dissimilarity`, que é a única distância
    que este PR pode consumir.
    """
    vizinhos = list(result.neighbors)
    distancias = [float(v.dissimilarity) for v in vizinhos]
    pesos = _pesos_provisorios(distancias, policy)

    resumo: Mapping[str, object] = {}
    if vizinhos:
        compartilhados = [float(v.evidence.coverage.shared_count) for v in vizinhos]
        eixos = float(vizinhos[0].evidence.coverage.profile_axis_count)
        fracoes = [c / eixos for c in compartilhados] if eixos > 0 else []
        # O PAR (parcela, peso) É MONTADO JUNTO, e não fatiado depois.
        #
        # `penalty_share` é `None` quando o par não compartilhou eixo nenhum, e
        # esses vizinhos precisam sair da média COM o peso deles. Filtrar só a
        # lista de parcelas e depois cortar os pesos pelo comprimento pegaria os
        # PRIMEIROS n pesos — que são de outros vizinhos — e a média sairia
        # plausível sobre pares que não se correspondem.
        com_parcela = [
            (float(v.evidence.penalty_share), peso)
            for v, peso in zip(vizinhos, pesos, strict=True)
            if v.evidence.penalty_share is not None
        ]
        parcelas = [valor for valor, _ in com_parcela]
        pesos_das_parcelas = [peso for _, peso in com_parcela]
        resumo = {
            "profile_axis_count": int(eixos),
            "minimum_shared_axes": int(min(compartilhados)),
            "maximum_shared_axes": int(max(compartilhados)),
            "weighted_shared_axes": weighted_mean(compartilhados, pesos),
            "weighted_shared_ratio": weighted_mean(fracoes, pesos) if fracoes else None,
            # A PARCELA INCERTA É DESCRITIVA. Ela já está DENTRO da distância —
            # é a penalidade por ausência —, e aparece aqui só para que se possa
            # ler quanto do número veio de incerteza em vez de discrepância.
            # A média é RENORMALIZADA sobre os pares que têm parcela: sem
            # isso ela somaria a menos de um e pareceria menor do que é.
            "weighted_penalty_share": _media_renormalizada(parcelas, pesos_das_parcelas),
        }

    return aggregate(
        query_identity=query_identity,
        kind=RetrievalKind.STATE,
        policy=policy,
        requested_k=requested_k,
        neighbors=[
            (v.key.text, v.rank, float(v.dissimilarity), v.evidence.fingerprint) for v in vizinhos
        ],
        retrieval_fingerprint=getattr(result, "fingerprint", ""),
        evidence_summary=resumo,
    )


def aggregate_trajectory(
    result: Any,
    *,
    policy: DistanceWeightingPolicy,
    query_identity: str,
    requested_k: int,
) -> NeighborAggregation:
    """O agregado de TRAJETÓRIA, a partir do resultado exato do PR-06.3.

    O RESUMO POR HORIZONTE É O QUE A TRAJETÓRIA TEM DE PRÓPRIO. Dois conjuntos
    com o mesmo `D_T` médio podem ter vindo de horizontes diferentes — um de
    `1m`, outro de `5m` —, e essa diferença é sobre QUANDO a comparação se
    sustenta. Ela é descritiva, como todo o resto deste módulo.
    """
    vizinhos = list(result.neighbors)
    distancias = [float(v.trajectory_dissimilarity) for v in vizinhos]
    pesos = _pesos_provisorios(distancias, policy)

    resumo: Mapping[str, object] = {}
    if vizinhos:
        celulas = [float(v.shared_cells) for v in vizinhos]
        horizontes = [float(v.shared_horizons) for v in vizinhos]
        espaco = float(vizinhos[0].evidence.coverage.cell_count)
        fracoes = [c / espaco for c in celulas] if espaco > 0 else []
        por_horizonte: dict[str, object] = {}
        for minutos in (1, 3, 5):
            eixos_do_horizonte = [
                float(
                    next(
                        (
                            c.shared_axes
                            for c in v.evidence.breakdown.horizons
                            if c.horizon_minutes == minutos
                        ),
                        0,
                    )
                )
                for v in vizinhos
            ]
            por_horizonte[f"{minutos}m_weighted_shared_axes"] = weighted_mean(
                eixos_do_horizonte, pesos
            )
        resumo = {
            "cell_count": int(espaco),
            "minimum_shared_cells": int(min(celulas)),
            "maximum_shared_cells": int(max(celulas)),
            "weighted_shared_cells": weighted_mean(celulas, pesos),
            "weighted_shared_ratio": weighted_mean(fracoes, pesos) if fracoes else None,
            "weighted_shared_horizons": weighted_mean(horizontes, pesos),
            **por_horizonte,
        }

    return aggregate(
        query_identity=query_identity,
        kind=RetrievalKind.TRAJECTORY,
        policy=policy,
        requested_k=requested_k,
        neighbors=[
            (
                v.anchor_key.text,
                v.rank,
                float(v.trajectory_dissimilarity),
                v.evidence.fingerprint,
            )
            for v in vizinhos
        ],
        retrieval_fingerprint=getattr(result, "fingerprint", ""),
        evidence_summary=resumo,
    )
