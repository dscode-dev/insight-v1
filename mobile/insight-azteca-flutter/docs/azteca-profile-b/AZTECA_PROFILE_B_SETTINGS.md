# AZTECA-PROFILE-B — Settings Truthfulness

Full classification in SETTINGS_MATRIX.md. Settings was made truthful in QUALITY-A (theme device-local +
persisted; prefs remote + persisted; About = AllBlue-Labs; sports rows honestly disabled; logout real; cache
clear real). This sprint re-verified every row and found **no decorative bug** requiring a fix.

## REMOTE (persist through real API, survive restart)
Language (locale), notification push/email toggles, digest frequency → `PUT /v1/users/me/preferences`.
Note: the notification toggles persist a real preference; downstream push DELIVERY is a future capability
(no push infra) — this is honest (the setting saves state; it does not falsely claim delivery works).

## DEVICE_LOCAL (persist locally, survive restart, degrade safely)
Theme (ThemeStore/secure storage — QUALITY-A). Reuses the established local persistence architecture; no new
storage layer.

## NAVIGATION (real destinations)
Privacy/Terms/UGC/Legal Center sheets; About. No dead routes.

## CAPABILITY (real local action)
Clear image cache (`imageCache.clear()`), Logout (`authProvider.logout()` — clears tokens/session).

## DISABLED_FUTURE (honestly labeled)
Esportes ▸ Time favorito / Competições — "Em breve", not fake toggles.

## Result
No setting appears functional but does nothing. No changes needed beyond QUALITY-A. Verified against actual
behavior, not labels.
