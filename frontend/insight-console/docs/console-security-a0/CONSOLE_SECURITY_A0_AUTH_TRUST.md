# CONSOLE-SECURITY-A0 — Stage 1: Authentication & Session Trust Audit

The real, current trust chain (no invented claims).

| # | Question | Reality (CONFIRMED) |
|---|----------|---------------------|
| 1 | How the Console authenticates | Operator logs in at the **cloud Gateway** `POST /v1/operator/auth/login`; Gateway issues an **opaque session token**. Live: login → 400 (needs body), i.e. real endpoint. |
| 2 | Where session state lives | Gateway-owned `operator_sessions` table in **cloud Postgres `insight_auth`** (CONFIRMED live: `operator_sessions` exists). Console stores only the opaque token in an HttpOnly cookie `insight_console_session`. |
| 3 | Artifact reaching the BFF | The opaque token (cookie), forwarded server-side as `Authorization: Bearer` to the Gateway. |
| 4 | Verified claims | The Gateway verifies the session server-side: `token_hash = sha256(token)` ∧ `revoked_at IS NULL` ∧ `expires_at > now()` ∧ `is_active`. Live: `/v1/operator/auth/me` → 401 without token. |
| 5 | User ID derivation | From the Gateway `/v1/operator/auth/me` response (`operator.id`). Server-verified. |
| 6 | Roles | From the same response (`operator.role`, normalized SuperAdmin/Operations/Support/Analyst/ReadOnly). |
| 7 | Permissions | Gateway-issued permission set (`console/roles.go`). The frontend uses them only for affordances; the BFF re-checks. |
| 8 | Session ID | **YES** — the real session key is `sha256(token)` (the Gateway's `token_hash`). Non-secret, stable, distinct from correlation/request ids. Used for `OperatorContext.sessionId`. |
| 9 | Auth strength | **ABSENT** in the `/me` contract → modeled `null` (not fabricated). |
| 10 | Issuer/audience validation | Opaque token (not a JWT to the Console) → issuer/audience N/A at the Console; server-side session validation is the trust anchor. |
| 11 | Refresh/revocation | **YES** — `POST /v1/operator/auth/refresh`, `/logout`; `revoked_at`/`expires_at` enforced. Real, revocable. |
| 12 | Cloud identity == Console operator? | **Currently the SAME concept** — the operator session IS the cloud identity. CONSOLE-IDENTITY-A will split identity/operator/agent. Until then `identityId == operatorId` (documented). |

**Trust anchor:** a server-verified, revocable, expiring operator session at the cloud Gateway,
backed by durable `operator_sessions` in `insight_auth`. This is a solid foundation for trusted
attribution. Absent claims (authStrength, authenticatedAt) are modeled honestly as `null`.
