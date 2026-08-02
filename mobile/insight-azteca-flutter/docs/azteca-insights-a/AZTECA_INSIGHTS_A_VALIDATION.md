# AZTECA-INSIGHTS-A — Validation

## insight-azteca-flutter
- `flutter pub get` — OK (**no dependency added** — chart deferred).
- `flutter analyze` — **No issues found**.
- `flutter test` — **102 passed / 0 failed** (was 75 after PROFILE-B; **+27**).
- `git diff --check` — clean.

### New tests (27)
`test/insight_semantics_test.dart` (20) — delta needs a baseline; zero-baseline % is null; polarity/
favourability (incl. `lowerIsBetter`); probability bounds asserted; **probability ≠ confidence** (no derivation);
confidence bounds + bands; comparison null ratio/share on zero denominator; **TrendSeries rejects <2 points**
(no fake trend from a scalar); series auto-sort + real direction + asDelta; distribution rejects 1 bucket +
normalizes shares; freshness defaults to unknown; explanation carries product language only.
`test/insight_primitives_test.dart` (7) — scalar renders + semantic sentence; delta icon **+ text** for up and
down (never colour-alone); unknown direction renders **no arrow**; probability bar vs confidence segments are
visually distinct; comparison with nothing to compare renders "—"; unknown freshness renders nothing;
explanation renders product language + evidence summary + source.

## Backend
**No backend repository changed** ⇒ no Go/Python validation required for this sprint. Verified untouched:
insight-social (POSTS-B feed fix + PROFILE-B PATCH intact) and insight-gateway (QUALITY-A avatar 503 +
PROFILE-B PATCH proxy intact). **Atlas 1.0.0 not modified** (inspected read-only only).

## Honesty
No live production mutation, no deployment. No fabricated live/smoke results.
