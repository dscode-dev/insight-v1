"""CLI over `atlas.intelligence.corpus.build`.

    python -m scripts.atlas_similarity_dataset_build <validated_lake_dir> <out_dir>

The logic moved into the package so the scheduled refresh
(`atlas.vector_memory.refresh`) can call it without `atlas` importing
`scripts/` — which would close a cycle, since this file imports `atlas.*`.
Kept as an entry point because a rebuild is still something an operator
needs to be able to run by hand: after a registry correction, or to inspect
what the merge did before letting the scheduler publish it.

`<validated_lake_dir>` must point at Explorer's `validated/` layer
specifically, never the lake root.
"""

from __future__ import annotations

import sys

from atlas.intelligence.corpus import build

__all__ = ["build"]


def main() -> None:
    lake_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/validated"
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "/tmp/similarity-dataset"
    build(lake_dir, out_dir)


if __name__ == "__main__":
    main()
