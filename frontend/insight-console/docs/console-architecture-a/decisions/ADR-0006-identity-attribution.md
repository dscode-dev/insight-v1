# ADR-0006 — Operator identity is bound server-side; deprecate client-asserted actor strings

**Status:** Proposed

**CURRENT STATE:** Two real mutation paths attribute the actor with **client-supplied strings**:
moderation `moderator_id` (in the POST body, under a shared service token) and Explorer
`X-Operator` (a plain header). Atlas uses a static `X-Internal-Token` with no operator identity.

**PROBLEM:** Attribution is forgeable/asserted, not proven. A control plane's audit and
authorization must bind to a **verified operator session**, not a value the caller chooses.

**DECISION:** Every privileged call carries a **verified operator identity** derived at the
mutation point — either the operator session Bearer re-validated by the service, or a **signed,
short-lived control-plane assertion** minted by the boundary (contains operator_id, capabilities,
correlation_id, expiry). Deprecate `X-Operator` and client `moderator_id`; the service reads the
actor from the verified identity only.

**RATIONALE:** Trustworthy audit + authz require unforgeable attribution. This is the prerequisite
for ban/suspend/publish/cancel to be safe.

**MIGRATION IMPACT:** Moderation handler re-derives moderator from the session; Explorer accepts a
control-plane assertion instead of `X-Operator`; Atlas reads stay internal-token for now (frozen,
read-only) but move behind the boundary (ADR-0003).

**RISKS:** Coordinated change across gateway + services (mitigate: additive — accept both, then
remove the string). Assertion signing key management (mitigate: boundary-held, rotated).
