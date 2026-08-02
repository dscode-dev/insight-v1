# ADR-0002 — Capability Registry with `domain.resource.action` grammar

**Status:** Proposed

**CURRENT STATE:** Two disconnected vocabularies exist: gateway `console/roles.go` permissions
(user.ban, feed.hide, scheduler.pause, model.promote, …) and the IOC-CONTROL-A action catalog.
Most permissions have **no backing route** (RBAC vocabulary ≫ enforcement points).

**PROBLEM:** Without a single capability model, permissions are a promise, not an enforcement
point; the Console cannot render "what can this operator do here" truthfully, and new mutations
have no canonical identifier for authz + audit + approval.

**DECISION:** Adopt one platform grammar — **`domain.resource.action`** (e.g.
`social.posts.moderate`, `explorer.missions.cancel`, `identity.sessions.invalidate`). A
**Capability Registry** binds each capability to: risk level, approval requirement, rollback
availability, affected services, and the backing service route. RBAC roles map to capability
sets. A capability is only "usable" when a real route exists.

**RATIONALE:** Aligns authz, audit, approval, and UI affordances on one identifier; makes the
"vocabulary ≫ contracts" gap visible and closable; seeds directly from `roles.go` + the action
catalog.

**MIGRATION IMPACT:** Normalise existing permissions into the grammar; mark capabilities without
routes as `contract_missing` (hidden/disabled in UI). Moderation and Nexus publishing are the
first fully-wired capabilities.

**RISKS:** Migration churn in permission strings (mitigate: alias table). Over-granular
capabilities (mitigate: derive from real resources, not speculation).
