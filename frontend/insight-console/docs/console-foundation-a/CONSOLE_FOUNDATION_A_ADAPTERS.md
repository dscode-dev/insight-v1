# CONSOLE-FOUNDATION-A — Typed Adapters & Error Model

## Base — `adapters/base.ts`
Single server-side transport. Not a generic proxy: every call targets a **fixed** config/registry-
resolved upstream + **fixed** path — the browser can never choose a host or path.
- Bounded timeout (default 5s) via `AbortController`; response-size cap (2 MB); JSON validation.
- Canonical error normalization (see below) + per-source attribution (`SourceStatus`) on success
  AND failure. Tokens injected here from server config, never returned.
- Small capability-oriented interface `HealthReadable` (Atlas ≠ Social ≠ Anvil — no god interface).

## Service adapters (only what current reads need)
| Adapter | Reads | Auth (server-side) | Notes |
|---------|-------|--------------------|-------|
| `atlas.ts` | `GET /health` | `X-Internal-Token` | Atlas 1.0.0 **frozen** — consume only |
| `explorer.ts` | `GET /health` | none | version/active_jobs surfaced when present |
| `nexus.ts` | `GET /healthz` | none | unconfigured ⇒ CONFIGURATION_ERROR (honest) |
| `gateway.ts` | `GET /v1/console/platform/health` | service token + operator Bearer | returns cloud per-service map + gateway self |
| `robozao.ts` | `GET /operations/status` | operator Bearer | returns robozão per-service map + self |

## Normalized error model — `errors.ts`
11 canonical codes distinguishing the failure modes the audit found conflated:
`CONFIGURATION_ERROR, SERVICE_UNAVAILABLE, TIMEOUT, UNAUTHORIZED, FORBIDDEN, UPSTREAM_ERROR,
INVALID_RESPONSE, CAPABILITY_UNSUPPORTED, CAPABILITY_UNAVAILABLE, NOT_FOUND/BAD_REQUEST, PARTIAL_DATA`.
- `retryable` + `httpStatus` derived per code; upstream failures are **not** flattened to 200.
- `normalizeThrown` maps AbortError→TIMEOUT, connection errors→SERVICE_UNAVAILABLE, and **never
  leaks** the raw message/host (tested: `ECONNREFUSED 10.0.0.1` → generic "upstream unreachable").
- `sourceStateForCode` maps codes → per-source `SourceState` for snapshots.

## Tested failure matrix (`tests/control-plane-adapters.test.ts`)
success · 503→SERVICE_UNAVAILABLE · 401→UNAUTHORIZED · 500→UPSTREAM_ERROR · malformed→INVALID_RESPONSE
· AbortError→TIMEOUT · connection-refused→SERVICE_UNAVAILABLE (no host leak) · unconfigured→CONFIGURATION_ERROR.
Also verified: the internal token is sent upstream but never appears in the adapter result.
