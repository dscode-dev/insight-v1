# CONSOLE-SOCIAL-B — Post-Deploy Smoke Runbook (controlled)

Use DEDICATED test entities (a throwaway test user, a test post/comment, a non-critical agent fixture).
Do NOT ban/hide arbitrary real production users/content. Base = https://insight-api.konohalabs.com.br.
$TOK = a valid operator session with the required role (SuperAdmin for ban/hide/agent). Never paste secrets.

## Command shape (service-token added by the Console BFF; shown here direct-to-gateway for verification)
```
curl -s -X POST "$B/v1/console/social/users/$UID/suspend" \
  -H "Authorization: Bearer $TOK" -H "X-Console-Service-Token: $SVC" \
  -H "Content-Type: application/json" -d '{"reason":"smoke test","suspend_days":1}'
```

## Checklist (30)
1  unauthorized (no session) → 401.
2  authorized-but-missing-capability (e.g. Support role bans) → 403 forbidden_capability.
3  the 403 appears in `GET /v1/console/audit/events?outcome=DENIED` (DENIED intent recorded).
4  suspend test user → 200 resulting_state=suspended; audit AUTHORIZED+COMPLETED share one correlation_id.
5  existing test-user session no longer works for a mutation (revoked) — a post attempt returns 403 account_suspended.
6  suspended user READ (feed/GET) still works.
7  unsuspend → 200 active; the user can post again.
8  ban test user → 200 banned; sessions revoked.
9  banned user post/comment/like/follow/boost/save ALL → 403 account_banned (gap-closed paths).
10 unban → 200 active; participation restored.
11 hide test post → 200 hidden.
12 consumer feed + single post detail (`GET /v1/posts/{id}`) no longer expose the hidden post (404/absent).
13 operator investigation still shows the post (`/social/investigate/post/{id}`).
14 restore post → 200 visible; reappears.
15 hide test comment → 200 hidden.
16 thread integrity: replies remain; hidden parent absent from consumer list; operator sees it.
17 restore comment → 200 visible.
18 deactivate a non-critical test agent → 200 inactive; `agent_state_events` gets a row.
19 trigger that agent's publication path (Nexus/worker) → rejected (FailedPrecondition); `social_agent_publish_blocked_total` increments.
20 reactivate agent → 200 active; publication works again.
21 report review transition (test report) → 200 reviewing.
22 report resolve/dismiss per lifecycle → 200; illegal transition (e.g. →open) → 409.
23 moderation history (`/social/moderation`) shows the actions; distinct from Audit Center.
24 canonical audit correlation: one correlation_id links intent→outcome for each action.
25 duplicate command (same X-Request-Id) → idempotent: no duplicate audit rows, same resulting state.
26 retry after a timeout → safe (re-read state via `/enforcement/{type}/{id}` before retrying).
27 send `{"reason":"x","operator_id":"spoof","moderator_id":"spoof"}` → operator in audit is the SESSION operator, not "spoof".
28 no secret/token/host in any command response or audit metadata.
29 Atlas 1.0.0 untouched (no atlas calls/changes).
30 execution_enabled remains false; no generic /admin/execute exists (404).

## Console UI verification
`/social/investigate/{user|post|comment|agent}/{id}` shows the Enforcement panel (current state + typed
actions). Confirm: mandatory reason, expiry field for suspend, impact copy matches semantics, NO
optimistic success (spinner → server-confirmed state), 409 renders "state changed", 403 renders
"unauthorized". `/social/reports` → "Manage" opens report review/resolve/dismiss.
