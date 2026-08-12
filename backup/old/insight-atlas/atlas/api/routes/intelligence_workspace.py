from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from atlas.api.deps import AppContainer, get_container, require_internal_token
from atlas.intelligence.historical import HistoricalScope, load_dataset
from atlas.intelligence.orchestrator import (
    AtlasIntelligenceOrchestrator,
    AtlasRuntimeContext,
)
from atlas.intelligence.report_builder import HistoricalIntelligenceReportBuilder
from atlas.intelligence.signal_state_engine import SignalStateEngine
from atlas.intelligence_workspace import analyze, compare_models, knowledge
from atlas.operational_events import event_bus

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/internal/intelligence",
    tags=["intelligence-workspace"],
    dependencies=[Depends(require_internal_token)],
)

atlas_router = APIRouter(
    prefix="/atlas",
    tags=["atlas-intelligence-runtime"],
    dependencies=[Depends(require_internal_token)],
)


class AnalysisRequest(BaseModel):
    analysis_type: Literal["competition", "team", "season", "dataset", "trend"]
    query: str = Field(min_length=1, max_length=160)


async def _runtime_report(container: AppContainer, context: AtlasRuntimeContext):
    dataset = load_dataset(container.settings.intelligence_dataset_path)
    correlation_id = (
        f"runtime:{context.competition}:{context.home_team}:{context.away_team}"
    )
    # ATLAS-SIM-A: live team-strength state (Elo/attack-defense/h2h/
    # standings/rest) only needs team names + competition, so it's
    # always wireable here. Odds-tick-derived market features additionally
    # need the odds pipeline's stable match_id (atlas.odds_ticks.match_id,
    # payload-scoped — distinct from canonical_match_id) resolved from
    # (competition, home, away, kickoff); that identity-resolution lookup
    # is out of scope for this pass, so the market fallback stays unwired
    # here — the existing caller-supplied `context.odds` path (now also
    # producing line_movement) remains the live market-features source.
    strength_features = None
    if container.strength is not None:
        strength_features = await container.strength.features_for_match(
            competition=context.competition,
            home=context.home_team,
            away=context.away_team,
            as_of=context.as_of or datetime.now(timezone.utc),
        )
    try:
        event_bus.emit(
            "reasoning_started",
            current_state="processing",
            correlation_id=correlation_id,
            metadata={
                "competition": context.competition,
                "home_team": context.home_team,
                "away_team": context.away_team,
                "regime": context.regime,
            },
        )
        event_bus.emit_stage(
            "signal_loading",
            current_state="loading",
            correlation_id=correlation_id,
            competition=context.competition,
            metadata={"historical_data": context.historical_data},
        )
        signal_loading_started = time.perf_counter()
        report = AtlasIntelligenceOrchestrator(dataset).execute(
            context, strength_features=strength_features
        )
        event_bus.emit(
            "signal_loading_finished",
            current_state="loaded",
            stage="signal_loading",
            correlation_id=correlation_id,
            duration_ms=int((time.perf_counter() - signal_loading_started) * 1000),
            competition=context.competition,
            metadata={"signals": len(report.signals), "trends": len(report.trends)},
        )
        event_bus.emit(
            "behavior_engine_started",
            current_state="processing",
            stage="behavior",
            correlation_id=correlation_id,
            competition=context.competition,
        )
        event_bus.emit(
            "behavior_engine_finished",
            current_state="completed",
            stage="behavior",
            correlation_id=correlation_id,
            competition=context.competition,
            metadata={"behaviors": len(report.behaviors), "patterns": len(report.patterns or [])},
        )
        event_bus.emit(
            "similarity_started",
            current_state="processing",
            stage="similarity",
            correlation_id=correlation_id,
            competition=context.competition,
        )
        event_bus.emit(
            "similarity_finished",
            current_state="completed",
            stage="similarity",
            correlation_id=correlation_id,
            competition=context.competition,
            metadata={"similarity_available": report.similarity is not None},
        )
        embedding = DeterministicEmbeddingEncoder().from_report(report)
        vector_started = time.perf_counter()
        event_bus.emit(
            "vector_search_started",
            current_state="searching",
            stage="vector_search",
            correlation_id=correlation_id,
            competition=context.competition,
        )
        # ATLAS-SIMILARITY-B: online vector similarity now flows through the ONE
        # canonical SimilarityService (regime-scoped + causal via filters) — no
        # consumer touches pgvector or a repository directly. Same neighbours.
        vector = await container.similarity.context(
            SimilaritySearchRequest(
                embedding=embedding.embedding,
                filters=SimilarityFilters(
                    embedding_version=embedding.embedding_version,
                    competition=embedding.competition,
                    regime=embedding.regime.value,
                    time_window=TimeWindow(end=embedding.created_at),
                    exclude_match_id=embedding.source_match_id,
                ),
                top_k=25,
                minimum_similarity=0.72,
                minimum_neighbors=3,
            ),
            canonical_match_id=embedding.source_match_id,
            consumer="intelligence_workspace",
        )
        event_bus.emit(
            "vector_search_finished",
            current_state="completed",
            stage="vector_search",
            correlation_id=correlation_id,
            duration_ms=int((time.perf_counter() - vector_started) * 1000),
            competition=context.competition,
            metadata={
                "vector_neighbors": vector.confidence.neighbor_count,
                "vector_confidence": vector.confidence.confidence,
            },
        )
        memory_started = time.perf_counter()
        event_bus.emit(
            "memory_lookup_started",
            current_state="searching",
            stage="memory_lookup",
            correlation_id=correlation_id,
            competition=context.competition,
            metadata={"home_team": context.home_team, "away_team": context.away_team},
        )
        explorer = await container.ingestion.repository.latest_context(
            context.competition,
            context.home_team,
            context.away_team,
            report.as_of,
        )
        event_bus.emit(
            "memory_lookup_finished",
            current_state="completed",
            stage="memory_lookup",
            correlation_id=correlation_id,
            duration_ms=int((time.perf_counter() - memory_started) * 1000),
            competition=context.competition,
            metadata={
                "memory_rows": 1 if explorer.get("memory") else 0,
                "behavior_rows": len(explorer.get("behaviors", [])),
                "signal_rows": len(explorer.get("signals", [])),
            },
        )
        memory = explorer.get("memory")
        explorer_signal_payloads = [
            row["payload"] for row in explorer.get("signals", [])
        ]
        event_bus.emit(
            "signal_state_started",
            current_state="processing",
            stage="signal_state",
            correlation_id=correlation_id,
            competition=context.competition,
            metadata={"runtime_signals": len(report.signals), "explorer_signals": len(explorer_signal_payloads)},
        )
        signal_state_started = time.perf_counter()
        signal_state = SignalStateEngine().evaluate(
            report.signals,
            scope_key=f"runtime-endpoint:{context.competition}:"
            f"{context.home_team}:{context.away_team}",
            as_of=report.as_of,
            explorer_signals=explorer_signal_payloads,
        )
        event_bus.emit(
            "signal_state_finished",
            current_state="completed",
            stage="signal_state",
            correlation_id=correlation_id,
            duration_ms=int((time.perf_counter() - signal_state_started) * 1000),
            competition=context.competition,
            metadata={
                "strongest": len(signal_state.strongest_signals),
                "weakest": len(signal_state.weakest_signals),
                "conflicting": len(signal_state.conflicting_signals),
                "reinforced": len(signal_state.reinforced_signals),
            },
        )
        lineage = None
        if memory:
            lineage = {
                "generation_id": memory["generation_id"],
                "observed_at": memory["observed_at"],
                "lineage": memory["lineage"],
                "memory_reused": True,
                "vector_source": "hybrid_repository",
            }
        report_started = time.perf_counter()
        event_bus.emit(
            "intelligence_report_started",
            current_state="building",
            stage="report",
            correlation_id=correlation_id,
            competition=context.competition,
        )
        enriched_report = report.model_copy(
            update={
                # `matches`, not `contexts`; and neighbour_count lives on
                # `confidence`. SimilarityContext (ATLAS-SIMILARITY-A) kept the
                # SimilaritySearchResult surface — matches/confidence/filters —
                # and these two call sites were never updated to it. Both
                # raised AttributeError on the first real search, which nothing
                # noticed because atlas_vector_memory was empty until the
                # historical backfill populated it.
                "vector_contexts": vector.matches,
                "vector_neighbors": vector.confidence.neighbor_count,
                "vector_confidence": vector.confidence,
                "explorer_memory": memory["payload"] if memory else None,
                "explorer_behaviors": [
                    row["payload"] for row in explorer.get("behaviors", [])
                ],
                "explorer_signals": explorer_signal_payloads,
                "signal_states": signal_state.states,
                "signal_state": signal_state,
                "strongest_signals": signal_state.strongest_signals,
                "weakest_signals": signal_state.weakest_signals,
                "expired_signals": signal_state.expired_signals,
                "conflicting_signals": signal_state.conflicting_signals,
                "reinforced_signals": signal_state.reinforced_signals,
                "dependency_explanation": signal_state.dependency_explanation,
                "ingestion_lineage": lineage,
            }
        )
        event_bus.emit(
            "reasoning_finished",
            current_state="completed",
            stage="reasoning",
            correlation_id=correlation_id,
            competition=context.competition,
            report_id=str(enriched_report.report_id),
            metadata={"conflicts": len(enriched_report.conflicts)},
        )
        event_bus.emit(
            "intelligence_report_finished",
            current_state="completed",
            stage="report",
            correlation_id=correlation_id,
            report_id=str(enriched_report.report_id),
            duration_ms=int((time.perf_counter() - report_started) * 1000),
            competition=context.competition,
            metadata={"signals": len(enriched_report.signals), "behaviors": len(enriched_report.behaviors)},
        )
        event_bus.emit(
            "report_generated",
            current_state="completed",
            correlation_id=correlation_id,
            report_id=str(enriched_report.report_id),
            metadata={
                "report_id": str(enriched_report.report_id),
                "competition": context.competition,
                "home_team": context.home_team,
                "away_team": context.away_team,
                "signals": len(enriched_report.signals),
                "behaviors": len(enriched_report.behaviors),
                "vector_neighbors": enriched_report.vector_neighbors,
                "vector_confidence": enriched_report.vector_confidence,
                "conflicts": len(enriched_report.conflicts),
            },
        )
        event_bus.emit(
            "report_published",
            current_state="published",
            stage="report",
            correlation_id=correlation_id,
            report_id=str(enriched_report.report_id),
            competition=context.competition,
            metadata={"publication": "api_response", "side_effects": False},
        )
        return enriched_report
    except ValueError as exc:
        detail = str(exc)
        event_bus.emit(
            "reasoning_failed",
            severity="WARN",
            current_state="failed",
            correlation_id=correlation_id,
            metadata={
                "competition": context.competition,
                "home_team": context.home_team,
                "away_team": context.away_team,
                "error": detail,
            },
        )
        status_code = (
            status.HTTP_404_NOT_FOUND
            if detail == "historical_scope_empty"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except Exception as exc:
        # Any OTHER failure (e.g. Postgres/Redis instability inside
        # container.similarity/container.ingestion) previously propagated
        # with no terminal event at all — the correlation_id's last
        # visible stage stayed whatever was emitted before the crash,
        # forever, since nothing ever marked it "failed". Re-raised
        # unchanged (still a 500) — this only adds the missing signal.
        event_bus.emit(
            "reasoning_failed",
            severity="ERROR",
            current_state="failed",
            correlation_id=correlation_id,
            metadata={
                "competition": context.competition,
                "home_team": context.home_team,
                "away_team": context.away_team,
                "error": str(exc),
            },
        )
        raise


@atlas_router.post("/vector-memory/refresh")
async def refresh_vector_memory(
    container: AppContainer = Depends(get_container),
) -> dict:
    """Reconstrói a memória vetorial a partir de `atlas.match_record`.

    APONTAVA PARA O LAKE. Até o passo 7 esta rota chamava um watcher que
    varria `validated/`, tirava a impressão digital do diretório e
    reconstruía se ela tivesse mudado. O lake saiu; a rota ficou, porque a
    necessidade que a criou não mudou: quem acabou de ingerir precisa saber
    se aquilo chegou ao caminho quente, e não na próxima passagem de 30
    minutos nem abrindo o banco.

    NÃO TEM MAIS `force`. O parâmetro existia para forçar apesar da
    impressão digital do diretório não ter mudado. Sem diretório observado,
    toda chamada reconstrói — que é o que `force=true` significava.

    RECONSTRÓI TUDO, SEMPRE. As features são walk-forward: uma partida
    inserida no meio da linha do tempo muda todas as posteriores, então a
    reconstrução parcial correta é a inteira.
    """
    builder = getattr(container, "vector_builder", None)
    if builder is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="vector_builder_not_configured",
        )
    try:
        resultado = await builder.construir()
    except Exception as exc:  # noqa: BLE001 — o motivo é a entrega
        logger.exception("vector_build_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "vector_build_failed",
                # O tipo separa "não há partidas" de "o banco recusou a
                # escrita" sem o operador precisar dos logs de um host que
                # ele talvez nem alcance.
                "kind": type(exc).__name__,
                "reason": str(exc)[:500],
            },
        ) from exc

    payload = resultado.as_dict()
    # Construir zero partidas não é erro — a base pode estar vazia — mas
    # também não é sucesso, e um chamador que visse só o HTTP 200 reportaria
    # "aplicado" para uma memória que nunca foi escrita.
    payload["applied"] = resultado.partidas > 0
    return payload


@atlas_router.post("/intelligence")
async def runtime_intelligence(
    body: AtlasRuntimeContext,
    container: AppContainer = Depends(get_container),
) -> dict:
    """Execute the deterministic intelligence runtime without side effects."""
    return (await _runtime_report(container, body)).model_dump(mode="json")


@atlas_router.get("/reasoning")
async def runtime_reasoning(
    competition: str,
    home_team: str,
    away_team: str,
    container: AppContainer = Depends(get_container),
) -> dict:
    report = await _runtime_query_report(
        container, competition, home_team, away_team
    )
    return {
        "report_id": str(report.report_id),
        "reasoning": report.reasoning.model_dump(mode="json"),
        "confidence_explanation": report.confidence_explanation.model_dump(
            mode="json"
        ),
        "uncertainty_explanation": report.uncertainty_explanation.model_dump(
            mode="json"
        ),
    }


@atlas_router.get("/intelligence-graph")
async def runtime_intelligence_graph(
    competition: str,
    home_team: str,
    away_team: str,
    container: AppContainer = Depends(get_container),
) -> dict:
    report = await _runtime_query_report(
        container, competition, home_team, away_team
    )
    return {
        "report_id": str(report.report_id),
        "graph": report.graph.model_dump(mode="json"),
    }


@atlas_router.get("/conflicts")
async def runtime_conflicts(
    competition: str,
    home_team: str,
    away_team: str,
    container: AppContainer = Depends(get_container),
) -> dict:
    report = await _runtime_query_report(
        container, competition, home_team, away_team
    )
    return {
        "report_id": str(report.report_id),
        "conflicts": [
            conflict.model_dump(mode="json") for conflict in report.conflicts
        ],
    }


def _historical_report(
    container: AppContainer,
    competition: str,
    year: int | None,
    season: str | None,
    home_team: str | None = None,
    away_team: str | None = None,
):
    dataset = load_dataset(container.settings.intelligence_dataset_path)
    try:
        return HistoricalIntelligenceReportBuilder(dataset).build(
            HistoricalScope(competition=competition, year=year, season=season),
            home_team=home_team,
            away_team=away_team,
        )
    except ValueError as exc:
        if str(exc) == "both_teams_required":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="both_teams_required",
            ) from exc
        if str(exc) in {
            "historical_scope_empty",
            "historical_matchup_empty",
        }:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="historical_scope_empty",
            ) from exc
        raise


