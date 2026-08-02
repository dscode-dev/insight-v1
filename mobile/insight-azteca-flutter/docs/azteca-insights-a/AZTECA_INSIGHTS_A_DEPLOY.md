# AZTECA-INSIGHTS-A — Manual Deployment (USER-OPERATED)

Agent did NOT deploy.

## Repositories changed
- **insight-azteca-flutter only** (semantic model, primitives, Profile Statistics integration, tests).
- **No backend change.** insight-social + insight-gateway untouched. **No migration.** Atlas untouched.

## Build
```
flutter build ipa --dart-define=ENVIRONMENT=production      # or: flutter build appbundle
```
No new dependency (chart deferred) ⇒ no pubspec/lockfile churn beyond the tree.

## Version lineage (unchanged by this sprint)
| Component | Deployed | Code-ready |
|---|---|---|
| insight-gateway | 0.1.13 | **0.1.15** (QUALITY-A avatar 503 + PROFILE-B PATCH proxy) — still pending, unchanged here |
| insight-social | 0.1.8 | **0.1.10** (POSTS-B feed self-post + PROFILE-B PATCH handler) — still pending, unchanged here |
| azteca-flutter | prior build | **INSIGHTS-A app build** |

⇒ This sprint requires **only a Flutter app build**. The pending backend deploys are inherited from
POSTS-B/PROFILE-B and are independent of INSIGHTS-A.

## Prechecks (read-only)
`GET /v1/users/{id}/sports-profile` → 401 unauth (route registered) — the only contract this sprint consumes.

## Rollback
Previous app build. Nothing else to roll back (no backend/migration).
