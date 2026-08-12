"""Trend Timeline — Sprint 3.6 Part 1.

The ordered, append-only narrative timeline of one story (Atlas's
story unit is the trend lifecycle instance — `cluster_id` carries its
instance_id). Persisted and exposed internally for future Nexus
continuity, agent historical references and retrospective generation.
No APIs.
"""

from atlas.trends.timeline.models import TrendTimeline, TrendTimelineEntry
from atlas.trends.timeline.repository import TrendTimelineRepository

__all__ = ["TrendTimeline", "TrendTimelineEntry", "TrendTimelineRepository"]
