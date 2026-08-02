# CONSOLE-ARCHITECTURE-A — Stage 1: Information Architecture Audit

**Subject:** insight-console 0.3.18 — Next.js 14.2.15 App Router, React 18. 34 pages, 25 BFF
routes, 2 layouts. **31/34 pages are server components**; only 3 are client. Almost no
client state layer (one provider: i18n; zero `use*` hooks/stores). Data flows: thin server
`page.tsx` → `*-Center` component (mostly presentational) → `lib/*` adapter or Console `/api`.

**Classification key:** A OPERATIONAL · B OBSERVATIONAL · C SUPERFICIAL · D DUPLICATED ·
E PREVIEW-ONLY · F DEAD/OBSOLETE · G FOUNDATION.

---

## 1. Navigation vs. reality

`components/console/nav-config.tsx` exposes **5 groups / 16 items**: Operations (Operations
Center, Control Panel, DLQ), Intelligence (Atlas Intelligence, Atlas Knowledge), Data (Mission
Center, Dataset Center, Sources, Tickets), Realtime (Publication Center, Publication Analytics,
Moderation), Administration (Authentication, Audit, Users, Operators, Sessions).

**Finding IA-1 (orphans):** 12+ built pages are **not reachable from navigation** —
`/dashboard`, `/agents`, `/llm`, `/cloud`, `/live`, `/explorer`, `/atlas` (index),
`/data-intelligence/dashboard`, `/data-intelligence/executions`, `/audit/publications`,
`/publication-center/manual`, `/console/[...path]`. Several are stale precursors of the
consolidated command center.

**Finding IA-2 (coarse nav RBAC):** 13/16 nav items gate on `console.access` — the sidebar is
effectively all-or-nothing. Real per-capability authorization is deferred to the BFF, so nav is
not a meaningful permission surface.

---

## 2. Page & capability matrix

| Route | Purpose | Data source | Real backend? | Mutates? | Audited? | Value | Class | Recommendation |
|-------|---------|-------------|---------------|----------|----------|-------|-------|----------------|
| `/operations` (OperationalCommandCenter) | 10-tab "command center" | 8 Console `/api` polled @10s | Partly (health real; readiness/insights derived) | No | No | Med | **C+G** | Decompose; keep real-data tabs, drop derived scoring |
| `/operations/history` (Control Panel) | Operation lifecycle list | `/api/v1/control/operations` (JSON file) | No (ephemeral file) | Preview only | Local only | Low | **E** | Move Operation domain to a real service |
| `/dlq` | Dead-letter queue view/replay | `/api/v1/dlq` + `/dlq/[id]/replay` | Depends on gateway/robozao DLQ | Maybe (replay) | Partial | Med | **A/B** | Verify replay backend; keep if real |
| `/atlas/intelligence` | Atlas intelligence view | `/api/v1/data-intelligence/atlas/*` → Atlas direct | Yes (Atlas 1.0.0) | No | No | High | **B/G** | Keep; align to frozen Atlas contracts |
| `/atlas/knowledge` | Atlas knowledge/graph | Atlas direct | Yes | No | No | Med | **B** | Keep |
| `/atlas` (index) | — | — | — | — | — | Low | **F** | Remove or redirect |
| `/data-intelligence/pipelines` (Mission Center) | Explorer missions | Explorer direct / robozao ops | Yes (Explorer) | **Yes** (start/estimate exist upstream) | Partial | High | **A/B** | Keep; wire real mission mutations behind approvals |
| `/data-intelligence/datasets` (Dataset Center) | Dataset inventory | Explorer datasets | Yes | No | No | Med | **B** | Keep |
| `/data-intelligence/sources` | Source health | Explorer/robozao | Yes | No | No | Med | **B** | Keep |
| `/data-intelligence/tickets` | Explorer tickets | robozao ops `/tickets` | Yes | No | No | Med | **B** | Keep |
| `/data-intelligence/executions` + `[id]` | Job executions | Explorer/robozao | Yes | No | No | Med | **B** | Keep; may merge into Mission Center |
| `/data-intelligence/dashboard` | DI summary | derived | Partly | No | No | Low | **C/D** | Merge into Mission/Dataset |
| `/data-intelligence/pipelines/[id]` | Mission drill-down | Explorer | Yes | No | No | Med | **B** | Keep |
| `/moderation` (ModerationCenter) | Reports + actions | `/api/v1/moderation/*` → gateway admin | **Yes** | **Yes** (dismiss/remove/restore/suspend/ban) | **Yes** (moderator_id) | High | **A** | **Keep — the one true control surface**; harden attribution |
| `/publication-center` (+`/manual`,`/tickets/[id]`) | Nexus publications | Nexus authed API | Yes (Nexus) | **Yes** (audited) | Yes | High | **A** | Keep; canonical example of real control |
| `/analytics/publications` | Publication analytics | Nexus | Yes | No | No | Med | **B** | Keep |
| `/agents` | Agent registry | social `AgentService` (List/Get) | Read-only | No | No | Med | **B** | Keep read; **agent admin has no backend** |
| `/auth` (Authentication) | Auth activity/metrics | `/api/v1/auth/activity` gateway | Yes | No | No | Med | **B** | Keep |
| `/audit` (Audit Center) | Audit log | `/api/v1/audit` → gateway `/v1/console/audit` | Yes | No | Read | High | **B/G** | Keep; this is the audit spine |
| `/audit/publications` | Publication audit | Nexus | Yes | No | Read | Med | **B/D** | Consider merge into Audit Center |
| `/administration/users` | User admin (read) | `/api/v1/admin/users` → gateway (GET) | Read-only | No | No | Med | **B** | Keep read; mutations missing |
| `/administration/operators` | Operator admin (read) | gateway `/v1/console/admin/operators` | Read-only | No | No | Med | **B** | Keep read; mutations missing |
| `/administration/sessions` | Session admin (read) | gateway `/v1/console/admin/sessions` | Read-only | No | No | Med | **B** | Keep read; force-logout missing |
| `/dashboard` (+DashboardLiveTiles) | Landing tiles | Console metrics/health | Partly | No | No | Low | **C/D** | Rework as real home or drop |
| `/cloud` (CloudEnvironment) | Cloud service health | `/api/cloud/services` → platform-health | Yes | No | No | Med | **B/D** | Merge into Operations→Infra |
| `/live` | Live/realtime view | UNKNOWN | UNKNOWN | No | No | Low | **C/F** | Verify; likely superficial |
| `/explorer` | Explorer view | Explorer direct | Yes | No | No | Low | **D** | Duplicates Data group; merge |
| `/llm` (llm-ops) | LLM/provider view | Nexus/qwen | Partly | No | No | Low | **C** | Keep minimal or merge |
| `/console/[...path]` | Catch-all passthrough | dynamic | UNKNOWN | — | — | Low | **F** | Audit & likely remove |

---

## 3. Structural findings

- **IA-3 — One mega-component dominates.** `operational-command-center.tsx` = **1606 lines**,
  `"use client"`, 10 tabs, **polls 8 endpoints every 10s**, and computes **readiness scores,
  insights, coverage, timelines client-side**. It absorbs CONSOLE-INTELLIGENCE-A +
  CONSOLE-ENTERPRISE-A. It is simultaneously the most valuable (real health tabs) and the most
  problematic (derived "intelligence", no pagination, no error boundaries per tab) surface.
- **IA-4 — Frontend-derived intelligence.** Readiness %, "insights", coverage %, health scores
  are computed in the browser from polled rows, not returned by a service. This is presentation
  masquerading as platform truth (Class C). It must not become the control plane's source of
  truth.
- **IA-5 — Real control is narrow but genuine.** Only **Moderation** and **Publication Center**
  are Class A (real, mutating, audited). Everything else is B/C. The Console today is ~85%
  viewer, ~15% controller.
- **IA-6 — Read-only administration.** Users/Operators/Sessions are genuine reads off the
  gateway but expose **zero mutations** (no suspend/ban/force-logout/role-change wired), despite
  the gateway RBAC catalog naming all of them.
- **IA-7 — Duplication clusters.** (a) `/cloud` vs Operations→Infra tab; (b) `/explorer` vs Data
  group; (c) `/data-intelligence/dashboard` vs Mission/Dataset centers; (d) `/audit/publications`
  vs Audit Center; (e) `/dashboard` tiles vs Operations overview.

**IA verdict:** The information architecture is **broad but shallow and viewer-biased**. It is
organised around *surfaces* (pages/tabs) rather than *capabilities* (typed, audited actions on
domain resources). The redesign must re-anchor on capability domains (Stage 3/7), collapse the
duplication clusters, and demote frontend-derived scoring to clearly-labelled heuristics.
