# CONSOLE-ARCHITECTURE-A — Stage 6: Authentication, Authorization & Audit Audit

Assesses whether today's administrative security is sufficient for future high-impact actions
(ban user, restore post, disable agent, publish as official Ninja, cancel mission, retry
ingestion, execute/rollback operations). **Design requirements only — nothing implemented.**

---

## 1. Current model (CONFIRMED)

### Authentication
- **Operator login** at the **cloud gateway** `/v1/operator/auth/login`; server issues an
  **opaque session token**. Console stores it in an **HttpOnly, SameSite=Lax** cookie
  (`insight_console_session`, 8h). `lib/session.ts`, `lib/api-guard.ts`.
- **Session resolution** via gateway `/v1/operator/auth/me`; gateway validates server-side:
  `operator_sessions.token_hash = sha256(token) AND revoked_at IS NULL AND expires_at > now()
  AND operators.is_active` → returns role (`console/handlers.go`). **Real, revocable, expiring.**
- **Edge middleware** gates on **cookie presence only** (no JWT verify at edge, by design); each
  server handler re-resolves via `currentOperator()`/`requireOperator()`.

### Authorization
- **RBAC catalog** in gateway `console/roles.go`: roles SuperAdmin/Operations/Support/Analyst/
  ReadOnly with a **rich permission set** (user.*, feed.*, scheduler.*, provider.*, model.*,
  dlq.*, audit.read, flag.*, config.*, maintenance_mode.toggle, console.access).
- **BFF enforcement:** every `/api/v1/**` handler calls `requireOperator()`/`requirePermission()`
  — "the frontend never decides" (defence against IDOR/priv-esc).

### Service-to-service
- **Gateway admin (moderation)** gated by **shared `X-Console-Service-Token`** (constant-time,
  fail-closed if empty) — `consolemw`. Authenticates *the Console server*, not the operator.
- **Console admin reads** (`/v1/console/*`) additionally require the **operator Bearer** and
  re-check role server-side.
- **Atlas** trusts a static `X-Internal-Token`; **Explorer** trusts an `X-Operator` **string**.

### Audit
- **Gateway audit spine** `/v1/console/audit` (`AuditService.Query`) records admin reads +
  moderation. **Operation-domain events do NOT reach it** (they live in the JSON file).

---

## 2. Findings

| # | Finding | Severity |
|---|---------|----------|
| SEC-1 | **Moderation attribution is client-supplied** (`moderator_id` in POST body) under a shared service token; the mutation point does not re-bind a verified operator session | **High** |
| SEC-2 | **Explorer identity is an unauthenticated `X-Operator` string** — any Console-side value is trusted | **High** |
| SEC-3 | **Atlas static internal token** — no operator identity on intelligence reads; shared secret | Med |
| SEC-4 | **RBAC vocabulary ≫ enforcement points** — permissions named for actions with no route (illusion of control) | Med |
| SEC-5 | **SuperAdmin permission bypass** in Operation domain (`role==="SuperAdmin" \|\| …`) | Med |
| SEC-6 | **Operation events bypass the audit spine** (no tamper-evident record of approvals) | **High** |
| SEC-7 | **No CSRF token** on state-changing `/api/v1` POSTs (SameSite=Lax is the only defence); no per-request replay/nonce | Med |
| SEC-8 | **No rate limiting** on Console BFF admin routes (observed) | Med |
| SEC-9 | **No dual-control / break-glass** for critical actions | **High** (for future) |
| SEC-10 | **No sensitive-action confirmation binding** (confirmation is UI-only, not server-enforced) | Med |
| SEC-11 | Correlation id propagated end-to-end; HttpOnly/secure cookie; fail-closed service token | ✅ Strengths |

---

## 3. Sufficiency for future actions (verdict per action)

| Future action | Sufficient today? | Missing |
|---------------|-------------------|---------|
| Ban user | ❌ | operator-bound attribution (SEC-1), audit-spine event, dual-control for permanence |
| Restore post | ⚠️ partial | attribution binding; otherwise moderation path is real |
| Disable agent | ❌ | backend contract + capability + audit |
| **Publish as official Ninja** | ❌ | **entire identity/delegation model** (`public_actor`/`executed_by`/`origin`/`operation_id`) — none exists |
| Cancel mission | ❌ | Explorer cancel contract + operator identity (SEC-2) + approval |
| Retry ingestion | ⚠️ | DLQ replay may exist; needs operator binding + audit |
| Execute operational action | ❌ | durable Operation Service + executor (out of scope now) |
| Rollback action | ❌ | rollback contract per operation; only a text field today |

---

## 4. Required security model (design requirements)

1. **Single trust boundary.** All privileged calls flow through the **control-plane boundary**
   (gateway or a control-plane service). Eliminate direct Console→Atlas/Explorer internal-token
   calls; replace with **operator-identity-bound, gateway-mediated** contracts.
2. **Operator identity bound at the mutation point.** Every mutating service re-derives the
   operator from a verified session (or a signed, short-lived control-plane assertion), never a
   client string. Deprecate `X-Operator`/client `moderator_id`.
3. **Capability-based authz** (`domain.resource.action`) enforced **server-side at the service**,
   not only the BFF. BFF stays as defence-in-depth.
4. **Canonical audit is mandatory and tamper-evident.** Every mutation emits
   `insight.operational_event.v1` to the **audit spine** with `operator_id` + `correlation_id` +
   before/after state. Approvals are audited events, not file writes.
5. **Dual-control + break-glass** for `critical` risk (ban permanence, official publishing,
   destructive ops): distinct approver identity ≠ creator; break-glass is time-boxed and
   loudly audited.
6. **Sensitive-action server-enforced confirmation** (typed confirmation token, short TTL,
   single-use) — not UI-only.
7. **CSRF + rate limiting + replay protection** on all BFF state-changing routes.
8. **Official-identity delegation model** (future sprint): explicit
   `public_actor: ninja_user`, `executed_by: owner:<operator-id>`, `origin: insight-console`,
   `operation_id: <id>` — **no silent impersonation**; internal audit always preserves the real
   operator.

**Security verdict:** The **authentication** foundation is solid (real, revocable operator
sessions; HttpOnly cookie; server-side role checks). The **authorization + attribution + audit**
model is **not yet sufficient** for a control plane: attribution is client-asserted on the two
real mutation paths, the audit spine is bypassed by the Operation domain, and no dual-control /
official-identity model exists. These are the gating security prerequisites for CONSOLE-SOCIAL-A
and any mutation sprint.
