# AZTECA V1 — Finite Closure Roadmap (Stage 14)

Derived from evidence. The working hypothesis was reordered/merged: Search/Communities/Live-Radar/
Notifications/Realtime are backend-blocked → moved to V1.1/POST-V1. V1 closure = 4 focused sprints + certify.

## Sprint 1 — AZTECA-QUALITY-A  (independent; do FIRST)
- Objective: green, trustworthy baseline + store-blocking legal correction.
- Why: 6 failing tests (stale nav + unstubbed feed harness); theme not persisted; legal reads KonohaLabs.
- Repos: insight-azteca-flutter (+ store metadata).
- Backend: none. Migrations: none. Deploy: app build only.
- Flutter: fix nav widget-type tests + feed test harness (override socialApiProvider) + api_client env
  assertion; persist theme (local/secure); legal → **AllBlue-Labs** (+version bump + re-acceptance);
  a11y pass on settings.
- Acceptance: `flutter analyze` clean; `flutter test` all green; theme survives restart; legal shows
  AllBlue-Labs; store metadata publisher = AllBlue-Labs.
- Non-goals: no new features, no redesign.

## Sprint 2 — AZTECA-POSTS-B  (depends on QUALITY-A)
- Objective: composer ergonomics + resolve the disappearing-post UX + (optional) GIF.
- Why: composer field padding/caret/growth; own-post/feed-semantics mismatch; GIF desired.
- Repos: azteca-flutter (+ insight-social/gateway IF own-post-in-Global or GIF proxy chosen).
- Backend: OPTION A (no backend) — post-publish confirmation routes user to Profile▸Atividades + a
  transient "posted" state, stop pretending Home retains it. OPTION B (backend) — include author's own
  recent posts in `/v1/feed/global`. GIF (optional): `/v1/gifs/*` BFF proxy + metadata attachment.
- Migrations: none (metadata-based GIF) unless first-class media column chosen.
- Flutter: composer padding/caret/growth/scroll/duplicate-submit; GifProvider + GifPostRenderer + picker (if GIF).
- Acceptance: created post is always discoverable post-refresh (via Atividades or Global-with-own-posts);
  composer meets Instagram/Threads-grade field ergonomics; regression test locks the behavior.
- Non-goals: no feed redesign; GIF only if proxy lands.

## Sprint 3 — AZTECA-PROFILE-B  (depends on QUALITY-A; parallel to POSTS-B)
- Objective: real Edit Profile + reliable avatar + honest tabs.
- Why: Edit button misrouted to avatar-only; avatar MinIO-conditional; Comunidades tab placeholder.
- Repos: azteca-flutter + insight-gateway/insight-social (PATCH profile) + Gateway MinIO confirm.
- Backend: add `PATCH /v1/users/me` (display_name, bio, favorite_team, location); confirm/repair MinIO
  wiring so `/v1/users/me/avatar` registers.
- Migrations: none (fields exist on users) — verify.
- Flutter: Edit button → real form; avatar as sub-action; 404-aware avatar messaging; keep Atividades real;
  Comunidades honest-empty until COMMUNITIES-A.
- Acceptance: edit name/bio/team persists + reloads; avatar upload succeeds against a MinIO-wired Gateway (or
  a precise unavailable message); no fabricated tab content.
- Non-goals: no communities backend, no tab redesign.

## Sprint 4 — AZTECA-INSIGHTS-A  (independent; low-risk)
- Objective: accessible intelligence-UI primitive kit rendering ONLY real data.
- Why: metrics/probabilities desired; no chart lib; must not fabricate.
- Repos: azteca-flutter (+ fl_chart dependency).
- Backend: none for profile metrics; match intelligence deferred with Live/Radar.
- Flutter: metric/delta/probability/confidence/arrow primitives (custom) + fl_chart sparkline; a11y
  (icon+text+direction, semantics, contrast, reduced-motion); apply to profile stats now.
- Acceptance: primitives render real profile metrics; zero fabricated numbers; a11y checks pass.
- Non-goals: no Live/Radar data (backend-absent).

## Sprint 5 — AZTECA-V1-CERTIFY-A  (depends on 1-4)
- Objective: forensic re-audit + store-readiness certification of the frozen V1 boundary.
- Acceptance: every V1_REQUIRED item READY on real data; analyze+test green; legal AllBlue-Labs; avatar
  reliable; disappearing-post resolved; honest placeholders for deferred domains; store metadata correct.
- Non-goals: no new domains.

## Deferred (V1.1 / POST-V1, each backend-blocked; sequence after certify)
SEARCH-A (search backend) · COMMUNITIES-A (hub/membership backend) · LIVE-RADAR-A (live/context/radar
backends over Atlas) · NOTIFICATIONS-A (notif backend + FCM/APNs) · REALTIME-A (SSE hardening).

## Independence / prerequisites
- QUALITY-A: strict first (unblocks trust + store gate).
- POSTS-B, PROFILE-B, INSIGHTS-A: can run in parallel after QUALITY-A (INSIGHTS-A fully independent).
- CERTIFY-A: strict last.
- All deferred sprints: strictly blocked on their backends.
