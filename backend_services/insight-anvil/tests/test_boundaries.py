"""Consolidation Sprint 0 Task 7 — dependency boundary enforcement.

Anvil is the analytics worker. It must never import
a retired or external-domain service package again. These tests walk
every module's import statements (AST level — no execution) and fail
loudly if a forbidden dependency is reintroduced.
"""

from __future__ import annotations

import ast
import pathlib

FORBIDDEN_ROOTS = {
    "playmaker",        # retired — runtime/streaming absorbed into anvil.*
    "pundit",           # retired — superseded by the trend stream + Nexus
    "atrium",           # legacy BFF — superseded by the Gateway
    "plaza",            # legacy social — superseded by insight-social
    "insight_magnus",   # retired odds library
}

PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[1] / "anvil"


def _imported_roots(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_no_legacy_imports_in_anvil() -> None:
    violations: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        bad = _imported_roots(path) & FORBIDDEN_ROOTS
        if bad:
            violations.append(f"{path.relative_to(PACKAGE_ROOT.parent)}: {sorted(bad)}")
    assert not violations, (
        "Legacy service imports reintroduced:\n" + "\n".join(violations)
    )


def test_no_legacy_imports_in_tests() -> None:
    tests_root = pathlib.Path(__file__).resolve().parent
    violations: list[str] = []
    for path in sorted(tests_root.rglob("*.py")):
        bad = _imported_roots(path) & FORBIDDEN_ROOTS
        if bad:
            violations.append(f"{path.name}: {sorted(bad)}")
    assert not violations, (
        "Legacy service imports reintroduced in tests:\n" + "\n".join(violations)
    )
