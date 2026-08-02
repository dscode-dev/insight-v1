# AZTECA-PROFILE-B — Settings Matrix

Every visible Settings row classified (traced UI → state → persistence → restart). Largely established truthful
in QUALITY-A; re-verified here. No UNKNOWN remains.

| Row | Class | Persistence | Restart | Notes |
|---|---|---|---|---|
| Conta ▸ Nome de usuário | NAVIGATION/read-only | — | — | display only (@username), not editable |
| Conta ▸ Telefone | read-only | — | — | display only |
| Aplicativo ▸ Tema (system/light/dark) | DEVICE_LOCAL | secure storage (ThemeStore) | survives | QUALITY-A; real |
| Cache ▸ Limpar cache de imagens | CAPABILITY (local action) | n/a | n/a | real: `imageCache.clear()` |
| Notificações ▸ Push | REMOTE | `PUT /v1/users/me/preferences` | survives | pref persists; delivery is a future capability (no push infra yet) |
| Notificações ▸ E-mail | REMOTE | prefs PUT | survives | pref persists; delivery future |
| Notificações ▸ Frequência do resumo | REMOTE | prefs PUT | survives | real |
| Idioma | REMOTE | prefs PUT (locale) | survives | value persists; full UI translation is future (labeled) |
| Esportes ▸ Time favorito | DISABLED_FUTURE | — | — | honestly disabled "Em breve" (unmodeled) |
| Esportes ▸ Competições que sigo | DISABLED_FUTURE | — | — | honestly disabled "Em breve" |
| Privacidade ▸ Política de Privacidade | NAVIGATION | — | — | opens bundled sheet |
| Sobre/Legal ▸ Termos/Privacidade/UGC/Central | NAVIGATION | — | — | bundled sheets; AllBlue-Labs (QUALITY-A) |
| Sobre ▸ Insight · AllBlue-Labs · 2026 | read-only | — | — | correct org (QUALITY-A) |
| Sessão ▸ Sair | REMOTE (session) | `authProvider.logout()` clears tokens/session | survives (logged out) | real |

## DECORATIVE_BUG resolved
None found that mutate fake state. The notification/language toggles genuinely persist a remote preference
(REMOTE); their downstream *delivery/translation* is a future capability, not a lie about persistence. Sports
rows are honestly disabled. No toggle "appears functional but does nothing".

## Verdict
Settings is TRUTHFUL: every row is REMOTE (persists), DEVICE_LOCAL (persists), NAVIGATION (real destination),
CAPABILITY (real local action), or DISABLED_FUTURE (honestly labeled). No changes required this sprint beyond
what QUALITY-A already fixed.
