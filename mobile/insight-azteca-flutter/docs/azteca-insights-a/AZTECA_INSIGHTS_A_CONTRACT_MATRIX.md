# AZTECA-INSIGHTS-A — Contract Matrix

| Capability | Product contract | Producer | Class | V1 action |
|---|---|---|---|---|
| Profile totals (posts, signals, followers, following, communities) | `GET /v1/users/{id}/sports-profile` ✅ | Social (SQL counts) | REAL_AND_CONSUMABLE | **Integrated** with primitives |
| Reputation | same ✅ | Social `users.reputation` | REAL_AND_CONSUMABLE | **Integrated** |
| Role / level | same ✅ (role = const "supporter") | Social | REAL_AND_CONSUMABLE (honest) | rendered as-is (PROFILE-B) |
| "precisão" / accuracy | `/v1/profile/me/bundle` ⚠️ **stub** (`NativeFlagged`) | — (none) | NOT_IMPLEMENTED | **REMOVED** (was fabrication) |
| Profile badges | `/v1/profile/me/bundle` ⚠️ stub | — | NOT_IMPLEMENTED (achievement, not a metric) | left as-is; flagged for CERTIFY-A |
| Match probabilities (1/X/2) | ❌ none (`/v1/context/*` absent) | Atlas (internal) | BLOCKED_BY_CONTRACT | language built; **not rendered** |
| Confidence in estimate | ❌ none | Atlas (internal) | BLOCKED_BY_CONTRACT | primitive built; not rendered |
| Momentum / pressure | ❌ none (`/v1/live/*` absent) | — | BLOCKED_BY_CONTRACT / NOT_IMPLEMENTED | deferred to LIVE-RADAR |
| Odds evolution (series) | ❌ none | — | BLOCKED_BY_CONTRACT | **no chart added** (nothing to draw) |
| Radar magnitude / market movement | ❌ none (`/v1/radar/*` absent) | — | BLOCKED_BY_CONTRACT | deferred to LIVE-RADAR |
| Historical similarity / patterns | internal only | Atlas 1.0.0 (FROZEN) | REAL_BUT_INTERNAL | never exposed |
| Reasoning / explainability | ❌ no product contract | Atlas (internal) | BLOCKED_BY_CONTRACT | primitive built; not rendered |
| Deltas / ratios from two real values | n/a (pure presentation) | client | CLIENT_DERIVABLE_SAFE | supported by the model |
