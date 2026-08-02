# AZTECA-POSTS-B — Deployed vs Code-Ready Delta (read-only)

## Deployed (live, read-only checks)
- insight-gateway: **0.1.13** · insight-social: **0.1.8** (instance-20260604-195317, us-central1-c).
- Routes verified registered (401 unauth): `/v1/feed/global`, `/v1/users/{id}/sports-profile`,
  `/v1/users/me/preferences`. Avatar route `/v1/users/me/avatar` → 404 (QUALITY-A fix not yet deployed).
- No `/v1/gifs/*` route exists.

## Code-ready working tree
- **insight-social 0.1.9 (target)** — POSTS-B feed self-post fix (Global feed public fill no longer excludes
  own posts). Requires a new Social image + deploy.
- **insight-gateway 0.1.14 (target, from QUALITY-A)** — avatar route always-registers + 503; UNCHANGED by
  POSTS-B. Still pending deploy. **Any gateway image built now includes the QUALITY-A fix.**
- **insight-azteca-flutter** — own Activity → real posts, composer→Activity reconciliation, feed
  reconciliation consistent with backend fix. Requires an app build.

## Delta summary
| Component | Deployed | Code-ready | Needs deploy |
|---|---|---|---|
| insight-social | 0.1.8 | 0.1.9 (feed fix) | YES |
| insight-gateway | 0.1.13 | 0.1.14 (QUALITY-A avatar) | YES (independent of POSTS-B) |
| insight-azteca-flutter | (prior build) | POSTS-B app | YES (app build) |

The Social feed fix is the only backend change strictly required for the POSTS-B publishing outcome. The
Gateway 0.1.14 deploy carries the earlier QUALITY-A avatar capability (do not drop it).
