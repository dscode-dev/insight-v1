# CONSOLE-SOCIAL-A — Investigation Workspace & Information Architecture (Stages 17-19)

## Information architecture (domain-local, coherent — not 10 new global sidebar items)
One **Social** group with a domain-local secondary nav (audit the existing `nav-config.tsx` +
`(console)` layout before wiring — add ONE top-level "Social" entry, sub-navigation inside the domain):
```
Social
├── Overview            /social
├── Activity            /social/activity
├── Content
│   ├── Posts           /social/posts        · /social/posts/{id}
│   └── Comments        /social/comments     · /social/comments/{id}
├── Identities
│   ├── Users           /social/users        · /social/users/{id}
│   └── Agents          /social/agents       · /social/agents/{id}
├── Communities         /social/communities  (only if schema supports)
├── Relationships       /social/relationships
├── Trust & Safety
│   ├── Reports         /social/reports      · /social/reports/{id}   (gateway-sourced)
│   └── Moderation      /social/moderation
└── Investigation       /social/investigation/{entityType}/{id}
```

## Investigation deep-link model (stable routes, not React state)
`/social/investigation/{entityType}/{id}` where entityType ∈ {user, agent, post, comment, community,
report}. The route IS the investigation truth — deep-linkable + reopenable. Tabs are query params
(`?tab=timeline`), not component state. Entity summary pages (`/social/users/{id}` etc.) link INTO the
investigation view; a breadcrumb preserves the trail.

## Investigation panels (all read-only, honest partial state per panel)
`Summary · Timeline · Related Content · Relationships · Reports · Moderation · Audit Evidence`. Each
panel is independently loaded and independently degradable (a failed Reports panel does not blank the
page — Stage 20). `EntityReference` is the uniform drill-down cell so every entity everywhere is
one click from its investigation.

## Partial-data & failure UX (Stage 20 — reuse FOUNDATION-A error model)
Every surface renders one of: loading · empty · **partial** · unavailable · unauthorized · error ·
success — **distinctly**. Never render `0`/`[]` for an unavailable source; the read models carry
`sources[]` with per-source state so the UI shows "unknown (source unavailable)" instead of a fake
zero. One failed panel never destroys the workspace.

## UX posture (Stage 19)
Information density over decoration: data tables + compact filters + split detail panes + breadcrumbs
+ status chips + compact identity cells + readable timelines. No oversized cards, no fake KPIs, no raw
JSON as primary UI, no modal chains. The operator always knows: where am I / what entity / what
happened / who did it / what's connected / what to investigate next.

## Observability (Stage 23)
Per-capability request count + latency + upstream errors + partial-data count + timeout count, via the
existing control-plane observability convention. **No user/post ids as metric labels** — label by
capability only.
