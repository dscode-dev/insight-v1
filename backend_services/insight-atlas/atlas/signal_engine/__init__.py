"""Signal Engine — Sprint 6.2 Part 4.

The first intelligence abstraction: turns provider events, Atlas
contexts and odds movements into typed Signals. Foundation that
Explorer (and other consumers) will later read — no Explorer
integration yet.
"""

from atlas.signal_engine.engine import SignalEngine
from atlas.signal_engine.models import Signal, SignalOrigin, SignalType

__all__ = ["Signal", "SignalEngine", "SignalOrigin", "SignalType"]
