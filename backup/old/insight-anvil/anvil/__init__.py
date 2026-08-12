"""Anvil — analytics worker for Insight Layer F/E.

Consumes derived events from Atlas's output streams and persists them
to ClickHouse for historical query, backtesting, and ML feature retrieval.

Public surface kept narrow on purpose; everything else is an implementation
detail of the worker.
"""

from __future__ import annotations

__version__ = "0.1.0"
