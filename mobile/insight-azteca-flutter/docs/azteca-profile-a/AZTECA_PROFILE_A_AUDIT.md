# AZTECA-PROFILE-A — Sports Identity & Public Profiles — Stage 0 Audit
## Before
- **Own profile** (`profile_screen.dart`): header (avatar/name) + 3-tab segmented control
  (Atividade/Sinais/Comunidades, from prior refinement) over a `profileBundleProvider`
  (UserStats reputation/posts/signals/accuracy + badges + activity).
- **Public profile** (`user_profile_screen.dart`): a SEPARATE, basic layout — avatar/name/reputation +
  Follow/Mute buttons over the user's posts. **Not unified** with the own profile (duplicate header).
- **Navigation**: feed cards → `openAuthorProfile` → `R.userProfileFor(id)` (works). Comment authors in
  the thread were **not** tappable. Search is discovery-first (no per-user results).
- **Backend identity available**: own = AuthUser(id/username/displayName/accentColor/avatarUrl) +
  UserStats(reputation/posts/signals/accuracy); public = SocialUserDto(…/reputation). **Not modeled:**
  location, favorite team, followers count, communities count, level. No "Edit Profile" screen exists.
- **Settings**: grouped soft cards (prior refinement) — Aplicativo/Notificações/Idioma/Conta e
  segurança/Suporte e legal/Sobre/Sessão.
## Decisions
1. One shared `SportsProfileHeader` + `ProfileIdentity` consumed by BOTH profiles (Stage 1).
2. Header renders location/team/followers/communities **only when present** (future-ready, no mock).
   `level` is derived from real reputation (presentation, not fabricated data).
3. Owner edit reuses the REAL avatar flow (no placeholder Edit screen).
4. Settings expands to the 8 requested categories; Sports/Privacy unbacked items are honestly disabled.
