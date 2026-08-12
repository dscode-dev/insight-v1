"""Oracle — online pgvector similarity detector (ATLAS-VECTOR-B).

Activates the two historical trend types that were reserved in the taxonomy:

  * ``historical_similarity`` — this developing match resembles a coherent set
    of prior matches (nearest vectors passed every gate).
  * ``historical_pattern``    — the resemblance is not only close but *tight*
    (dense, high-agreement neighbourhood), i.e. a recurring pattern.

The detector is a PURE, SYNCHRONOUS consumer of a precomputed
``SimilarityContext`` attached to ``TrendInputs.similarity`` by
``TrendIntelligencePipeline`` (the async pgvector query runs there, not here).
It never talks to a database, never uses an in-memory index, and never falls
back to a degraded guess: if any gate fails it emits nothing.

``HistoricalDeviationDetector`` (atlas/trends/oracle.py) is unchanged and keeps
running alongside this detector in the same historical engine.
"""

from __future__ import annotations

from atlas.similarity.contracts import (
    SimilarityConfidence,
    SimilarityContext,
    SimilarityMatch,
)
from atlas.similarity.scoring import confidence_for_matches
from atlas.trends.models import Trend, TrendCategory, TrendInputs, TrendType


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class OracleSimilarityDetector:
    """Emit historical similarity/pattern trends from online pgvector search.

    O PORTÃO QUE MUDOU, E POR QUÊ. Até aqui um dos portões era
    `neighbor_agreement >= 0,40`, sob a leitura de que os vizinhos concordavam
    entre si. Aquele número media 1 - amplitude/média das DISTÂNCIAS: se os K
    vizinhos estavam todos igualmente longe. Num top-K ordenado por distância
    o leque é garantido, então o portão recusava quase tudo — medido sobre o
    corpus, passava 0,0% na lente `gols` do Brasileirão e da Argentina, e
    9,7% em `resultado` na Premier League, que é a lente mais forte que
    existe.

    Agora o portão é CONCORDÂNCIA DE DESFECHO CONTRA A TAXA BASE. Uma
    vizinhança em que 50% dos jogos terminaram em vitória do mandante não diz
    nada num campeonato onde 48% de TODOS os jogos terminam assim. O que
    conta é a diferença, e é a mesma régua com que cada lente é validada.

    Portões determinísticos — uma tendência sai só quando TODOS passam:
      * minimum_similarity   — melhor vizinho ≥ o limiar da consulta
      * minimum_neighbors    — quantidade de vizinhos ≥ o mínimo
      * concordância         — os vizinhos terminaram do mesmo jeito ACIMA da
                               taxa base da competição, com folga
      * versões compatíveis  — todo vizinho compartilha embedding + schema
      * domínio compatível   — competição / temporada / mercado / fase, quando
                               a consulta os declarou

    Os portões `pattern_*` são estritamente mais apertados, então
    `historical_pattern` é condição superset de `historical_similarity`.
    """

    def __init__(
        self,
        *,
        margem_sobre_a_base: float = 0.05,
        pattern_min_neighbors: int = 5,
        margem_de_padrao: float = 0.15,
        top_neighbors: int = 5,
        taxa_base_padrao: float = 0.45,
    ) -> None:
        #: Quanto a concordância precisa superar a taxa base da competição.
        #:
        #: 0,05 e não zero: a concordância é medida sobre 25 vizinhos, e a
        #: variação amostral sozinha move essa fração em alguns pontos. Cinco
        #: pontos é a folga que separa "acima da base" de "empatado com ela".
        self._margem = margem_sobre_a_base
        self._pattern_min_neighbors = pattern_min_neighbors
        #: Padrão é uma afirmação mais forte, então exige folga maior.
        self._margem_padrao = margem_de_padrao
        self._top_neighbors = top_neighbors
        #: Usada só quando a competição não tem taxa base medida. 0,45 é a
        #: mediana das cinco competições do corpus — um palpite declarado, e
        #: preferível a supor zero, que faria qualquer vizinhança passar.
        self._taxa_base_padrao = taxa_base_padrao

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        result = inputs.similarity
        if result is None or not result.matches:
            return []

        # Domain/version compatibility gate — every returned neighbour must be
        # compatible with the query facets that were actually declared.
        compatible = [m for m in result.matches if self._compatible(m, result)]
        if not compatible:
            return []

        # Score the neighbourhood the detector ACTUALLY accepted.
        # `result.confidence` was computed by the similarity service over
        # ALL returned matches, including the ones just filtered out —
        # so with 20 neighbours returned and 4 surviving, the emitted
        # trend's strength, confidence and evidence described a
        # 20-neighbour set the detector had itself rejected. The
        # published payload even contradicted itself:
        # evidence["neighbor_count"]=20 next to 4 matched_event_ids.
        # `confidence_for_matches` is the same pure function the service
        # uses, so this is a re-scope, not a different metric.
        confidence = confidence_for_matches(
            compatible, minimum_neighbors=result.confidence.minimum_neighbors
        )
        best_similarity = max(m.similarity for m in compatible)
        neighbor_count = len(compatible)

        # Similarity gates.
        if best_similarity < result.minimum_similarity:
            return []
        if neighbor_count < confidence.minimum_neighbors:
            return []
        # CONCORDÂNCIA DE DESFECHO, CONTRA A TAXA BASE DESTA COMPETIÇÃO.
        #
        # Sem desfecho nos vizinhos não há o que julgar, e o detector não
        # emite: um portão que não consegue medir não deve deixar passar por
        # não conseguir.
        if confidence.outcome_agreement is None:
            return []
        taxa_base = self._taxa_base(inputs)
        # ESTRITAMENTE MAIOR, e não "maior ou igual". Empatar com a taxa base
        # mais a margem não é superá-la, e a borda cai com frequência: com 4
        # vizinhos e três desfechos possíveis, a concordância mínima possível
        # é 2/4 = 50% — exatamente 45% + 5%.
        if confidence.outcome_agreement <= taxa_base + self._margem:
            return []

        trends: list[Trend] = [
            self._trend(
                inputs,
                result,
                compatible,
                trend_type=TrendType.historical_similarity,
                best_similarity=best_similarity,
                confidence=confidence,
            )
        ]

        # Pattern gate — a coherent, recurring neighbourhood (strictly tighter).
        if (
            neighbor_count >= self._pattern_min_neighbors
            and confidence.outcome_agreement > taxa_base + self._margem_padrao
        ):
            trends.append(
                self._trend(
                    inputs,
                    result,
                    compatible,
                    trend_type=TrendType.historical_pattern,
                    best_similarity=best_similarity,
                    confidence=confidence,
                )
            )
        return trends

    def _taxa_base(self, inputs: TrendInputs) -> float:
        """A taxa base da competição consultada.

        Ela viaja no contexto, posta ali por quem construiu a vizinhança e
        tem acesso a `atlas.lens_validation` — a MESMA tabela com que cada
        lente é validada. O detector é uma função pura de portões e não abre
        conexão; buscar o número aqui dentro faria dele um segundo lugar que
        sabe o que é uma taxa base, e dois lugares divergem.

        Sem o número, cai no padrão declarado. Isso é conservador na direção
        certa: 0,45 é mais alto que a taxa base de duas das cinco competições
        do corpus, então o portão fica mais apertado, não mais frouxo.
        """
        contexto = inputs.similarity
        if contexto is None:
            return self._taxa_base_padrao
        # `getattr` porque `inputs.similarity` pode ser um
        # `SimilaritySearchResult`, que não tem metadata — só o
        # `SimilarityContext` construído pela ponte carrega a taxa base.
        valor = (getattr(contexto, "metadata", None) or {}).get("taxa_base")
        try:
            taxa = float(valor)
        except (TypeError, ValueError):
            return self._taxa_base_padrao
        return taxa if 0.0 < taxa < 1.0 else self._taxa_base_padrao

    # -- gates ----------------------------------------------------------------

    @staticmethod
    def _compatible(match: SimilarityMatch, result: SimilarityContext) -> bool:
        filters = result.filters
        if match.embedding_version != filters.embedding_version:
            return False
        # Each optional facet is gated ONLY when the query declared it.
        checks = (
            (filters.feature_schema_version, match.feature_schema_version),
            (filters.competition, match.competition),
            (filters.season, match.season),
            (filters.market_type, match.market_type),
            (filters.match_phase, match.match_phase),
        )
        for wanted, got in checks:
            if wanted is not None and got != wanted:
                return False
        return True

    # -- trend construction ---------------------------------------------------

    def _trend(
        self,
        inputs: TrendInputs,
        result: SimilarityContext,
        matches: list[SimilarityMatch],
        *,
        trend_type: TrendType,
        best_similarity: float,
        confidence: SimilarityConfidence,
    ) -> Trend:
        is_pattern = trend_type == TrendType.historical_pattern
        return Trend(
            trend_type=trend_type,
            category=TrendCategory.oracle,
            canonical_match_id=inputs.canonical_match_id,
            competition_id=inputs.competition_id,
            minute=inputs.minute,
            # Pattern strength leans on tightness; similarity strength on the
            # combined similarity score. Both bounded [0, 1].
            strength=_clamp(
                confidence.outcome_agreement if is_pattern else confidence.similarity_score
            ),
            confidence=_clamp(confidence.confidence),
            direction=0,  # historical resemblance has no market direction
            evidence=self._evidence(
                result, matches, best_similarity, trend_type, confidence
            ),
        )

    def _evidence(
        self,
        result: SimilarityContext,
        matches: list[SimilarityMatch],
        best_similarity: float,
        trend_type: TrendType,
        confidence: SimilarityConfidence,
    ) -> dict:
        filters = result.filters
        top = matches[: self._top_neighbors]
        kind = "pattern" if trend_type == TrendType.historical_pattern else "resemblance"
        summary = (
            f"{len(matches)} compatible historical neighbours "
            f"(best similarity {best_similarity:.3f}, "
            f"concordância {confidence.outcome_agreement:.3f}) "
            f"establish a {kind} under embedding {filters.embedding_version}."
        )
        return {
            # matched event ids
            "matched_event_ids": [m.match_id for m in matches],
            # distances / similarities
            "best_similarity": round(best_similarity, 6),
            "similarity_score": confidence.similarity_score,
            "average_distance": confidence.average_distance,
            "distance_spread": confidence.distance_spread,
            "outcome_agreement": confidence.outcome_agreement,
            "modal_outcome": confidence.modal_outcome,
            "distance_uniformity": confidence.distance_uniformity,
            # counts / confidence
            "neighbor_count": confidence.neighbor_count,
            "minimum_neighbors": confidence.minimum_neighbors,
            "minimum_similarity": result.minimum_similarity,
            "confidence": confidence.confidence,
            # versions (explainability)
            "embedding_version": filters.embedding_version,
            "feature_schema_version": filters.feature_schema_version,
            "signal_catalog_version": filters.signal_catalog_version,
            "behavior_catalog_version": filters.behavior_catalog_version,
            "competition": filters.competition,
            "season": filters.season,
            "market_type": filters.market_type,
            "match_phase": filters.match_phase,
            # reasoning + top contributing neighbours
            "reasoning_summary": summary,
            "gate_reasons": confidence.reasons,
            "top_neighbors": [
                {
                    "match_id": m.match_id,
                    "similarity": m.similarity,
                    "distance": m.distance,
                    "competition": m.competition,
                    "season": m.season,
                }
                for m in top
            ],
        }
