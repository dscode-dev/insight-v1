# AZTECA V1 — Communities / Notifications / Realtime Backlog Dependency Map (Stage 9)

Three distinct concerns — do NOT merge. Realtime = transport/state sync. Notifications = user-facing
delivery + inbox. Communities = a product domain.

## AZTECA-COMMUNITIES-A
| Aspect | State | Evidence |
|---|---|---|
| Backend model | PARTIAL | Social has `communities` + `community_members` tables (00001) |
| Read API | PARTIAL/MOCK | `hub_service` → `/v1/hub/bundle`, `/v1/hub/communities/{id}` but backed by MOCK fixtures; membership "not in the mock yet" |
| Mutation API (join/leave) | UNKNOWN/ABSENT | no join/leave contract proven in Gateway |
| Flutter client/screen/nav | EXISTS (superficial) | `/hub`, `/hub/community/:id`, discussion threads; NOT in bottom nav |
| Membership/role/status | ABSENT | Profile ▸ Comunidades is placeholder |
Verdict: SUPERFICIAL. Needs real Gateway hub/community + membership endpoints (list, detail, join/leave, my-
communities). Backend-dependent.

## AZTECA-NOTIFICATIONS-A
| Aspect | State | Evidence |
|---|---|---|
| Backend read API | ABSENT | `notifications_v1` OFF → `/v1/notifications`, `/mark-all-read` don't exist; `notifications_service` mock fixtures |
| Push infra (FCM/APNs) | ABSENT | no firebase_messaging/push package in pubspec; no permission flow |
| Inbox/unread state | MOCK | in-memory mock list |
| Preference toggles | PARTIAL | push/email/digest flags persist via `/v1/users/me/preferences` but no delivery |
| Screen/nav | EXISTS | `/notifications` route + screen |
Verdict: NOT IMPLEMENTED. Needs: notifications backend (list/read/mark), push transport (FCM/APNs +
permission flow), inbox state. Large, multi-layer.

## AZTECA-REALTIME-A
| Aspect | State | Evidence |
|---|---|---|
| Transport | PARTIAL (hand-rolled) | `realtime_service.dart` connects `GET /v1/realtime/sse?access_token=` (SSE over HttpClient); mock fallback |
| Backend SSE route | UNKNOWN | `/v1/realtime/sse` referenced; existence unproven (gateway has realtime pkg — verify) |
| Reconnect / dedupe / background | PARTIAL/UNKNOWN | some structure in service; robustness unproven; `feed/updates` poll referenced (`pendingNewPostsProvider`) |
| Event model | EXISTS | `models/realtime_event.dart` typed events |
Verdict: PARTIAL foundation, unproven end-to-end. Needs a verified SSE backend + reconnect/dedupe/background
policy. Not user-visible today.

## Dependency graph
```
COMMUNITIES-A ── backend (hub/membership) ──▶ Profile▸Comunidades real, Hub real
NOTIFICATIONS-A ── needs ──▶ REALTIME-A (optional: push vs SSE) + notifications backend + FCM/APNs
REALTIME-A ── enables ──▶ LIVE (event push), NOTIFICATIONS (in-app), feed "new posts" pill (already stubbed)
```
- REALTIME-A is a prerequisite/accelerator for NOTIFICATIONS-A (in-app) and LIVE, but NOTIFICATIONS push can
  use FCM/APNs independently of SSE.
- COMMUNITIES-A is independent of Realtime/Notifications (pure product domain + backend).
- All three are **backend-blocked**: Azteca cannot complete any alone.

## V1 recommendation
COMMUNITIES-A, NOTIFICATIONS-A, REALTIME-A are **POST-V1** (or V1.1) — each needs net-new backend. For V1,
render honest placeholders (already done via feature gates) and keep Profile▸Comunidades honest-empty.
