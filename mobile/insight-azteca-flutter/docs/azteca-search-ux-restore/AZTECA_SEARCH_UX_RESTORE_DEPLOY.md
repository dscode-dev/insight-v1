# AZTECA-SEARCH-UX-RESTORE — Deploy (USER-OPERATED)

**Somente Flutter precisa de novo build.** Backend Search inalterado.

- insight-social: **inalterado** — permanece social 0.1.11 (não muda).
- insight-gateway: **inalterado** — permanece gateway 0.1.16 (não muda).
- Migrations: nenhuma. Contratos: nenhum. Ranking/score/cursores/cache/rate-limit/capabilities/deep-links:
  nenhum.

## Build
```
cd insight-azteca-flutter
flutter pub get
flutter build ipa      --dart-define=ENVIRONMENT=production   # iOS
flutter build appbundle --dart-define=ENVIRONMENT=production   # Android
```

## Smoke visual
Ver AZTECA_SEARCH_UX_RESTORE_SMOKE.md.

## Rollback
Reinstalar o build Flutter anterior. Sem rollback de backend (nada mudou lá).
