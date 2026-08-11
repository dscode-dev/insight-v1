"""Measuring instruments for the Atlas itself.

WHY THIS PACKAGE EXISTS. Every claim made about the vector memory in the
August 2026 review — 14 constant dimensions, random pairs sitting at 0.807
similarity, retrieval beating the base rate by 5.7 points — was produced by
throwaway scripts. That makes the next measurement incomparable with this
one, and "it got better" becomes an opinion rather than a reading.

Nothing here changes state. These are read-only instruments, safe to run
against production, and every number they print is meant to be reproduced
before and after a change so the difference can be attributed.

    python -m scripts.atlas_diagnose vectors --database-url ...
    python -m scripts.atlas_diagnose modules
    python -m scripts.atlas_diagnose coverage --lake-dir ...
"""

from atlas.diagnostics.coverage import CoverageReport, measure_coverage
from atlas.diagnostics.module_map import ModuleMap, TableUse, map_modules, map_tables
from atlas.diagnostics.vector_report import (
    DimensionStat,
    VectorReport,
    measure_dimensions,
    measure_retrieval,
    measure_similarity,
)

__all__ = [
    "CoverageReport",
    "DimensionStat",
    "ModuleMap",
    "TableUse",
    "VectorReport",
    "map_modules",
    "map_tables",
    "measure_coverage",
    "measure_dimensions",
    "measure_retrieval",
    "measure_similarity",
]
