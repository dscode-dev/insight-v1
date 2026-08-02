# CONSOLE-I18N-A — Internationalization Foundation — Audit & Report

## Stage 0 — Audit findings
- Console: Next.js 14 (App Router) + React 18 + TS + Tailwind. **No i18n library** existed; every
  string was hardcoded English.
- **Operations Center** = `/operations` → `OperationalCommandCenter` (1603 lines, 10 tabs: Overview /
  Infra / Missions / Explorer / Atlas / Providers / Timeline / Coverage / Intelligence / Incidents).
- **Control Panel** = `/operations/history` → `OperationsCenter` (517 lines): a 69-action control
  catalog + preview/lifecycle surface.
- Repeated terminology to keep consistent: Mission, Provider, Coverage, Readiness, Service Registry,
  Operation, Control Panel, status tokens (healthy/running/completed/…), severities, buttons.
- Shared chrome with hardcoded strings: sidebar nav (groups + items), header ("Operational Command
  Center", "Sign out"), degraded/empty/loading states.

## Architecture delivered (Stages 1–2, 5, 6)
- `lib/i18n/config.ts` — `Locale = en | pt-BR`, default en, `detectSystemLocale()` (pt-* → pt-BR,
  en-* → en, fallback en), `normalizeLocale`, storage key.
- `lib/i18n/messages/` — **domain-split catalogs** (never one giant file): `common`, `navigation`,
  `operations`, `control-panel`, assembled in `index.ts` with `translate(ns, locale, key, vars?)`
  (locale → English → raw-key fallback + `{var}` interpolation).
- `lib/i18n/provider.tsx` — client `I18nProvider` (system detect on first mount, localStorage persist,
  `document.documentElement.lang`), `useLocale`, `useT(namespace)`. Runtime switch, **no reload**, all
  lookup logic centralized (no duplication).
- `components/console/language-switcher.tsx` — EN / Português (Brasil) selector (immediate switch).
- Mounted in `app/(console)/layout.tsx` (wraps the shell in `I18nProvider`); new client `ConsoleHeader`
  carries the translated title + switcher + sign-out.

## Translated (no remaining hardcoded strings)
- **Navigation/shell**: all sidebar group + item labels, header title, sign out, language label.
- **Common** (Stage 5): loading/no-data/unknown/retry + status (healthy/running/completed/…) + severity
  (info/warning/critical/…) + buttons + table headers — shared keys, no duplication.
- **Control Panel (chrome)**: title, subtitle, refresh, safety banner + execution-disabled message,
  control-surface header + hint, filter, tabs (incl. domain labels), context metrics, all six preview
  labels (Description/Impact/Affected services/Rollback/Permission/Confirmation), operation preview,
  all four action buttons (+busy states), execute-disabled, full operation-lifecycle block,
  permission summary, empty state.
- **Operations Center (chrome)**: title, subtitle, refresh, degraded banner, **all 10 tab labels**,
  Executive Summary heading + subtitle.

## Remaining work (for PARTIAL → READY)
- **Control Panel**: the 69-action operational catalog content (per-action `description`/`impact`/
  `rollback`/`confirmation`, ≈345 technical strings) is still English — these are *data*, not chrome,
  and need careful operational translation. The structure to translate them (a `control-panel.actions.*`
  sub-namespace keyed by action id) is ready.
- **Operations Center**: the deep per-tab panel bodies (MetricGrid label arrays, per-section titles
  across Infrastructure/Missions/Explorer/Atlas/Providers/Timeline/Coverage/Intelligence/Incidents,
  insight/readiness copy). The foundation is wired in this component (`useT("operations")`) — remaining
  strings consume the same `operations` catalog.
- Status tokens rendered via the shared `<Pill>` are intentionally kept canonical (color-mapped tokens);
  their meaning is conveyed by color + translated labels around them.
