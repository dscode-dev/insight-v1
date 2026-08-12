"""Pattern Memory — Sprint 2 Part A3.

Pure statistical recurrence memory over trend lifecycle outcomes. No
embeddings, no vector DB, no ML — counts and rates only, fully
explainable and reproducible from the stored rows.
"""

from atlas.patterns.memory import PatternMemory, PatternStats, pattern_key

__all__ = ["PatternMemory", "PatternStats", "pattern_key"]
