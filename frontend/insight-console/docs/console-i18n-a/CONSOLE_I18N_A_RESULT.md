# CONSOLE-I18N-A — Result & Classification

## Classification: **PARTIAL**
The production i18n **foundation is complete and building** (`tsc --noEmit` clean, `next build`
succeeds). EN + pt-BR, runtime switching with no reload, local persistence, system detection, and the
shared catalog are all in place and consumed by Navigation, the shell, the Control Panel chrome and the
Operations Center chrome. It is PARTIAL only because two **content-heavy** areas remain: the Control
Panel's 69-action catalog text (~345 technical strings) and the Operations Center's deep per-tab panel
bodies. Both now consume the established foundation — finishing them is data translation, not new
architecture.

## DoD status
1. Production i18n foundation — **DONE**.
2. Runtime language switching (no reload) — **DONE**.
3. English complete — **DONE** (English is the source + fallback).
4. Portuguese (Brazil) — **DONE for all translated surfaces**; pending for the remaining content above.
5. Operations Center translated — **PARTIAL** (chrome + tabs + summary done; deep panels pending).
6. Control Panel translated — **PARTIAL** (all chrome/labels/buttons/lifecycle/warnings done; action
   catalog content pending).
7. No hardcoded strings — **PARTIAL** (chrome/navigation/common: yes; action-catalog + deep panels: no).
8. Shared translation catalog — **DONE** (`common` + domain split, no duplication).
9. Local preference persistence — **DONE** (`localStorage: console.locale`).
10. Build passes — **DONE**.

## Validation (Stage 7)
- [x] `tsc --noEmit` — no errors.
- [x] `next build` — success (all routes, incl. `/operations` + `/operations/history`).
- [x] No missing-key crashes — `translate()` falls back locale → English → raw key.
- [x] Runtime switch — `useT` consumers re-render on `setLocale` (no reload), preference persists.
- [x] Consistent terminology — single shared catalog; operational nouns (Mission/Provider/Coverage/
      Readiness/Control Panel) defined once.

## To reach READY
1. Add `control-panel.actions.<id>.{description,impact,rollback,confirmation}` and render the catalog
   via those keys (keep risk/domain Pill tokens canonical).
2. Internationalize the Operations Center per-tab panels against the existing `operations` catalog
   (MetricGrid labels, section titles, insight/readiness copy).
3. Re-run `next build`; verify both locales end-to-end.

All future Console pages must consume `useT(...)` / the domain catalogs instead of hardcoding strings.
