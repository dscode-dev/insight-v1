# AZTECA-INSIGHTS-A — Performance

## Findings (audit, not speculative optimization)
- **No chart repaint cost**: no chart library, no `CustomPainter` — nothing to repaint. (The heaviest widget
  is a `LinearProgressIndicator`.)
- **Rebuild scope**: primitives are `StatelessWidget` + `const` constructors; the model is `@immutable` with
  `const` constructors, so identical metrics are canonicalized and skip rebuilds.
- **Provider invalidation is scoped**: Statistics watches `sportsProfileProvider(userId)` only. A metric
  refresh does **not** rebuild the whole profile tree or the feed.
- **No JSON parsing in widgets**: DTO parsing happens in the service layer; widgets receive typed models.
- **Formatter allocation**: `NumberFormat` is constructed per call in `formatMetricNumber`. Acceptable at
  current scale (≤6 metrics per screen); flagged as the first thing to memoize (per-locale cache) **if** a
  future dense/series surface renders hundreds of values. Not optimized now (no measurement, no need).
- **Lists**: Statistics uses a bounded, non-scrolling `GridView.count(shrinkWrap)` inside a `ListView` — a
  fixed 4-tile grid, not an unbounded list. Activity/Feed keep `ListView.builder` + stable keys (POSTS-B).
- **Series downsampling**: N/A (no series). When `TrendSeries` gets real data, downsample at the mapper (not
  the widget) before constructing points.

## Realtime-compatibility (without implementing REALTIME-A)
The model is immutable value-types and the primitives are pure functions of them, so a future realtime push
can replace a metric and rebuild **only** that tile — no architecture change required, no full-screen rebuild.

## Verdict
No pathological behaviour found. No premature optimization applied.
