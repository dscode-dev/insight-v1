# AZTECA V1 — Settings Functionality Audit (Stage 4)

Design is accepted — NOT redesigned. `settings_screen.dart` + `settings_provider.dart` +
`preferences_service.dart`. Classification per item.

| Setting | Class | Evidence |
|---|---|---|
| Theme (light/dark/system) | **SESSION_ONLY** | `themeModeProvider` StateProvider; `settings_provider.dart:4` "Not yet persisted across restarts" — toggles but does not survive restart |
| Language / Idioma | **REMOTE_PERSISTED** | `notifier.setLocale` → `preferences_service.update(locale)` → `PUT /v1/users/me/preferences` (route exists, gateway main.go:530-532) |
| Notifications: push toggle | **REMOTE_PERSISTED (write path) / SUPERFICIAL (effect)** | `setPushEnabled`→prefs PUT persists the flag, but no push infra exists (`notifications_v1` OFF) — the toggle is stored, delivery is not wired |
| Notifications: email toggle | **REMOTE_PERSISTED (write) / SUPERFICIAL (effect)** | `setEmailEnabled` → prefs PUT; no email delivery proven |
| Notifications: digest frequency | **REMOTE_PERSISTED** | `_pickDigestFrequency` → prefs PUT |
| Privacy Policy / Terms / UGC / Legal Center | **NAVIGATION_ONLY** | `showPrivacyPolicy`/`showTermsOfUse`/`showUgcSafetyPolicy`/`showLegalCenter` open bundled sheets (`legal.dart`) |
| About (version/org) | **NAVIGATION_ONLY / DECORATIVE** | static "KonohaLabs · 2026" (`settings_screen.dart:255`) — legal-org issue (Stage 10) |
| Logout | **REMOTE_PERSISTED (session)** | `_confirmLogout` → `authProvider.notifier.logout()` → clears tokens + `/v1/auth` session; real |
| Blocked users | **UNKNOWN** | moderation_service has block APIs; a blocked-users management screen not confirmed here — verify live |
| Favorite team | **PARTIAL** | favoriteTeam surfaces in sports-profile; edit path not wired (see Edit-profile gap, Stage 3) |
| Biometric options | **NOT PRESENT / UNKNOWN** | no biometric package in pubspec; not implemented |
| Image cache clearing | **UNKNOWN** | avatar cache eviction exists (`avatar_cache.dart`); a user-facing "clear cache" action not confirmed |
| Environment switcher (dev/staging) | **LOCAL (dev-only)** | `InsightEnv.runtimeEnvironment`; guarded off in production builds |

## Key findings
1. **Theme is the clearest defect**: visually toggles, does not persist across restart (SESSION_ONLY) — the
   canonical "toggles but does not survive restart" case the sprint warned about. Fix: persist to secure/
   local storage (or preferences) in AZTECA-QUALITY-A/PROFILE-B.
2. **Notification toggles persist the preference but have no delivery** — honest UI risk: the toggle implies a
   capability that does not exist until AZTECA-NOTIFICATIONS-A. Recommend labeling as "preferences saved,
   delivery coming soon" or gating until push exists.
3. Legal/About and policy items are navigation-only (correct for their purpose) but carry the KonohaLabs→
   AllBlue-Labs legal correction (Stage 10).
4. Preferences read/write chain (`/v1/users/me/preferences`) is REAL and the backbone of persisted settings.

## Verdict
Settings is PARTIAL: preferences (language/notification-flags/digest) genuinely remote-persist; theme is
session-only; policy/about are navigation-only; notification delivery is absent. No item is BROKEN, but
several are SUPERFICIAL in effect.
