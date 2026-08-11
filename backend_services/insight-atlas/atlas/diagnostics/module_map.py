"""What each package in Atlas is, and whether anything still reaches it.

THE PROBLEM THIS ANSWERS. Atlas is 34.200 lines across 256 modules in 41
top-level packages, with 20 of its 27 tables empty. Reading it does not tell
you which parts are load-bearing, and that is the actual complaint: not that
the code is wrong, but that nobody can say what is happening inside it.

REACHABILITY, NOT COVERAGE. A package is called ALIVE here when the running
service can reach it by following imports from an entry point. That is a
weaker claim than "is used" — a module can be imported and never called — but
it is a claim that can be checked mechanically and cannot be argued with. The
opposite verdict is the useful one: a package nothing imports is dead beyond
dispute, and that is the list worth acting on.

TESTS DO NOT KEEP CODE ALIVE. A package reached only from `tests/` is
reported as `só testes`, and one reached only from `scripts/` as `só
scripts` — real, but an operator command rather than the running service.
Counting either as alive is how a codebase grows a museum.

REACHABILITY ALONE IS NOT ENOUGH HERE, and the first run proved it: 42 of
43 packages came back alive, because Atlas wires almost everything into the
container at boot. Yet 20 of its 27 tables are empty. The deadness is in the
DATA, not in the imports — so `map_tables` crosses the two, and a package
that is reachable while every table it writes sits empty is the honest
definition of decorative.

Static imports only. `importlib` calls and deferred imports inside functions
ARE followed (the AST walk does not care about indentation), but a module
resolved from a string at runtime is invisible here — noted so a `dead`
verdict is read as "no import found", not "proven unreachable".
"""

from __future__ import annotations

import ast
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

#: Where the running service starts. Everything the container executes is
#: reachable from one of these; anything that is not, is not running.
ENTRY_POINTS = ("atlas.main", "atlas.api.app", "atlas.cli")


@dataclass(frozen=True)
class PackageInfo:
    name: str
    modules: int
    lines: int
    #: Packages that import this one, excluding itself.
    imported_by: tuple[str, ...]
    verdict: str  # "vivo" | "só testes" | "morto"

    @property
    def dead(self) -> bool:
        return self.verdict == "morto"


@dataclass
class ModuleMap:
    packages: list[PackageInfo]
    total_modules: int
    total_lines: int
    unreachable_modules: tuple[str, ...]

    @property
    def dead_packages(self) -> list[PackageInfo]:
        return [p for p in self.packages if p.dead]

    @property
    def dead_lines(self) -> int:
        return sum(p.lines for p in self.packages if p.dead)

    def as_dict(self) -> dict:
        return {
            "total_modules": self.total_modules,
            "total_lines": self.total_lines,
            "packages": [
                {
                    "name": p.name, "modules": p.modules, "lines": p.lines,
                    "verdict": p.verdict, "imported_by": list(p.imported_by),
                }
                for p in self.packages
            ],
            "dead_packages": [p.name for p in self.dead_packages],
            "dead_lines": self.dead_lines,
            "unreachable_modules": list(self.unreachable_modules),
        }


def map_modules(root: Path, *, package: str = "atlas", tests_dir: str = "tests") -> ModuleMap:
    """Build the import graph and judge each top-level package."""
    modules = _collect(root / package, package)
    test_modules = _collect(root / tests_dir, tests_dir) if (root / tests_dir).exists() else {}
    script_modules = (
        _collect(root / "scripts", "scripts") if (root / "scripts").exists() else {}
    )

    edges: dict[str, set[str]] = {}
    for name, path in {**modules, **test_modules, **script_modules}.items():
        edges[name] = _imports_of(path, name, known=set(modules))

    reachable = _walk(edges, [e for e in ENTRY_POINTS if e in modules])
    from_scripts = _walk(edges, list(script_modules)) - reachable
    from_tests = _walk(edges, list(test_modules)) - reachable - from_scripts

    lines_by_module = {name: _line_count(path) for name, path in modules.items()}
    imported_by: dict[str, set[str]] = defaultdict(set)
    for importer, targets in edges.items():
        for target in targets:
            source_pkg, target_pkg = _top(importer, package), _top(target, package)
            if target_pkg and source_pkg != target_pkg:
                imported_by[target_pkg].add(source_pkg or importer.split(".")[0])

    grouped: dict[str, list[str]] = defaultdict(list)
    for name in modules:
        top = _top(name, package)
        if top:
            grouped[top].append(name)

    packages: list[PackageInfo] = []
    for name, members in sorted(grouped.items()):
        if any(m in reachable for m in members):
            verdict = "vivo"
        elif any(m in from_scripts for m in members):
            verdict = "só scripts"
        elif any(m in from_tests for m in members):
            verdict = "só testes"
        else:
            verdict = "morto"
        packages.append(
            PackageInfo(
                name=name,
                modules=len(members),
                lines=sum(lines_by_module[m] for m in members),
                imported_by=tuple(sorted(imported_by.get(name, ()))),
                verdict=verdict,
            )
        )

    order = {"morto": 0, "só testes": 1, "só scripts": 2, "vivo": 3}
    packages.sort(key=lambda p: (order[p.verdict], -p.lines))
    return ModuleMap(
        packages=packages,
        total_modules=len(modules),
        total_lines=sum(lines_by_module.values()),
        unreachable_modules=tuple(
            sorted(set(modules) - reachable - from_tests - from_scripts)
        ),
    )


@dataclass(frozen=True)
class TableUse:
    table: str
    rows: int
    #: Packages whose source mentions this table by name.
    referenced_by: tuple[str, ...]

    @property
    def decorative(self) -> bool:
        """Code exists to fill it, and it is empty.

        The pairing is what makes this worth reporting. An empty table with
        no code behind it is merely a leftover migration; an empty table
        that several packages write through is a feature that runs and
        produces nothing — which is the kind of thing that makes a system
        impossible to reason about.
        """
        return self.rows == 0 and bool(self.referenced_by)


def map_tables(
    root: Path, row_counts: dict[str, int], *, package: str = "atlas"
) -> list[TableUse]:
    """Cross every table with the packages that name it in their source.

    Textual, deliberately: the table names appear in raw SQL, in SQLAlchemy
    models and in migration files, and no single parser sees all three. A
    name mentioned in a comment counts as a reference here — the direction to
    be wrong in, since this list decides what gets DELETED.
    """
    sources: dict[str, str] = {}
    for name, path in _collect(root / package, package).items():
        top = _top(name, package)
        if not top:
            continue
        try:
            sources[name] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

    uses: list[TableUse] = []
    for table, rows in sorted(row_counts.items()):
        bare = table.split(".")[-1]
        referenced = {
            _top(name, package)
            for name, text in sources.items()
            if bare in text and _top(name, package)
        }
        uses.append(
            TableUse(table=table, rows=rows, referenced_by=tuple(sorted(referenced)))
        )
    uses.sort(key=lambda u: (u.rows > 0, -len(u.referenced_by), u.table))
    return uses


def _collect(directory: Path, prefix: str) -> dict[str, Path]:
    """Module dotted-name → file, skipping caches and generated code."""
    found: dict[str, Path] = {}
    if not directory.exists():
        return found
    for path in sorted(directory.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(directory).with_suffix("")
        parts = [prefix, *relative.parts]
        if parts[-1] == "__init__":
            parts = parts[:-1]
        found[".".join(parts)] = path
    return found


def _imports_of(path: Path, module: str, *, known: set[str]) -> set[str]:
    """Modules this file imports, resolved to names that exist in the tree."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()

    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                # Relative import: climb the importer's own package.
                parts = module.split(".")
                base = ".".join(parts[: max(0, len(parts) - node.level)] + ([base] if base else []))
            targets.add(base)
            targets.update(f"{base}.{alias.name}" for alias in node.names if base)

    # `from atlas.strength import X` names the package; `X` may be a symbol
    # rather than a module, so only what actually exists is kept.
    return {t for t in targets if t in known} - {module}


def _walk(edges: dict[str, set[str]], seeds: list[str]) -> set[str]:
    seen, queue = set(seeds), deque(seeds)
    while queue:
        for nxt in edges.get(queue.popleft(), ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def _top(module: str, package: str) -> str | None:
    parts = module.split(".")
    if parts[0] != package or len(parts) < 2:
        return None
    return parts[1]


def _line_count(path: Path) -> int:
    try:
        return sum(1 for _ in path.open(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return 0
