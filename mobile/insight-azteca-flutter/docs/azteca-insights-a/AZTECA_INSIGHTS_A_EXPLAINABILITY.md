# AZTECA-INSIGHTS-A — Explainability

## Status: **language built, BLOCKED_BY_CONTRACT for data**
No product-facing explanation/reasoning contract exists (Stage 0: no `/v1/context/*`, no insights route).
Explanations are therefore **not rendered anywhere** — nothing is fabricated.

## What was built
`InsightExplanation` (model) + `InsightExplanationCard` (widget):
- `summary` — one product sentence: what changed / why it matters;
- `factors[]` — short product-language contributing factors;
- `evidenceSummary` — a *summary* ("Baseado em 12 partidas semelhantes"), never raw evidence;
- `source` — `InsightSource.{platform, community, market, historical, unknown}` — a **product category**, never
  a class/detector name;
- `freshness` — how fresh, when the contract says.

## Structural guarantee against leaking internals
The type has **no field capable of carrying** feature vectors, embedding dimensions, detector class names,
SimilarityContext, replay metadata, or model traces. Leaking them would require changing the type — it is not
a convention, it is the API surface.

## Product language (required)
✅ "Pressão de mercado subiu após movimento sustentado em várias casas."
❌ "OracleSimilarityDetector passed agreement gate 0.72."

## Required projection (future)
`MatchInsightSummary.explanations[] { summary, factors[], evidence_summary?, source }` — produced by the
Gateway from internal reasoning, translated into product language server-side. Flutter maps 1:1 to
`InsightExplanation`. Until then the UI stays honest (absent, not faked).
