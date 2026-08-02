# ADR-0005 — Single canonical audit spine; every mutation emits `insight.operational_event.v1`

**Status:** Proposed

**CURRENT STATE:** A real audit spine exists at the gateway (`/v1/console/audit`,
`AuditService.Query/Append`) recording admin reads + moderation. **But** the Operation domain's
events live only in a JSON file, and mutations attribute via client-supplied strings.

**PROBLEM:** Audit is partial and bypassable. Approvals and operation lifecycle are not
tamper-evidently recorded. Who-did-what-why-where-result cannot be reconstructed across the
control plane.

**DECISION:** **One audit spine owns all control-plane audit.** Every read-of-sensitive-data and
every mutation emits a canonical `insight.operational_event.v1` event with `operator_id`,
`correlation_id`, `target_service/resource`, before/after state, and capability id. The Operation
Service, Social admin, Identity admin, and all adapters emit through it. IOC operational events
(Atlas, Explorer, robozão) are **consumed** into the same correlation model.

**RATIONALE:** Audit is a platform guarantee, not a per-surface afterthought. Correlation ids
already flow end-to-end; this closes the loop into a single queryable, tamper-evident spine.

**MIGRATION IMPACT:** Route Operation-domain events to the spine; add emission to each new
mutation. Audit Center reads the unified spine (subsumes `/audit/publications`).

**RISKS:** Volume/retention (mitigate: tiered retention, indices on correlation/operator/
resource). Must not block mutations on audit write (mitigate: durable async with at-least-once).
