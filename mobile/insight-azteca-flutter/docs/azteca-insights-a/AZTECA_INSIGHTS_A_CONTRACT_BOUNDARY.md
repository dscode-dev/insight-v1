# AZTECA-INSIGHTS-A — Product Contract Boundary

## Architectural rule (upheld)
```
Azteca Flutter → Gateway (product API) → product projection → Explorer / Atlas / Magnus
```
Flutter consumes **product-oriented projections only**. It must never import/see: SimilarityContext,
ReplayManifest, QualityEvaluation, detector internals, trend-engine objects, IOC events, vector memory.

## Decision for THIS sprint: **NO backend change**
Stage 0 proved:
1. The only real intelligence contract Azteca can consume (`/v1/users/{id}/sports-profile`) **already exists,
   is product-oriented, and is sufficient** for the Profile Statistics integration. ⇒ reuse; create no duplicate.
2. Every other intelligence surface (match probabilities, momentum, odds series, radar magnitude/confidence)
   is **BLOCKED_BY_CONTRACT**: its producers (`/v1/live/*`, `/v1/radar/*`, `/v1/context/*`) do not exist. Building
   a Gateway projection now would mean projecting *nothing* — or worse, reaching into Atlas internals to
   manufacture a payload. Both are forbidden. ⇒ **no projection built; requirement documented instead.**

⇒ **Backend repositories changed this sprint: NONE.** insight-social and insight-gateway are untouched
(their code-ready lineage — social 0.1.10, gateway 0.1.15 — is preserved exactly).

## Required future projection (for the sprint that has real producers)
When Live/Radar/context producers exist, expose ONE additive, versioned, bounded, product-typed read:
```
GET /v1/matches/{id}/insights →
MatchInsightSummary {
  match_id, generated_at, freshness,
  metrics[]:       { label, value, unit }
  probabilities[]: { label, probability(0..1), confidence?(0..1) }
  comparisons[]:   { label, left{label,value}, right{label,value}, unit }
  trends[]:        { label, unit, points[]{ at, value }, reference? }
  explanations[]:  { summary, factors[], evidence_summary?, source }
}
```
Rules: no Atlas structure passthrough; no detector/vector/replay fields; bounded array sizes; stable
semantics independent of Atlas implementation; versionable. The Flutter semantic model already maps 1:1 to
this shape, so the client work will be a thin DTO→model mapper.

## Explicitly rejected designs
- A generic `/v1/proxy?url=` or any caller-controlled forwarding — forbidden.
- Exposing Atlas contracts directly to Flutter — forbidden (and would break the Atlas 1.0.0 freeze contract).
- Fabricating a projection from internals to make the UI look finished — forbidden.
