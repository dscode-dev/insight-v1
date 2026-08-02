# CONSOLE-ARCHITECTURE-A — Stage 9: Refactor Blueprint

Incremental, **non-rewrite** plan. The Console must stay usable throughout. Each item is
KEEP / REFACTOR / MOVE / DEPRECATE / REMOVE with a concrete reason.

---

## 1. KEEP (foundation — do not disturb)
- Server-first Next.js shell, `(console)` layout, middleware correlation + cookie gate.
- `lib/admin-api.ts` (typed gateway seam, Zod, ConsoleApiError, timeouts, correlation).
- `lib/api-guard.ts` / `lib/session.ts` (operator resolution, `requireOperator/Permission`,
  `withApiHandler`).
- **Moderation Center** and **Publication Center** — the two real control surfaces; the pattern.
- Audit Center (the audit spine reader).
- i18n foundation (do not expand this sprint).

## 2. REFACTOR
| Target | Action | Reason |
|--------|--------|--------|
| `operational-command-center.tsx` (**1606 LOC**) | **Decompose** into per-domain surfaces (Infra, Missions, Explorer, Atlas, Providers, Timeline, Coverage, Incidents) with lazy loading + per-surface error boundaries; move derived scoring behind clearly-labelled heuristic helpers | Oversized, mixed concerns, shared error array, browser-derived "truth" |
| Client 10s polling | Convert live tabs to **SSE**; keep summaries on backed-off polling | Efficiency, ordering, lag (ADR-0008) |
| `operations-adapters.ts` topology maps | Read from **registries** | Hardcoded topology (ADR-0001) |
| `lib/operations-domain.ts` | Repoint to **Operation Service**; remove SuperAdmin bypass; drive real transitions | Ephemeral/racy/audit-bypass (ADR-0004/0005) |
| Moderation attribution | Bind operator server-side | Client-supplied `moderator_id` (ADR-0006) |

## 3. MOVE
| Element | From → To | Reason |
|---------|-----------|--------|
| Operation domain logic + storage | Console BFF → **Operation Service** (durable) | Platform state, not frontend state |
| Atlas/Explorer adapters + internal tokens | Console BFF → **boundary adapters** | Secrets + trust boundary (ADR-0003/0008) |
| Topology metadata | Console constants → **Service/Environment Registry** | Single source of truth |

## 4. DEPRECATE
- `lib/db.ts` (already a no-op stub) and the `pg` dependency — remove once confirmed unused.
- Direct-service internal-token seam (`lib/cloud.ts`) — deprecate as boundary adapters land.
- `/audit/publications` — fold into unified Audit Center.

## 5. REMOVE (dead / superseded)
- `/atlas` index page (empty shell) → redirect to `/atlas/intelligence`.
- `/console/[...path]` catch-all — audit and remove if it serves nothing real.
- Duplicate surfaces after merge: `/cloud` (→ Operations→Infra), `/explorer` (→ Data group),
  `/data-intelligence/dashboard` (→ Mission/Dataset), `/dashboard` tiles (→ real home or drop).
- `/live` if confirmed superficial.

## 6. Structural cleanups
- **Oversized components:** `operational-command-center` (1606), `operations-center` (523),
  `moderation-center` (336), `data-intelligence-center` (265) → extract presentational leaf
  components + typed domain hooks.
- **Mixed server/client:** keep pages server-first; push interactivity into small client leaves,
  not 1600-line client trees.
- **Duplicated derived-state logic:** centralise `num/text/pct/rows` helpers and readiness/coverage
  heuristics into one clearly-named `lib/heuristics` module labelled "not platform truth".
- **Duplicated adapters:** one adapter per domain; delete overlaps between `cloud.ts`,
  `operations-adapters.ts`, `robozao.ts`.
- **Route restructuring:** collapse duplication clusters (IA-7); align routes to capability
  domains (Platform / Social / Identity / Agents / Intelligence / Data / Realtime / Support /
  Governance).
- **BFF restructuring:** thin handlers; shared control-plane contract types generated from the
  boundary; no domain logic in `app/api`.

## 7. The mega-component decision (explicit, as mandated)
`operational-command-center.tsx` **must be decomposed** — but **not in this sprint** beyond, at
most, a *tiny non-behavioral extraction* if needed for validation. It is simultaneously the
Console's most-used surface and its worst structural liability (1606 LOC, 10 tabs, 8 polled
endpoints, browser-derived scoring, shared error array, no pagination). Decomposition is scheduled
into **CONSOLE-SERVICE-OPS-A** (Stage 10), executed behind unchanged routes so operators see no
disruption. Real health tabs are preserved; derived "intelligence" is demoted to labelled
heuristics or replaced by service-reported facts.

**Blueprint verdict:** No rewrite. ~6 KEEP anchors, a bounded set of REFACTOR/MOVE items driven by
the ADRs, and a clear DEPRECATE/REMOVE list that shrinks surface area while preserving the two real
control flows.
