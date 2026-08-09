"""Methods the API depends on are actually methods of their class.

This is not a hypothetical. `coverage_by_version` and `overview` were
both appended to the end of their files, which placed them AFTER the
module-level helper functions and therefore outside the class. Python
parses that without complaint, ruff is happy, and the only symptom in
production was `/v1/meta/embeddings` reporting `available: false` —
because the route guards with `hasattr` and degraded honestly instead of
crashing. A guard that hides the bug is exactly why this needs a test.

Checks the class surface directly rather than calling the methods: the
point is where the function is DEFINED, which no behavioural test of a
correctly-defined method would ever catch.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from atlas.backtest.approval import PromotionDecisionRepository
from atlas.strength.repository import StrengthRepository
from atlas.vector_memory.repository import PgVectorMemoryRepository

# (class, method) pairs that an API route reaches for by name.
API_SURFACES = [
    (PgVectorMemoryRepository, "coverage_by_version"),  # GET /v1/meta/embeddings
    (StrengthRepository, "overview"),                   # GET /v1/meta/strength
    (PromotionDecisionRepository, "record"),            # POST /backtests/{id}/decision
    (PromotionDecisionRepository, "get_by_hash"),       # GET  /backtests/{id}/decision
    (PromotionDecisionRepository, "history"),           # GET  /backtests/decisions
]


@pytest.mark.parametrize(
    ("cls", "method"),
    API_SURFACES,
    ids=[f"{c.__name__}.{m}" for c, m in API_SURFACES],
)
def test_method_is_bound_to_its_class(cls: type, method: str) -> None:
    # hasattr is what the routes themselves check, so it is what has to
    # hold — a function defined at module level or nested inside another
    # helper fails here exactly as it failed in production.
    assert hasattr(cls, method), (
        f"{cls.__name__}.{method} is missing — most likely defined outside "
        f"the class body (check its indentation and position in the file)"
    )
    assert callable(getattr(cls, method))


@pytest.mark.parametrize(
    ("cls", "method"),
    API_SURFACES,
    ids=[f"{c.__name__}.{m}" for c, m in API_SURFACES],
)
def test_method_is_declared_inside_the_class_body(cls: type, method: str) -> None:
    """Parse the source and assert the def really sits in the class body.

    `hasattr` alone can be satisfied by a later monkeypatch or an
    assignment; this pins the file layout, which is what actually broke.
    """
    source = Path(inspect.getfile(cls)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == cls.__name__
    )
    declared = {
        node.name
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert method in declared, (
        f"{method} is not declared in {cls.__name__}'s class body — "
        f"found there: {sorted(declared)}"
    )
