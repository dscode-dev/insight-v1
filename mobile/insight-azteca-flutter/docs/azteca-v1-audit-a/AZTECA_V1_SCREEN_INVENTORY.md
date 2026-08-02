# AZTECA V1 — Screen & Route Inventory (Stage 1)

Routes from `lib/routing/routes.dart` + `lib/routing/router.dart`. Classification is evidence-based.
Shell tabs (StatefulShellRoute): Home `/`, Live `/live`, Radar `/radar`, Search `/search`, Profile `/profile`.

| Route | Screen | Class | Data source / evidence |
|---|---|---|---|
| `/splash` | Splash | READY | boot + auth redirect |
| `/auth/entry,phone,otp,username` | Auth | READY | `auth_service` → `/v1/auth/*` (phone+OTP+refresh) |
| `/onboarding/welcome,about,competitions,teams` | Onboarding | PARTIAL | competitions real; team/prefs persistence via preferences |
| `/` | Home/Feed | READY | `FeedNotifier`→`/v1/feed/global,following`; pagination+refresh real |
| composer (ComposerScreen, pushed) | Post composer | PARTIAL | `POST /v1/posts` real+persisted; UX defects (Stage 2); text-only |
| `/post/:postId` | Post thread/detail+comments | READY | `getPost`+`listComments`+`createComment` real |
| `/users/:userId` | Public profile | READY | `sportsProfile`+`userPosts` real |
| `/profile` | Owner profile | PARTIAL | identity/stats/activity real; Edit=avatar-only; Comunidades tab placeholder |
| `/profile/settings` | Settings | PARTIAL | prefs remote; theme session-only; many nav-only (Stage 4) |
| `/agents`, `/agents/:agentId` | Agents list/profile | READY | `listAgents`/`getAgent`/`agentPosts` real |
| `/search` | Explore/Search | SUPERFICIAL | `search_screen.dart` only: empty→`_Discovery`, query→`_NoResultsYet` (no service, no `/v1`) |
| `/live`, `/live/match/:matchId` | Live | NOT IMPLEMENTED | `live_v1` OFF → `/v1/live/*`,`/v1/context/*` absent → "Em breve" |
| `/radar` | Radar | NOT IMPLEMENTED | `radar_v1` OFF → `/v1/radar/*` absent → "Em breve" |
| `/hub`, `/hub/community/:id` | Communities (Hub) | SUPERFICIAL | `hub_service` mock fixtures; `/v1/hub/*` unproven; not in bottom nav |
| `/discussion/:discussionId` | Discussion thread | PARTIAL | `discussion_service` exists; tied to hub |
| `/notifications` | Notifications | NOT IMPLEMENTED | `notifications_v1` OFF; mock fixtures; `/v1/notifications*` absent |
| error/not-found | GoRouter errorBuilder | UNKNOWN — REQUIRES LIVE VALIDATION | present; not exercised here |

## Per-route notes
- **Home**: loading (shimmer), empty, error states present; pull-to-refresh + infinite scroll real; deep-link OK.
- **Composer**: submission pending + failure handled; duplicate-submit guard needs verification (Stage 2); draft store present.
- **Profile owner**: 3 tabs — Atividades (real `userPosts`), Comunidades (placeholder text), Estatísticas (real grouped stats). Edit button misrouted to avatar upload.
- **Live/Radar/Notifications**: screens render a calm placeholder by design (gated) — honest, not broken. Cannot be V1 without backend routes.
- **Search**: renders but never returns results — decorative.

## Summary counts
READY 6 · PARTIAL 5 · SUPERFICIAL 2 · NOT IMPLEMENTED 3 · UNKNOWN 1.
