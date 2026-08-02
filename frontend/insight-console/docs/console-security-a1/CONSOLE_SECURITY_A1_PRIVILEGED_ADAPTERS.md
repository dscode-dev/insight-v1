# CONSOLE-SECURITY-A1 — Privileged Adapter Closure & Legacy Inventory

## Explorer closure (Stage 10) — the SECURITY-A0 debt
`lib/control-plane/adapters/explorer-privileged.ts` (`explorerPrivilegedCall(operator, path, method,
body)`):
- `X-Operator` is derived **server-side** from the verified `OperatorContext`
  (`operatorUsername ?? operatorId`) — the browser has NO input to it (the adapter signature accepts
  no client actor).
- correlation propagated (`X-Request-Id` from `operator.correlationId`).
- observability (`privileged_adapter_request`/`failure`).
- The `data-intelligence/[...path]` route now builds `OperatorContext` and calls this adapter for all
  Explorer traffic (no direct privileged `fetch` in route/UI code).

**Honest note:** Explorer does not currently *verify* `X-Operator` — it is attribution metadata, not
authentication. This adapter guarantees the value is trustworthy on the Console side and contains the
flow behind one seam. Stronger Explorer-side operator verification is recorded as future debt (not
overstated as auth).

## Explorer call classification
| Path | Class | Handling |
|------|-------|----------|
| `/explorer/*` GET (missions/jobs/datasets/…) | AUTHENTICATED_READ | operator-bound adapter |
| `sources/enable`, `sources/disable`, `config.write` POST | PRIVILEGED_MUTATION | permission-checked + operator-bound adapter |

## Legacy privileged direct-client inventory (decisions)
| Client | Decision | Rationale |
|--------|----------|-----------|
| `lib/data-intelligence.ts` Explorer (`X-Operator`) | **WRAP_BEHIND_ADAPTER (done)** | now via `explorer-privileged` |
| `lib/data-intelligence.ts` Atlas (`X-Internal-Token`) | KEEP_TEMPORARILY | Atlas 1.0.0 **frozen, read-only**; service identity, server-only; reads stay behind the typed call — no Atlas mutation, no new Atlas contract |
| `lib/cloud.ts` | KEEP_TEMPORARILY | documented; internal creds server-only |
| `lib/operations-domain.ts` (`/tmp`) | KEEP_TEMPORARILY | attribution bound to OperatorContext + canonical audit; durable store = CONSOLE-OPERATIONS-A |
| Nexus publication routes | REMOVE_DEAD_CODE / NOT_IMPLEMENTED | empty scaffolds — no real mutation; **no fabricated publication audit** |

**No authoritative client-asserted actor identity remains.** Atlas is untouched (frozen).
