# Console Architecture Audit — Sprint 4.5 Part 1

Audit date: 2026-06-12. Scope: what the Console is today (Sprint 8
foundation), what Sprint 4.5 adds (publication & agent control), and
the boundaries the new surface must respect.

## 1. What exists today

```
insight-console/                  Next.js 14, app router, TS strict
├── app/
│   ├── layout.tsx                html className="dark" → DARK IS DEFAULT
│   ├── login/page.tsx            phone + verification login
│   ├── (console)/
│   │   ├── layout.tsx            sidebar shell, permission-filtered nav
│   │   ├── dashboard/            platform health tiles
│   │   ├── live/                 scheduler / live ops
│   │   ├── dlq/                  dead letter queue + replay
│   │   └── audit/                platform audit log (admin API)
│   └── api/
│       ├── auth/{login,logout,verify}/      session endpoints
│       └── v1/{audit,dlq,platform,providers,scheduler}/  BFF routes
├── lib/
│   ├── admin-api.ts              SERVER-ONLY client → ADMIN_API_BASE_URL
│   ├── api-guard.ts              requireOperator/requirePermission/withApiHandler
│   ├── session.ts                cookie → JWT verify → /v1/console/me
│   └── utils.ts                  cn(), time formatting
├── types/auth.ts                 Role + Permission unions, ConsoleOperator
└── components/ui/                badge, button, card, dialog (shadcn-style)
```

**Data flow (unchanged by this sprint):**
browser → `/api/**` (Console BFF, same origin) → upstream admin APIs.
Browser code never holds upstream URLs or tokens. Every `/api/v1/**`
handler starts with `requireOperator()`/`requirePermission()` and is
wrapped in `withApiHandler()` (structured errors, correlation ids).

**Auth:** session cookie → JWT verify (jose) → operator hydrated from
the admin API `/v1/console/me` with `role` + `permissions[]`. The
frontend treats permissions as UI hints only; the BFF re-validates on
every call (IDOR/escalation defence, Sprint 8 Part 15).

**Theme:** dark-first is already true (`className="dark"` on `<html>`),
tokens are CSS variables in `globals.css` (Linear/Vercel/Stripe
reference set), `.table-operational` provides dense tables.

## 2. What Sprint 4.5 adds

Historical note: Sprint 4.5 temporarily used a direct Nexus admin API
for publication and agent controls. Robozao-Readiness-A removes that
direct integration. Current Console operational data sources are:

- Insight Gateway through `ADMIN_API_BASE_URL`.
- Robozao Gateway through `ROBOZAO_GATEWAY_URL`.

Publication, agent, Explorer, LLM and future Robozão operational
surfaces must be exposed through Robozao Gateway contracts, not through
service-specific Console clients.

| Surface | Reads | Writes (all audited in Nexus) |
| --- | --- | --- |
| /publication-center | GET /v1/publications/{tickets,candidates,history} | PATCH /v1/publications/tickets/{id} |
| ticket detail | GET ticket + explainability fields | PATCH (review/edit), POST /tickets/{id}/publish |
| manual publication | GET /v1/personas | POST /v1/publications/manual |
| /agents | GET /v1/agents, /v1/publications/agent-metrics, /v1/personas | PUT /v1/agents/{id} (enable/disable), PUT /v1/personas/{slug} |
| /llm | GET /v1/llm/health | — |
| /audit (publications tab) | GET /v1/audit/events | POST /v1/audit/events (console-origin events) |
| /analytics/publications | GET /v1/publications/history + candidates | — |

The Console remains a pure API consumer. It does not own business
logic, write service databases, mint service-specific admin tokens, or
talk directly to Atlas, Explorer, Nexus, or Sport Hub.

## 3. New libraries (server-side)

- `lib/robozao.ts` — server-only client for `ROBOZAO_GATEWAY_URL`.
- `lib/permissions.ts` — Sprint 4.5 tier mapping over the existing
  Role union (no backend change needed):
  - `viewer`  ← ReadOnly, Support — see everything, mutate nothing
  - `admin`   ← Operations, Moderator, MLAdmin — review tickets,
    approve/reject/edit, publish, manage agents
  - `super_admin` ← PlatformAdmin, SuperAdmin — admin + persona
    editing + manual publication as any agent
- `lib/console-metrics.ts` — in-process counters exposed as Prometheus
  text at `GET /api/metrics`:
  `console_ticket_reviews_total{action}`, `console_publications_total`,
  `console_manual_publications_total{agent}`,
  `console_agent_changes_total{action}`,
  `console_provider_incidents_total{provider}`,
  `console_audit_events_total`.

## 4. Attribution chain

Every operational action must resolve the operator through Gateway and
flow through Robozao Gateway. Service-specific mutation contracts are
pending and must preserve Gateway-owned operator identity.

## 5. Non-negotiables → enforcement points

| Rule | Enforced by |
| --- | --- |
| Console never owns business logic | Gateway and Robozao Gateway own backend contracts; Console displays/forwards only |
| Console never writes service DBs | no direct DB/service admin client in the Console |
| Everything through APIs | browser → /api only; server → `ADMIN_API_BASE_URL` or `ROBOZAO_GATEWAY_URL` |
| Every change auditable | future operational actions must carry Gateway operator identity through Robozao Gateway |
| Every publication explainable | future publication surfaces must be returned by the operations contract, never recomputed in the Console |
| Every manual action attributable | future action contracts must reject missing Gateway operator identity |
| Dark mode first | already the default (`html.dark`); new components use existing tokens |

## 6. Gaps / accepted debt

- Console nav advertises routes that have no pages yet (users, feed,
  atlas, flags, config) — Sprint 8 leftovers, untouched here.
- Direct service integrations were removed in Robozao-Readiness-A.
  Future action contracts must be added to Robozao Gateway first.
- `console_*` metrics are per-process (Next.js single instance);
  multi-replica deployment would need an aggregation strategy.
