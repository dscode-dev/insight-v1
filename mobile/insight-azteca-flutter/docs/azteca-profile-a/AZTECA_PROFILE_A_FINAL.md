# AZTECA-PROFILE-A — Sports Identity & Public Profiles — FINAL

Unified the Profile into a single Sports Identity architecture used by both the logged-in user and
any public user. `flutter analyze` → No issues. Profile/Settings only (Home/Feed/Composer/Nav/Auth
untouched). Backend is the source of truth; no mock data.

## Unified architecture (Stage 1)
- **`widgets/sports_profile_header.dart`** — `ProfileIdentity` (display name, @username, initials,
  accent, reputation + optional location/team/followers/communities/posts/signals) + `ProfileLevel`
  (5 tiers derived from reputation) + `SportsProfileHeader` (avatar → names → optional context line →
  quiet metrics strip → an `actions` slot). One header, never aware of where it was opened from.
- **`widgets/profile_actions.dart`** — `OwnerProfileActions` (Edit/Settings) vs `PublicProfileActions`
  (Follow/Unfollow · Message[disabled] · More→moderation menu). Owner-only controls never render on
  someone else's profile and vice-versa (Stage 3).
- Both `profile_screen.dart` (own) and `user_profile_screen.dart` (public) now compose
  `SportsProfileHeader` + `InsightSegmentedControl` + `IndexedStack` — **no duplicate header**.

## Sports Identity (Stage 2)
Avatar · Display Name · @username · (location/favorite team when available) · metrics strip
(Level + Reputation, plus followers/communities/posts/signals when available). Clear hierarchy, no
oversized cards, no heavy borders. Fields the backend doesn't return yet are simply omitted —
future-ready, no placeholders.

## Public (Stage 3) & Own (Stage 4)
- Public: real Follow/Unfollow (`userRelationProvider`, optimistic+rollback), Message disabled
  ("em breve"), More → `showProfileMenu` (report/block/mute). Never shows Edit Profile.
- Own: Edit (reuses the REAL avatar pick→preview→upload flow) + Settings; personal Statistics tab
  (reputation/posts/signals/accuracy + badges). Same layout as public.

## Tabs (Stage 5) & State (Stage 8)
`InsightSegmentedControl` with 4 tabs — Atividade · Sinais · Comunidades · Estatísticas. Selection
persists per profile via `profileSectionIndexProvider` (family keyed `'me'`/userId, non-autoDispose);
`IndexedStack` keeps each tab mounted so scroll position is preserved. Settings keeps its scroll via
`PageStorageKey`.

## Settings (Stage 6)
Eight grouped categories: **Conta** (username/phone) · **Aplicativo** (theme) · **Idioma** ·
**Esportes** (favorite team / competitions — prepared, honestly disabled) · **Privacidade** (privacy
policy + blocked accounts + biometric, prepared) · **Notificações** (push/email/digest, real) ·
**Suporte** (legal center/terms/UGC) · **Sobre** · **Sessão** (logout). Each item: icon · title ·
optional subtitle · chevron · soft grouped background. Business logic unchanged.

## Navigation (Stage 7)
Feed and now **comment/post authors in the thread** navigate to the SAME unified profile (agents →
agent profile, users → public Sports Profile). Search is discovery-first (no per-user results). No
navigation to placeholder pages.

## Performance (Stage 8) & Accessibility (Stage 9)
Shared header/action widgets (zero duplication), stable `ValueKey`s on post lists, `IndexedStack`
reuse, family providers ready for future realtime. Semantics on avatar/actions/segments/metrics/tiles;
≥44dp targets; dynamic text via theme.

## DoD
1 unified architecture ✅ · 2 public completed ✅ · 3 own improved ✅ · 4 sports identity ✅ ·
5 navigation fixed ✅ · 6 segmented control (4 tabs) ✅ · 7 settings reorganized ✅ ·
8 state persistence ✅ · 9 accessibility ✅ · 10 analyze passes ✅.
