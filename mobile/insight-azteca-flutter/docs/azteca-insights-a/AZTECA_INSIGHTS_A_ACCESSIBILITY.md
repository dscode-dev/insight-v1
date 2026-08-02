# AZTECA-INSIGHTS-A — Accessibility & Localization

## Never colour-alone (enforced in the primitives, not left to callers)
Every directional read pairs **icon + text**: `↑ +8,4%`, `↓ -3,1%`, `→ estável`. Colour only *reinforces*.
Test: `delta shows icon + TEXT (never colour alone) for up and down`. `MetricDirection.unknown` renders **no
arrow at all** (test-locked) — absence of a baseline is communicated, not implied by a neutral colour.

## Semantics (screen readers read sentences, not fragments)
- `InsightMetricCard` → "Publicações: 12" (test-asserted).
- `DeltaIndicator` → "Pressão: subiu +8,4% em relação a 100".
- `ProbabilityBar` → "Probabilidade de Vitória A: 64%".
- `ConfidenceIndicator` → "Confiança na estimativa: Alta, com evidências".
- `ComparisonBar` → "Pressão: A 71 contra B 50".
- `FreshnessIndicator` → "Atualização: Recente".
- `InsightExplanationCard` → "Explicação: … . Baseado em 12 partidas semelhantes".
Composite widgets use `excludeSemantics: true` so the reader gets one clean sentence instead of stray tokens.

## Localization
- All numbers/percentages go through `intl` with `Localizations.localeOf(context)` — **no hardcoded en-US**
  (pt-BR renders "+8,4%" with a comma). `NumberFormat.decimalPattern` / `percentPattern`.
- Copy uses the existing Azteca pt-BR approach (no new localization architecture introduced).
- `FontFeature.tabularFigures` keeps digits aligned as values grow.

## Text scaling & motion
No fixed heights on text; tiles size to content (`mainAxisSize.min`), so large text scales don't clip.
No metric animations added ⇒ nothing to violate reduced-motion. (When charts land, honour reduced-motion there.)
