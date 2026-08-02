# CONSOLE-SOCIAL-B — Security

## Trust boundary
Browser → Console BFF (/api/v1/social/*) → Gateway command plane (/v1/console/social/*) → moderation
(Gateway-owned) / Social agent state. Browser never reaches Social; no service token in browser; no
cross-domain join in browser.

## Every mutation (defense in depth)
1. **Console service token** (consolemw `requireConsoleSvc`) — only the Console BFF can reach the command routes.
2. **Verified operator session** (`requireOperatorFull`) — operator id/role/session derived server-side from `operator_sessions`.
3. **Capability authorization** (`authorizeCap`) — the operator's role must carry the exact permission; registry presence never grants; SuperAdmin bypass is the pre-existing platform rule. Fail-closed.
4. **Actor-strip** — the command body decodes ONLY reason/report_id/suspend_days; operator/moderator/actor/session fields are never read (structurally impossible + tested).
5. **Canonical audit intent** BEFORE mutation; **outcome** after (see AUDIT_FLOW). High-impact fails closed if intent cannot be recorded.
6. Console BFF independently re-authorizes the capability before calling the Gateway.

## Secrets
Canonical audit `sanitizeMeta`/forbidden-key filter drops token/secret/password/cookie/authorization/
credential/bearer. Command responses carry no host/topology/trace/secret. Reason text is bounded (≤512).

## Read-only elsewhere preserved
No new generic mutation surface. `execution_enabled` remains false. Atlas 1.0.0 untouched. A2 read
privacy (aggregate-only saves, no saver reader) preserved + regression-tested.
