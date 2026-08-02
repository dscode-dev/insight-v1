# AZTECA V1 — Backend Contract Gap Matrix (Stage 12)

Classes: EXISTS_AND_USED · EXISTS_NOT_USED · PARTIAL_CONTRACT · CLIENT_EXPECTS_MISSING_BACKEND ·
BACKEND_EXISTS_MISSING_CLIENT · MISSING_BOTH · NOT_REQUIRED_FOR_V1. Owner in parens.

| Capability | Contract | Class | Notes |
|---|---|---|---|
| Create post | `POST /v1/posts` (Social) | EXISTS_AND_USED | persisted; text-only |
| List feed | `GET /v1/feed/global`,`/following` (Social) | EXISTS_AND_USED | own posts excluded by design (root cause) |
| Feed updates | `GET /v1/feed/updates` (Social) | EXISTS_NOT_USED (partial) | `pendingNewPostsProvider` stubbed |
| Get post | `GET /v1/posts/{id}` (Social) | EXISTS_AND_USED | |
| User posts (activity) | `GET /v1/users/{id}/posts` (Social) | EXISTS_AND_USED | Profile▸Atividades; reliable recovery surface |
| Comments/replies | `GET/POST /v1/posts/{id}/comments` (Social) | EXISTS_AND_USED | depth-bounded |
| Like | `POST/DELETE /v1/posts/{id}/like` (Social) | EXISTS_AND_USED | |
| Save | `POST/DELETE /v1/posts/{id}/save` + `/v1/me/saved-posts` (Social) | EXISTS_AND_USED | |
| Boost | `POST/DELETE /v1/posts/{id}/boost` (Social) | EXISTS_AND_USED | |
| Interaction states | `POST /v1/posts/interaction-states` (Social) | EXISTS_AND_USED | hydration |
| Follow/mute | `POST/DELETE /v1/follow|mute/{id}` (Social) | EXISTS_AND_USED | |
| Sports profile | `GET /v1/users/{id}/sports-profile` (Social) | EXISTS_AND_USED | grouped stats + versioned avatar |
| Avatar upload | `POST /v1/users/me/avatar` (Gateway+MinIO) | PARTIAL_CONTRACT | route CONDITIONAL on MinIO; 404 when MinIO absent |
| Profile edit (name/bio/team/location) | `PATCH /v1/users/me` | CLIENT_EXPECTS_MISSING_BACKEND | no edit contract; Edit button misrouted to avatar |
| Preferences | `GET/PUT /v1/users/me/preferences` (Gateway) | EXISTS_AND_USED | language/notif-flags/digest |
| Agents | `GET /v1/agents`,`/{id}`,`/{id}/posts` (Social) | EXISTS_AND_USED | |
| Communities (list/detail) | `/v1/hub/*` (Gateway/Social) | PARTIAL_CONTRACT | mock-backed; membership absent |
| Community membership (join/leave/my) | — | MISSING_BOTH | needed for Profile▸Comunidades |
| Unified search | `GET /v1/search` | MISSING_BOTH | no search backend; Explore is a stub |
| Live matches | `/v1/live/*`,`/v1/context/*` | CLIENT_EXPECTS_MISSING_BACKEND | gated OFF; DTOs modeled |
| Radar signals | `/v1/radar/*` | CLIENT_EXPECTS_MISSING_BACKEND | gated OFF; DTOs modeled |
| Notifications | `/v1/notifications*` | CLIENT_EXPECTS_MISSING_BACKEND | gated OFF; mock |
| Push transport (FCM/APNs) | device push | MISSING_BOTH | no push package/permission flow |
| Realtime updates | `/v1/realtime/sse` | PARTIAL_CONTRACT | client hand-rolled; backend unproven |
| GIF attachment metadata | post metadata + `/v1/gifs/*` proxy | MISSING_BOTH | text-only model; needs BFF proxy |
| Settings: theme persistence | local storage | CLIENT-side gap | session-only today |
| Moderation (report/block) | `/v1/admin/moderation/*` + user block | EXISTS (partial client) | block APIs exist; UGC report UI present (Store-A) |

## Owner summary
- **Social**: post/feed/comment/like/save/boost/follow/agents/sports-profile — the strong, complete core.
- **Gateway**: preferences (real), avatar (MinIO-conditional), hub proxy (mock), moderation.
- **Missing backends (blockers)**: profile-edit PATCH, unified search, community membership, live/context,
  radar, notifications+push, GIF proxy, realtime SSE (verify).
