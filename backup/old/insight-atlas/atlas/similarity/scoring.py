"""Quão boa é uma vizinhança, e sobre o quê.

O QUE MUDOU E POR QUÊ. Este módulo calculava um número chamado
`neighbor_agreement` que não era concordância nenhuma:

    1 - (maior distância - menor distância) / distância média

Isso mede se os K vizinhos estão todos IGUALMENTE longe do alvo. Não diz uma
palavra sobre eles terem terminado do mesmo jeito. E o detector de tendências
usava esse número como portão, sob a leitura que o nome sugere.

O número não estava errado por descuido: `SimilarityMatch` só carregava
similaridade e distância, então concordância sobre desfecho era literalmente
incalculável aqui. A forma limitou a métrica, e o nome escondeu a limitação.

MEDIDO CONTRA O CORPUS DE 15.627 PARTIDAS, o portão em 0,40 deixava passar:

    lente/competição                     passa    concordância real
    gols · brasileirao                    0,0%              50,4%
    gols · argentina_liga                 0,0%              48,0%
    resultado · premier_league            9,7%              60,0%
    desempenho_time · la_liga            29,7%              53,8%

Zero na lente `gols` de dois campeonatos inteiros. E a taxa de passagem não
tem relação com qualidade: `resultado` na Premier League é a lente mais forte
que existe (+12,7% sobre a taxa base) e passava em 9,7%.

AGORA `SimilarityMatch` CARREGA O DESFECHO, e a concordância é a fração dos
vizinhos que terminaram igual. `distance_uniformity` continua sendo calculada
— é uma medida real da forma da vizinhança — com o nome do que ela mede.
"""

from __future__ import annotations

from collections import Counter

from atlas.similarity.contracts import (
    SimilarityConfidence,
    SimilarityDistribution,
    SimilarityMatch,
)


def confidence_for_matches(
    matches: list[SimilarityMatch],
    *,
    minimum_neighbors: int,
) -> SimilarityConfidence:
    if not matches:
        return SimilarityConfidence(
            similarity_score=0.0,
            confidence=0.0,
            neighbor_count=0,
            minimum_neighbors=minimum_neighbors,
            average_distance=0.0,
            distance_spread=0.0,
            distance_uniformity=0.0,
            outcome_agreement=None,
            modal_outcome=None,
            reasons=["no vector neighbors met filters and similarity threshold"],
        )

    similarities = [item.similarity for item in matches]
    distances = [item.distance for item in matches]
    best_similarity = max(similarities)
    average_similarity = sum(similarities) / len(similarities)
    similarity_score = (0.6 * best_similarity) + (0.4 * average_similarity)

    average_distance = sum(distances) / len(distances)
    distance_spread = max(distances) - min(distances)
    distance_uniformity = 1.0 - min(
        1.0,
        distance_spread / max(average_distance, 1e-9),
    )

    # CONCORDÂNCIA DE VERDADE: quantos dos vizinhos terminaram do mesmo jeito.
    #
    # `None` quando os vizinhos não trazem desfecho, e não zero: zero diria
    # "eles discordam totalmente", que é uma afirmação sobre algo não medido.
    desfechos = [m.outcome for m in matches if m.outcome]
    if desfechos:
        contagem = Counter(desfechos)
        modal, quantos = contagem.most_common(1)[0]
        outcome_agreement: float | None = quantos / len(desfechos)
        modal_outcome: str | None = modal
    else:
        outcome_agreement = None
        modal_outcome = None

    coverage = min(1.0, len(matches) / minimum_neighbors)
    # A confiança usa a concordância REAL quando ela existe. Enquanto usava a
    # uniformidade de distância, ela subia quando os 25 vizinhos estavam
    # igualmente longe — uma propriedade da forma da vizinhança, não do que
    # ela diz.
    coerencia = outcome_agreement if outcome_agreement is not None else distance_uniformity
    confidence = min(
        0.99,
        similarity_score * (0.50 + 0.25 * coerencia + 0.25 * coverage),
    )

    reasons = []
    if len(matches) < minimum_neighbors:
        reasons.append("fewer neighbors than minimum_neighbors")
    if outcome_agreement is None:
        reasons.append("vizinhos sem desfecho: concordância não medida")

    return SimilarityConfidence(
        similarity_score=round(similarity_score, 6),
        confidence=round(confidence, 6),
        neighbor_count=len(matches),
        minimum_neighbors=minimum_neighbors,
        average_distance=round(average_distance, 6),
        distance_spread=round(distance_spread, 6),
        distance_uniformity=round(distance_uniformity, 6),
        outcome_agreement=(
            round(outcome_agreement, 6) if outcome_agreement is not None else None
        ),
        modal_outcome=modal_outcome,
        reasons=reasons,
    )


def coverage_for_matches(matches: list[SimilarityMatch], *, minimum_neighbors: int) -> float:
    if minimum_neighbors <= 0:
        return 1.0 if matches else 0.0
    return round(min(1.0, len(matches) / minimum_neighbors), 6)


def distribution_for_matches(matches: list[SimilarityMatch]) -> SimilarityDistribution:
    """Deterministic neighbourhood shape — pure summary statistics, no ML."""
    if not matches:
        return SimilarityDistribution(
            count=0,
            best_similarity=0.0,
            worst_similarity=0.0,
            mean_similarity=0.0,
            min_distance=0.0,
            max_distance=0.0,
            mean_distance=0.0,
            distance_spread=0.0,
        )
    sims = [m.similarity for m in matches]
    dists = [m.distance for m in matches]
    return SimilarityDistribution(
        count=len(matches),
        best_similarity=round(max(sims), 6),
        worst_similarity=round(min(sims), 6),
        mean_similarity=round(sum(sims) / len(sims), 6),
        min_distance=round(min(dists), 6),
        max_distance=round(max(dists), 6),
        mean_distance=round(sum(dists) / len(dists), 6),
        distance_spread=round(max(dists) - min(dists), 6),
    )
