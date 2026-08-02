# AZTECA V1 — Scope Freeze Proposal (Stage 13)

Principle: V1 is a **coherent professional social+identity product** built on what genuinely works today,
plus the smallest set of high-value closures. Strict boundary — no endless expansion.

## V1_REQUIRED (must ship; mostly real today + finite fixes)
- Authentication (phone+OTP+refresh) — READY.
- Feed (global/following, pagination, refresh) — READY; + fix own-post/feed-semantics UX.
- Text posts + composer — REAL; + composer ergonomics fix (padding/caret/growth, duplicate-submit).
- Comments/replies, Like, Save, Boost — REAL; + rollback/counter verification.
- Profile (owner+public), sports identity, Estatísticas — REAL.
- Profile ▸ Atividades (persisted posts recovery surface) — REAL.
- Edit Profile — FIX misroute: real edit form + `PATCH /v1/users/me` (name/bio/team/location) [backend dep].
- Avatar upload — make reliable: confirm MinIO in deployed Gateway + client 404 messaging.
- Follow/unfollow — REAL.
- Settings — make theme persist; keep prefs (language/notif-flags/digest) real; keep policy nav-only.
- Legal terms/policies — correct to **AllBlue-Labs** (+version bump + re-acceptance). Store gate.
- Quality: fix stale nav tests + feed test harness; analyze clean.

## V1_OPTIONAL_IF_LOW_RISK (include only if its backend prerequisite lands cleanly)
- GIF posts — only if the GIF BFF proxy (`/v1/gifs/*`) + metadata attachment ship; else POST-V1.
- Explore as a real BROWSE hub (agents/competitions/trending via existing list endpoints) — no search backend needed.
- Sports intelligence UI primitives (metric/delta/probability/confidence/sparkline) rendering ONLY the
  real profile metrics now; match intelligence deferred with Live/Radar.

## V1_1
- Unified Search (needs new search backend) — AZTECA-SEARCH-A.
- Communities (needs hub/membership backend) — AZTECA-COMMUNITIES-A.
- Notifications inbox + preferences delivery — AZTECA-NOTIFICATIONS-A.

## POST_V1
- Live + Radar (large net-new backend over Atlas/Explorer/Anvil + match state) — AZTECA-LIVE-RADAR-A.
- Realtime SSE hardening + push transport (FCM/APNs) — AZTECA-REALTIME-A.
- Full match intelligence visualization (once Live/Context/Radar exist).
- Players/teams search entities.

## Justification highlights
- Live/Radar/Notifications/Realtime are correctly gated OFF (backend-absent) — shipping them now = fake
  product. Deferring is honest and keeps V1 finite.
- Search/Communities need net-new backends → V1.1, not V1.
- The V1 core (social+profile) is already real; V1 = polish + fix + legal + reliability, not new domains.

## Explicit V1 freeze boundary
V1 = Auth + Feed + Text(±GIF) posts + Comments/Replies + Like/Save/Boost + Profile(+Edit+Avatar+Activity+
Stats) + Follow + Settings(persisted) + Legal(AllBlue-Labs) + honest placeholders for the rest.
Everything else is explicitly out until its backend exists.
