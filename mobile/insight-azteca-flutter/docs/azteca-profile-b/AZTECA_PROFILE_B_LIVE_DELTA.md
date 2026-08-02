# AZTECA-PROFILE-B — Deployed vs Code-Ready (read-only)

## Deployed (live probes)
gateway **0.1.13**, social **0.1.8**. `GET /v1/users/{id}/sports-profile` → 401 (registered).
`GET /v1/users/me` → 401 (matches `{userId}` GET). `PATCH /v1/users/me` → **405** (no PATCH handler deployed →
confirms the write contract is NOT live yet). `POST /v1/users/me/avatar` → 404 (QUALITY-A 0.1.14 not deployed).

## Version lineage (cumulative — never drop a prior fix)
| Component | Deployed | After QUALITY-A | After POSTS-B | After PROFILE-B |
|---|---|---|---|---|
| insight-gateway | 0.1.13 | 0.1.14 (avatar 503) | 0.1.14 (unchanged) | **0.1.15** (+ PATCH /v1/users/me proxy) |
| insight-social | 0.1.8 | 0.1.8 | 0.1.9 (feed self-post) | **0.1.10** (+ PATCH profile handler) |
| azteca-flutter | prior | QUALITY-A | POSTS-B | PROFILE-B app build |

`insight-gateway:0.1.15` includes BOTH the QUALITY-A avatar fix AND the POSTS-B-era feed (no gateway change)
AND the PROFILE-B PATCH proxy. `insight-social:0.1.10` includes the POSTS-B feed fix AND the PROFILE-B PATCH
handler. No migration in any of these.
