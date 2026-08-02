"""LangGraph state machine wiring (Step 6).

The quality flow is a directed graph:

    Collect → Normalize → SchemaValidate → Deduplicate → ResolveEntities
            → ConsistencyCheck → QualityScore → Approve → Validated
                                                       ↘ Reject
                                                       ↘ HumanReview

**No business logic lives in the nodes.** Each node is a one-line delegate to
a `QualityPipeline` step method; all parsing/validation/scoring/decision logic
is in the deterministic `explorer.validators.*` modules and the pipeline. The
graph only encodes *order* and *branching*.

LangGraph is an optional dependency. `build_graph()` compiles a real
`StateGraph` when langgraph is installed (GPU host); otherwise the pipeline
runs the identical node sequence sequentially (`describe()` documents it).
"""

from __future__ import annotations

from typing import Any, Callable

# Canonical node order (single source of truth for graph + fallback runner).
NODE_SEQUENCE = (
    "collect",
    "normalize",
    "schema_validate",
    "deduplicate",
    "resolve_entities",
    "consistency_check",
    "quality_score",
    "approve",
)

TERMINALS = ("validated", "reject", "human_review")


def describe() -> dict[str, Any]:
    """Inspectable graph spec (used by tests + ML_B_LANGGRAPH_ARCHITECTURE)."""
    edges = [(NODE_SEQUENCE[i], NODE_SEQUENCE[i + 1]) for i in range(len(NODE_SEQUENCE) - 1)]
    return {
        "nodes": list(NODE_SEQUENCE),
        "terminals": list(TERMINALS),
        "edges": edges,
        "branch_nodes": ["schema_validate", "resolve_entities", "consistency_check", "quality_score"],
        "branches_to": list(TERMINALS),
    }


def langgraph_available() -> bool:
    try:
        import langgraph  # noqa: F401

        return True
    except ImportError:
        return False


def build_graph(steps: dict[str, Callable[[dict], dict]]) -> Any:
    """Compile a real LangGraph StateGraph from the pipeline step callables.

    Returns the compiled app, or None when langgraph is not installed (the
    pipeline then falls back to the sequential runner over NODE_SEQUENCE)."""
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        return None

    graph = StateGraph(dict)
    for name in NODE_SEQUENCE:
        graph.add_node(name, steps[name])
    graph.set_entry_point(NODE_SEQUENCE[0])
    for i in range(len(NODE_SEQUENCE) - 1):
        graph.add_edge(NODE_SEQUENCE[i], NODE_SEQUENCE[i + 1])
    graph.add_edge(NODE_SEQUENCE[-1], END)
    return graph.compile()
